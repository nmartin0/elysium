"""
run_sync.py  (copies the customer's own external data into Elysium's
local mirror -- one run, then exits)

Phase 2 of the read-only mirror architecture (see the roadmap (consumed)). A
SEPARATE PROCESS, deliberately, never a background thread inside the
web app -- a real, settled decision recorded in that section, for
three real reasons: it matches how every other entry point in
scripts/ already works; a sync copies entire tables, which would
otherwise compete with request handling in the same process (and
under the GIL, measurably slow it), while a badly-failing sync could
take the web server down with it; and it matches Foundry's own
precedent of running syncs as scheduled builds, separate from the
service answering queries.

This script performs ONE sync and exits. Scheduling is external and
deliberately not this script's concern -- a cron entry, a systemd
timer, a Kubernetes CronJob. Nothing here owns a timer or knows what
time it is beyond recording when a sync finished. That also means
"sync now" needs no special mechanism at all: running this script IS
the manual escape hatch.

WHAT IT SYNCS is derived entirely from the ontology itself (see
core/mirror/sync_targets.py), never from a second, separately-
maintained list -- so the mirror always holds exactly the tables the
ontology actually references, with no way for the two to drift apart.

READS THROUGH THE READ-ONLY ADAPTERS specifically (Phase 1 -- see
adapters/sqlite_adapter.py's own SQLiteReadAdapter), so this job is
structurally incapable of writing back to the customer's own data,
not merely intended not to.

FAILS LOUDLY, PER TABLE, leaving the last-good mirror in place for
whatever it couldn't sync -- matching this project's own established
"fail loudly, never silently substitute" discipline. A table that
fails does NOT abort the whole run: the other tables are genuinely
independent, and a partial refresh of the rest is strictly better
than none. Every failure is reported, and the process exits non-zero
so a scheduler actually notices rather than logging into the void.

Config and data are independent locations, resolved by
resolve_runtime_paths() exactly as every other entry point does --
this script never needs to know whether it is running locally or from
a real install.

Run from the project root:
    python3 -m scripts.run_sync
"""

import argparse
import contextlib
import json
import sys
import uuid
from typing import Any

from core.deployment_loader import (
    MirrorCatalogStranded,
    build_live_read_adapters,
    load_deployment_bundle,
    resolve_runtime_paths,
)
from core.mirror.classifications import record_classifications
from core.mirror.erasure import ErasureRegister, apply_erasures, suppression_for
from core.mirror.expectation_warnings import ExpectationWarnings
from core.mirror.gold import build_gold, published_ids
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.manifest import publish_manifest
from core.mirror.openlineage import (
    COMPLETE,
    DEFAULT_NAMESPACE,
    FAIL,
    RUN_JOB,
    START,
    LineageEmitter,
    gold_fields,
    lake_dataset,
    source_dataset,
)
from core.mirror.profiles import ProfileStore, profile_publications
from core.mirror.sync_attempts import SyncAttempts
from core.mirror.sync_lock import single_writer
from core.mirror.sync_targets import resolve_sync_targets
from core.sqlite_connection import (
    require_assertions_enabled,
    require_json_each,
)


def _evaluate_user_triggers(runtime_paths, config, mediator) -> None:
    """Runs everybody's triggers, each as its own owner.

    AFTER THE SYNC, like the mirror-health condition, because that is
    when the data changed. A trigger says WHAT to watch; the sync says
    when to look.

    NEVER RAISES INTO THE SYNC. The sync has done its work; failing to
    notice something about that work must not turn a successful sync
    into a failed one.
    """
    try:
        from core.count_condition import (
            evaluate_one_trigger,
            evaluate_user_triggers,
        )
        from core.notifications import NotificationStore
        from core.saved_views import SavedViewStore
        from core.triggers import TriggerStore
        from core.user_directory import UserDirectory

        triggers = TriggerStore(runtime_paths.data_dir / "triggers.db")
        # BOTH KINDS: made in the product, and declared in config.yaml.
        # They share owner resolution, the write mediator and the
        # evaluator -- a declared trigger is never a second code path.
        declared = list(config.declared_triggers)
        enabled = [*triggers.all_enabled(), *declared]
        if not enabled:
            return

        # ONLY THE OWNERS THAT ACTUALLY HAVE A TRIGGER. Resolving every
        # user would cost a lookup per account on a deployment where
        # nobody uses triggers at all.
        directory = UserDirectory(
            runtime_paths.data_dir / "credentials.db", config.roles,
        )
        # OWNERS, PLUS EVERY ACTIVE MEMBER OF A NAMED ROLE. Resolved
        # only for roles some trigger actually names, so a deployment
        # where nobody notifies a role pays for owners and no more.
        # A DISABLED ACCOUNT IS LEFT OUT, and so is never notified.
        named_roles = {
            role for trigger in enabled for role in trigger.recipient_roles
        }
        wanted = {trigger.owner_user_id for trigger in enabled}
        if named_roles:
            wanted |= {
                row["username"] for row in directory.list_users()
                # `role_name`, NOT `role` -- read from list_users()
                # rather than guessed. The guess matched nobody, and
                # would have notified no role member, silently.
                if row["role_name"] in named_roles and not row["disabled"]
            }
        owners = {}
        for user_id in wanted:
            try:
                if directory.is_user_disabled(user_id):
                    continue
                owners[user_id] = directory.get_user_record(user_id)
            except Exception:  # noqa: BLE001 - a removed account is skipped
                continue

        # A WRITE MEDIATOR ONLY IF SOME TRIGGER CAN PROPOSE. A sync
        # otherwise reads the source and nothing else -- that stays
        # true in the common case, and even here a proposal writes
        # nothing to the SOURCE, only a row to the approvals queue.
        write_mediator = pending_store = None
        if any(trigger.action_type for trigger in enabled):
            from datetime import timedelta

            from core.deployment_loader import build_generation
            from core.pending_write_persistence import PendingWritePersistence
            from core.pending_write_store import PendingWriteStore

            generation = build_generation(
                runtime_paths.config_dir, runtime_paths.data_dir,
                runtime_paths.log_dir,
            )
            write_mediator = generation.write_mediator
            mediator = generation.mediator
            # THE SAME DATABASE THE API READS, which is the whole reason
            # the store had to become database-authoritative first: a
            # proposal from this process now appears in Approvals
            # without the API restarting.
            pending_store = PendingWriteStore(
                ttl=timedelta(minutes=config.pending_write_ttl_minutes),
                audit_log=generation.mediator.audit_log,
                persistence=PendingWritePersistence(
                    runtime_paths.data_dir / "pending_writes.db",
                ),
            )

        notifications = NotificationStore(
            runtime_paths.data_dir / "notifications.db",
        )
        fired = evaluate_user_triggers(
            mediator, triggers,
            SavedViewStore(runtime_paths.data_dir / "saved_views.db"),
            notifications, owners, config.source_digest,
            write_mediator, pending_store,
        )
        # DECLARED TRIGGERS carry their view inline, so they skip the
        # saved-view lookup and go straight to the shared path.
        for trigger in declared:
            fired += evaluate_one_trigger(
                trigger, trigger.view, mediator, notifications, owners,
                config.source_digest, write_mediator, pending_store,
            )
        if fired:
            print(f"{fired} trigger(s) fired")
    except Exception as e:  # noqa: BLE001 - see the docstring
        print(f"could not evaluate triggers: {e}", file=sys.stderr)


def _notify_mirror_health(runtime_paths, config, attempts, targets,
                          drifts: "list | None" = None) -> None:
    """Tells whoever can fix the mirror that it needs fixing.

    NEVER RAISES INTO THE SYNC. The sync has already done its work and
    reported it; a failure to notice something about that work must
    not turn a successful sync into a failed one.

    RECIPIENTS COME FROM A GRANT, not a list. Whoever holds
    `manage:deployment` can start a sync, so whoever holds it should
    hear that one is needed -- and a deployment that adds or removes
    an administrator changes the recipient list by doing so.
    """
    try:
        from core.intermediate_layer.access_control import authorize
        from core.mirror.health_condition import (
            RECIPIENT_GRANT,
            notify_mirror_health,
        )
        from core.notifications import NotificationStore
        from core.user_directory import UserDirectory

        states = []
        for target in targets:
            attempt = attempts.last_for(target.silo_name, target.table_name)
            states.append({
                "silo": target.silo_name,
                "table": target.table_name,
                "last_synced_at": (
                    attempt.at.isoformat() if attempt else None
                ),
                "last_attempt_outcome": attempt.outcome if attempt else None,
            })

        # THE DIRECTORY IS BUILT HERE because a sync does not load one
        # -- it needs a config and adapters, not users. Reading the
        # same credentials database the API reads keeps one source of
        # truth about who exists.
        directory = UserDirectory(
            runtime_paths.data_dir / "credentials.db", config.roles,
        )
        recipients = [
            row["username"]
            for row in directory.list_users()
            if not row.get("disabled")
            and authorize(
                directory.get_user_record(row["username"]),
                config.roles, RECIPIENT_GRANT,
            )
        ]
        store = NotificationStore(runtime_paths.data_dir / "notifications.db")
        told = notify_mirror_health(states, recipients, store)
        if told:
            print(f"notified {told} administrator(s) about mirror health")
        # COLUMN DRIFT (R7), to the same people by the same grant.
        from core.mirror.health_condition import notify_column_drift
        if notify_column_drift(drifts or [], recipients, store):
            print("notified administrator(s) about column drift")
    except Exception as e:  # noqa: BLE001 - see the docstring
        # PRINTED, NOT LOGGED: this script has no logger, and a
        # message nobody sees is the failure mode this whole
        # condition exists to prevent.
        print(f"could not evaluate mirror health: {e}", file=sys.stderr)


def _propose_merges(store, config, object_type: str, type_def: dict,
                     rows_by_storage: dict) -> int:
    """Candidates a person should look at. Returns how many are new.

    NEVER APPLIES ANYTHING. A proposal sits in the store until somebody
    decides, and the next build reads only APPROVED ones -- which is
    why this can run unattended at all.

    AND IT NEVER BREAKS A SYNC. Inference is the optional half; if the
    extra is missing or the backend throws, the mirror and gold are
    still correct, so the failure is reported and the run continues.
    """
    from core.mirror.matching import SplinkMatcher, settings_for
    if not config.identity_inference or settings_for(type_def) is None:
        return 0
    try:
        candidates = SplinkMatcher().candidates(type_def, rows_by_storage)
    except Exception as exc:  # noqa: BLE001 - reported per type, like a sync
        print(f"WARNING gold.{object_type}: merges could not be proposed: {exc}",
              file=sys.stderr)
        return 0
    proposed = 0
    for candidate in candidates:
        before = len(store.proposals(object_type))
        store.propose(object_type, candidate.left_id, candidate.right_id,
                       candidate.score,
                       agreement=json.dumps(candidate.agreement, sort_keys=True))
        proposed += len(store.proposals(object_type)) - before
    return proposed


def _link_tables(schema: dict) -> dict[str, Any]:
    """{join table: the silo it lives in}, for many-to-many links.

    A LINK THROUGH A JOIN TABLE HAS NO OBJECT TYPE. Customer.tags is
    resolved by reading `customer_tags`, which is not a type, is not
    conformed and has no gold table of its own -- so a read from gold
    could not follow the link at all until gold published it too.

    PUBLISHED AS IT STANDS, without conforming: there is no ontology
    shape for a row that is nothing but two foreign keys, and inventing
    one would mean deciding what a link row IS, which nobody has asked
    for.
    """
    tables: dict[str, Any] = {}
    for type_def in (schema or {}).values():
        own_table = (type_def.get("storage") or {}).get("table")
        for field_config in (type_def.get("fields") or {}).values():
            if field_config.get("type") != "link":
                continue
            via_table = field_config.get("via_table")
            if not via_table:
                continue
            target = (schema or {}).get(field_config.get("target")) or {}
            target_table = (target.get("storage") or {}).get("table")
            if via_table in (own_table, target_table):
                continue
            tables[via_table] = ((target.get("storage") or {}).get("silo")
                                  or (type_def.get("storage") or {}).get("silo"))
    return tables


#: Which silver snapshot a gold link table was copied from.
LINK_SOURCE_PROPERTY = "elysium.link_source_snapshot"


def _publish_link_tables(sync, schema: dict) -> None:
    """Copy each join table into gold, unchanged.

    NOT DROPPED AND RECREATED, which is what this did on every sync until
    14 Oct: between the drop and the create, a reader following a
    many-to-many link found no table at all, and every run threw the
    table's history away to write the same rows back.

    NOW: skipped when silver has not moved since the copy (the snapshot
    it was copied from is stamped on it, as gold types stamp their
    inputs -- PA001-G11), and otherwise OVERWRITTEN IN PLACE, one atomic
    commit, so a reader sees the old rows or the new ones and never
    nothing. Dropped only when the columns themselves changed, which an
    overwrite cannot hold.
    """
    from core.mirror.gold import _columns_changed
    from core.ontology.gold_view import GOLD_NAMESPACE

    for table_name, silo in _link_tables(schema).items():
        try:
            silver_table = sync._catalog.load_table(f"{silo}.{table_name}")
            snapshot = silver_table.current_snapshot()
            silver = silver_table.scan().to_arrow()
        except Exception as exc:  # noqa: BLE001 - reported, like any other build
            print(f"FAILED  gold.{table_name}: its silver table could not be read: {exc}",
                  file=sys.stderr)
            continue
        stamp = str(snapshot.snapshot_id) if snapshot is not None else None
        identifier = f"{GOLD_NAMESPACE}.{table_name}"
        with contextlib.suppress(Exception):
            sync._catalog.create_namespace(GOLD_NAMESPACE)
        try:
            table = sync._catalog.load_table(identifier)
        except Exception:  # noqa: BLE001 - not there yet is the first build
            table = None
        if table is not None and _columns_changed(table, silver.schema):
            sync._catalog.drop_table(identifier)
            table = None
        if table is None:
            table = sync._catalog.create_table(identifier, schema=silver.schema)
            table.append(silver)
        elif stamp is not None and table.properties.get(LINK_SOURCE_PROPERTY) == stamp:
            print(f"unchanged gold.{table_name}: its silver has not moved (link table)")
            continue
        else:
            table.overwrite(silver)
        if stamp is not None:
            with sync._catalog.load_table(identifier).transaction() as tx:
                tx.set_properties({LINK_SOURCE_PROPERTY: stamp})
        print(f"published gold.{table_name}: {silver.num_rows} rows (link table)")


def _targets_before_referrers(schema: dict) -> list:
    """The object types, each after the types it links to (PA001-G8).

    THE LINK AUDIT ASKS THE TARGET'S PUBLICATION whether an id
    exists. Built in declaration order, a type could be audited
    against its target's PREVIOUS publication -- so a new target row
    and a new row referencing it, arriving in the SAME sync, refused
    the referrer for pointing at a row that was published seconds
    later.

    MEASURED: `AOrder` (built first, alphabetically) was refused --
    "1 customer value(s) point at no ZCustomer: 'c2'" -- and
    `ZCustomer` then published c2. Nothing was wrong with the data.
    Rename the type and the refusal moves.

    A CYCLE CANNOT BE ORDERED, and the audit says so: "mutually-linked
    types cannot both be ordered first". Those keep their declaration
    order -- and _build_gold lets a type in a cycle link to the ids its
    partner is about to publish this run (R18), saying so if the
    partner is then refused.

    DECLARATION ORDER IS THE TIE-BREAK, so a schema with no links
    builds in exactly the order it did before and nothing moves
    unnecessarily.
    """
    order = list(schema)
    position = {name: index for index, name in enumerate(order)}
    targets_of = _link_targets(schema)

    built: list = []
    done: set = set()
    remaining = list(order)
    while remaining:
        ready = [name for name in remaining if targets_of[name] <= done]
        if not ready:
            # A CYCLE. Take the earliest-declared remaining type and
            # carry on: no ordering satisfies it, and refusing to
            # build would be worse than auditing it against the
            # previous publication, which is what happened before.
            ready = [min(remaining, key=lambda name: position[name])]
        for name in ready:
            built.append(name)
            done.add(name)
            remaining.remove(name)
    return [(name, schema[name]) for name in built]


def _link_targets(schema: dict) -> dict[str, set]:
    """{type: the other types it links to}."""
    return {
        name: {
            (field.get("target") or field.get("object_type"))
            for field in (type_def.get("fields") or {}).values()
            if field.get("type") == "link"
        } & set(schema) - {name}
        for name, type_def in schema.items()
    }


def _cycles(schema: dict) -> dict[str, frozenset]:
    """{type: the other types it shares a link cycle with} -- each
    strongly connected component of two or more types (Tarjan's
    algorithm). Types in no cycle are absent."""
    targets = _link_targets(schema)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set = set()
    found: dict[str, frozenset] = {}
    counter = [0]

    def visit(name: str) -> None:
        index[name] = low[name] = counter[0]
        counter[0] += 1
        stack.append(name)
        on_stack.add(name)
        for target in sorted(targets[name]):
            if target not in index:
                visit(target)
                low[name] = min(low[name], low[target])
            elif target in on_stack:
                low[name] = min(low[name], index[target])
        if low[name] == index[name]:
            component = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == name:
                    break
            if len(component) > 1:
                for member in component:
                    found[member] = frozenset(component) - {member}

    for name in schema:
        if name not in index:
            visit(name)
    return found


def _ids_about_to_publish(sync, type_def: dict) -> "set | None":
    """The ids a type's silver holds -- what its gold will hold if its
    build passes. None for a type whose gold ids are not its silver ids:
    identity resolution merges rows, so they are decided by the build."""
    if type_def.get("identity") is not None:
        return None
    storage = type_def.get("storage") or {}
    try:
        table = sync._catalog.load_table(f"{storage.get('silo')}.{storage.get('table')}")
        column = storage.get("id_column")
        return {str(value) for value in
                table.scan(selected_fields=(column,)).to_arrow().column(column).to_pylist()
                if value is not None}
    except Exception:  # noqa: BLE001 - unknown is an answer: fall back to the publication
        return None


def _links_into(sync, type_def: dict, target: str, ids: set) -> int:
    """How many of a type's rows link to one of `ids` of `target` --
    read from its silver, the rows just published."""
    if not ids:
        return 0
    storage = type_def.get("storage") or {}
    columns = [field.get("column", name) for name, field in (type_def.get("fields") or {}).items()
               if field.get("type") == "link" and field.get("target") == target
               and not field.get("via_table") and not field.get("storage")]
    if not columns:
        return 0
    try:
        table = sync._catalog.load_table(f"{storage.get('silo')}.{storage.get('table')}")
        rows = table.scan(selected_fields=tuple(columns)).to_arrow().to_pylist()
    except Exception:  # noqa: BLE001 - unreadable: nothing can be said, so nothing is
        return 0
    return sum(1 for row in rows for column in columns
               if row.get(column) is not None and str(row.get(column)) in ids)


def _by_silo(targets) -> list[tuple[str, list]]:
    """Targets grouped by silo, in the order each silo first appears --
    the order the run already used, so nothing else about it moves."""
    grouped: dict[str, list] = {}
    for target in targets:
        grouped.setdefault(target.silo_name, []).append(target)
    return list(grouped.items())


@contextlib.contextmanager
def _consistent_read(adapter):
    """The adapter's consistent read, or table-by-table reads when it has
    none or cannot open one. Never the run's verdict: a silo whose
    snapshot cannot be opened is read as it always was, and its tables
    fail or succeed on their own."""
    if adapter is None:
        yield False
        return
    try:
        scope = adapter.consistent_read()
        consistent = scope.__enter__()
    except Exception as exc:  # noqa: BLE001 - fall back, never fail the run here
        print(f"WARNING could not open one snapshot of this silo ({type(exc).__name__}); "
              f"reading table by table", file=sys.stderr)
        yield False
        return
    try:
        yield consistent
    except BaseException:
        if not scope.__exit__(*sys.exc_info()):
            raise
    else:
        scope.__exit__(None, None, None)


def _outcome_for(result) -> str:
    """Which of SyncAttempts' three outcomes this run was (PA001-A17).

    A NAMED FUNCTION rather than an expression inline, because a
    control showed the inline version was untestable: every test of
    the history called attempts.record() directly, so the DECISION --
    the part that was wrong -- was never exercised.

    The store has supported three outcomes since it was written; this
    recorded 'synced' for both of the first two, so a source nobody
    has touched for a month and one that changed this morning looked
    identical in the history an operator reads.
    """
    if getattr(result, "degraded", None):
        # BEFORE 'unchanged': a run whose bronze failed did not do
        # everything, whatever silver found. The reason goes in the
        # attempt's detail, beside it.
        return "degraded"
    return "unchanged" if getattr(result, "unchanged", False) else "synced"


def deletions_accepted_for(type_def: dict, accepted: set) -> bool:
    """Whether the operator's --accept-deletions covers this TYPE (R66).

    THE FLAG NAMES TABLES; GOLD IS KEYED BY TYPE. The rule: a type's
    deletion guard yields when the operator accepted deletions in every
    table that decides WHICH OBJECTS IT HAS.

    For an ordinary type, and one with additional storage, that is the
    PRIMARY table alone: an additional storage contributes fields to
    rows the primary already has (a join, GOLD-5), so its rows vanishing
    cannot shrink the type. Accepting it alone does not lift the guard.

    For a type resolving identity across sources (GOLD-6) every storage
    contributes objects, so EVERY storage must be accepted. One accepted
    table never licenses publishing a type another unaccepted source
    could also have emptied.
    """
    storages = [type_def.get("storage") or {}]
    if type_def.get("identity"):
        storages += list((type_def.get("additional_storage") or {}).values())
    return all(f"{storage.get('silo')}.{storage.get('table')}" in accepted
               for storage in storages)


def _plain(value):
    """Frozen configuration as plain JSON-able data: the loader hands
    mappingproxies and tuples, which json.dumps refuses."""
    from collections.abc import Mapping

    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_plain(item) for item in value]
        return sorted(items, key=repr) if isinstance(value, (set, frozenset)) else items
    return value


def _gold_code_version() -> str:
    """A digest of the code a gold build runs (PA001-G11): every module
    under core/mirror and core/ontology. Any change to them rebuilds
    gold, which is more often than needed and never less -- new code is
    never mistaken for the code a publication was built by."""
    import hashlib
    from pathlib import Path

    digest = hashlib.sha256()
    root = Path(__file__).resolve().parents[1] / "core"
    for path in sorted([*(root / "mirror").rglob("*.py"), *(root / "ontology").rglob("*.py")]):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _gold_inputs(sync, type_def: dict, needed: set, approved, known: dict) -> "str | None":
    """Everything one type's gold is derived from, as one digest (PA001-G11).

    THE SAME INPUTS GIVE THE SAME GOLD: the silver snapshots it reads,
    what the ontology declares for the type, the merges a person
    approved, the published ids its links are audited against, and the
    code. When none of those moved since the last publication there is
    nothing to build. Dagster's asset versioning marks an asset
    "Unsynced" on the same three causes: its code version changed, its
    dependencies changed, or "the data version of a parent asset has
    changed due to a new materialization" (dagster.io/docs, asset
    versioning and caching).

    NONE ON ANY DOUBT, which always builds: a table with no snapshot, or
    anything that cannot be read. A spurious build costs one
    publication; a spurious skip serves stale gold.
    """
    import hashlib

    try:
        snapshots = {}
        for name in sorted(needed):
            snapshot = sync._catalog.load_table(name).current_snapshot()
            if snapshot is None:
                return None
            snapshots[name] = snapshot.snapshot_id
        targets = sorted({field.get("target") for field in (type_def.get("fields") or {}).values()
                          if field.get("type") == "link" and field.get("target")})
        links = {
            target: hashlib.sha256("\n".join(sorted(map(str, known[target]))).encode()).hexdigest()
            for target in targets if target in known
        }
        described = {
            "silver": snapshots,
            "type": _plain(type_def),
            "approved": sorted(_plain(list(approved or ()))),
            "links": links,
            "code": _gold_code_version(),
        }
        return hashlib.sha256(json.dumps(described, sort_keys=True, default=str).encode()).hexdigest()
    except Exception:  # noqa: BLE001 - see the docstring: doubt means build
        return None


def _build_gold(sync, config, data_dir, unsynced: set | None = None,
                 run_id: "str | None" = None, accepted: set | None = None,
                 lineage: "LineageEmitter | None" = None) -> int:
    """One gold table per object type, audited before it is published.
    Returns how many were refused.

    `unsynced` names the "silo.table" entries that FAILED this run. A
    type is skipped when one of its own tables is among them
    (PA001-G9): its silver is stale, so publishing it would claim a
    freshness it does not have.

    A TYPE WHOSE OWN TABLES ALL SYNCED IS BUILT NORMALLY, even while a
    neighbour's did not. Its links are still audited against the other
    types' PUBLISHED ids, which is the same thing that happens on any
    run where a neighbour simply did not change.
    """
    # The sync is often the first thing a new deployment runs, and it
    # is the thing that FILLS the lake -- so it says who can read it.
    import logging as _logging

    from core.identity_decisions import MergeDecisionStore
    from core.mirror.lake_permissions import warn_if_world_readable
    warn_if_world_readable(data_dir / "mirror", _logging.getLogger(__name__))

    _publish_link_tables(sync, config.schema)
    # DECISIONS LIVE BESIDE THE OTHER STORES, under data_dir -- not in
    # the lake, because they are what a PERSON told this deployment
    # rather than something derived from a source.
    decisions = MergeDecisionStore(data_dir / "identity_decisions.db")
    refused = 0
    # LINK CYCLES (R18). Ordering puts a target before its referrer, but
    # in a cycle one side must go first, and it was audited against its
    # partner's PREVIOUS publication: a new customer and a new account
    # that point at each other, arriving in one sync, refused whichever
    # was built first. Nothing was wrong with the data.
    #
    # SO A TYPE IN A CYCLE MAY LINK TO WHAT ITS PARTNER IS ABOUT TO
    # PUBLISH -- the ids in the partner's silver this run. If the
    # partner is then refused, those links point at nothing published,
    # and the run SAYS SO, naming both, below. That is the honest form
    # of "audit after every type is built" without holding every
    # publication until the last one passes.
    cycles = _cycles(config.schema or {})
    upcoming = {name: _ids_about_to_publish(sync, (config.schema or {})[name])
                for name in cycles}
    leaned_on: dict[str, set] = {}
    not_published: set = set()
    for object_type, type_def in _targets_before_referrers(config.schema or {}):
        storage = type_def.get("storage") or {}
        identifier = f"{storage.get('silo')}.{storage.get('table')}"
        try:
            # ARROW, NOT DICTS (GOLD-7): a single-source type never
            # needs the rows as Python objects, and building them costs
            # six times the memory. A type that DOES need them --
            # identity resolution, survivorship -- converts below,
            # where the need is visible.
            needs_rows = bool(type_def.get("additional_storage") or type_def.get("identity"))
            silver_table = sync._catalog.load_table(identifier)
            if needs_rows:
                # Identity resolution and survivorship compare values
                # row by row across sources; those are row-shaped
                # problems and keep the dict path.
                silver = silver_table.scan().to_arrow().to_pylist()
            else:
                # STREAMED (GOLD-7): never held whole, at either end.
                silver = silver_table.scan().to_arrow_batch_reader()
            # EVERY STORAGE THE TYPE SPANS (GOLD-5), because a fused
            # type is a join and a join needs both sides. Read here
            # rather than inside build_gold so that reading silver
            # stays the caller's job, as it already was.
            additional = {}
            for name, block in (type_def.get("additional_storage") or {}).items():
                other = f"{block.get('silo')}.{block.get('table')}"
                additional[name] = (
                    sync._catalog.load_table(other).scan().to_arrow().to_pylist()
                )
        except Exception as exc:  # noqa: BLE001 - reported per type, like a sync
            print(f"FAILED  gold.{object_type}: its silver table could not be read: {exc}",
                  file=sys.stderr)
            refused += 1
            not_published.add(object_type)
            continue
        needed = {f"{(type_def.get('storage') or {}).get('silo')}."
                   f"{(type_def.get('storage') or {}).get('table')}"}
        needed.update(
            f"{block.get('silo')}.{block.get('table')}"
            for block in (type_def.get("additional_storage") or {}).values()
        )
        stale = sorted(needed & (unsynced or set()))
        if stale:
            # SAID OUT LOUD, which is the whole of PA001-G9: this used
            # to be silent, and a silent skip on the ONLY read path
            # means the deployment serves yesterday's answer with
            # nothing in the output to suggest it.
            #
            # NOT counted as a gold failure: the silver failure that
            # caused it was already counted and named.
            print(f"skipped gold.{object_type}: "
                  f"{', '.join(stale)} did not sync, so its silver is stale")
            not_published.add(object_type)
            continue
        # LINEAGE (R15): what this type is built from, and into.
        gold_inputs = [lake_dataset(lineage.namespace, "silver", table)
                       for table in sorted(needed)] if lineage else []
        gold_output = [lake_dataset(lineage.namespace, "gold", object_type,
                                    gold_fields(object_type, config.schema))] if lineage else []
        if lineage:
            lineage.emit(START, f"gold.{object_type}", gold_inputs, gold_output)
        known = {
            target: ids
            for target, ids in (
                (name, published_ids(sync._catalog, name, other.get("id_field", "")))
                for name, other in (config.schema or {}).items()
            )
            if ids is not None
        }
        for partner in cycles.get(object_type, ()):
            coming = upcoming.get(partner)
            # NOT ON A PARTNER ALREADY KNOWN NOT TO PUBLISH (found in
            # review): built after its partner was refused or skipped, a
            # type would otherwise still link to ids that will not exist.
            if coming is not None and partner not in not_published:
                known[partner] = set(known.get(partner) or ()) | coming
                leaned_on.setdefault(partner, set()).add(object_type)
        approved = decisions.approved_pairs(object_type)
        try:
            result = build_gold(sync._catalog, object_type, type_def, silver, known,
                                 additional_rows=additional,
                                 approved_pairs=approved,
                                 retain_publications=config.retain_publications,
                                 run_id=run_id,
                                 accept_deletions=deletions_accepted_for(
                                     type_def, accepted or set()),
                                 inputs=_gold_inputs(sync, type_def, needed, approved, known))
        except Exception as exc:  # noqa: BLE001 - per type, like a sync
            # PER TYPE, LIKE EVERY OTHER FAILURE IN THIS LOOP
            # (PA001-G5). Reading silver was already guarded a few
            # lines above; BUILDING was not, so any exception out of
            # build_gold -- for ANY type -- ended the whole run in a
            # traceback.
            #
            # WHAT THAT COST, measured by injecting one failure: every
            # LATER type was never built, and run_sync raised instead
            # of returning, so _notify_mirror_health() and
            # _evaluate_user_triggers() never ran either. The
            # mirror-health alert is skipped precisely when something
            # has gone wrong, which is the one moment it exists for.
            #
            # ONE BAD TYPE IS NOT EVERY TYPE. The others have their own
            # silver and their own audit; refusing them because a
            # neighbour failed discards work that was fine.
            print(f"FAILED  gold.{object_type}: {exc}", file=sys.stderr)
            if lineage:
                lineage.emit(FAIL, f"gold.{object_type}", gold_inputs, gold_output,
                             error=str(exc))
            refused += 1
            not_published.add(object_type)
            continue
        # THE MATCHER NEEDS ROWS, and only runs when a type declares
        # inference -- so the table is materialised here rather than
        # for every type.
        proposed = _propose_merges(
            decisions, config, object_type, type_def,
            {None: silver if needs_rows else silver_table.scan().to_arrow().to_pylist(),
             **additional})
        if proposed:
            print(f"proposed {proposed} merge(s) for {object_type}, awaiting a decision")
        if result.skipped:
            print(f"skipped gold.{object_type}: {result.skipped}")
        elif result.unchanged:
            print(f"unchanged gold.{object_type}: built from the same inputs as its "
                  f"current publication, nothing written")
        elif result.published:
            print(f"published gold.{object_type}: {result.rows} rows")
        else:
            refused += 1
            not_published.add(object_type)
            print(f"REFUSED gold.{object_type}: " + "; ".join(result.problems), file=sys.stderr)
        if lineage:
            # A REFUSED PUBLICATION IS A FAILED RUN of this job: gold
            # was left as it was, which is what FAIL says.
            failed = not result.ok
            lineage.emit(FAIL if failed else COMPLETE, f"gold.{object_type}",
                         gold_inputs, gold_output,
                         error="; ".join(result.problems) if failed else None)
    for partner in sorted(not_published & set(leaned_on)):
        # THE CYCLE'S OTHER HALF DID NOT PUBLISH. A type built earlier was
        # let link to its new rows, which are not in gold after all --
        # named only when a row REALLY points at one (found in review:
        # this once warned about links nobody had made).
        unpublished = (upcoming.get(partner) or set()) - set(
            published_ids(sync._catalog, partner,
                          (config.schema or {})[partner].get("id_field", "")) or ())
        for referrer in sorted(leaned_on[partner]):
            dangling = _links_into(sync, (config.schema or {})[referrer], partner, unpublished)
            if dangling:
                print(f"WARNING gold.{partner} was not published this run, but "
                      f"gold.{referrer} now has {dangling} link(s) to its new ids; they point "
                      f"at nothing until {partner} publishes.", file=sys.stderr)
    return refused


def run_sync(runtime_paths=None, accept_deletions: set | None = None,
              rebuild: set | None = None, full: bool = False) -> int:
    """Syncs every ontology-referenced table. Returns the number of
    tables that FAILED -- 0 meaning a fully successful run, so a
    caller (and __main__ below) can use it directly as an exit code.

    `accept_deletions` names tables ("silo.table") allowed to sync
    even though more than half their rows are gone. Without it such a
    table is REFUSED and the mirror is left as it was, because a
    partially failed read looks exactly like a mass deletion
    (PA001-F4). Per-run and per-table, deliberately: the question "did
    half this table really just go?" has a different answer every time
    it is asked, so it is not a config key.
    """
    # ONE ID FOR THE WHOLE RUN (PR001-R9). Short and readable rather
    # than a full UUID: it is printed, typed into a grep and read
    # aloud. One in four billion against a few runs a day.
    run_id = uuid.uuid4().hex[:8]
    print(f"run {run_id}")

    accepted = set(accept_deletions or ())
    # `rebuild` names tables ("silo.table") whose SILVER may be dropped
    # and rebuilt because a declared type changed and Iceberg cannot
    # apply that in place (PA001-A10). Bronze is untouched, so no raw
    # value is lost; silver's snapshot history for that table is.
    rebuilding = set(rebuild or ())
    # The sync has its own invariant asserts -- that the committed
    # snapshot holds exactly what was written -- so it needs the same
    # guarantee the server does.
    require_assertions_enabled()
    # THE WRITE LOG PASSES ID LISTS AS JSON, so a SQLite without
    # json_each cannot serve one. Checked here rather than discovered
    # at the first write-log read, where the error would name neither
    # the requirement nor what to do about it.
    require_json_each()

    if runtime_paths is None:
        runtime_paths = resolve_runtime_paths()

    with single_writer(runtime_paths.data_dir / "sync.lock") as acquired:
        if not acquired:
            # Exits rather than waiting: the run this collided with is
            # already copying the same data, so queueing would only
            # duplicate work. Exit code 0 -- a skipped run is a normal
            # outcome, not something a scheduler should alert on.
            print(
                "another sync is already running -- exiting without doing anything",
                file=sys.stderr,
            )
            return 0

        # The read adapters specifically -- load_deployment_bundle()'s
        # own third return value is the WRITE set, deliberately ignored
        # here. A sync only ever reads from the source.
        # NOT SERVING (GOLD-8): this process is the one that PUBLISHES
    # gold, so it must be able to start when gold does not exist yet.
    # The refusal belongs to serving reads, not to loading a bundle.
        config, mediator, _write_adapters = load_deployment_bundle(
            runtime_paths.config_dir, runtime_paths.data_dir, serving=False,
        )
        targets = resolve_sync_targets({"object_types": config.schema})
        # THE WRITE LOG IS PASSED, and without it the drift policy
        # refuses every vanished column rather than absorbing one it
        # could not check. The mediator already holds the reader, so
        # this costs nothing and is the difference between "nothing
        # depends on this column" and "I did not look".
        sync = IcebergMirrorSync(
            # LIVE ADAPTERS, NEVER THE MEDIATOR'S. With
            # read_from_mirror on -- the default now -- the mediator's
            # adapters are MirrorReadAdapters, so a sync built from
            # them would read the mirror to build the mirror and never
            # touch the source at all.
            #
            # Found on a real deployment within an hour of the default
            # flipping: dropping silver and re-syncing reported a
            # source column "gone", because the thing being read was
            # the empty silver table.
            #
            # AND FROM THE SAME PATHS. Called without them, the adapters
            # resolved the DEFAULT data directory while the mirror went to
            # runtime_paths.data_dir: read one deployment, write another.
            runtime_paths.data_dir / "mirror", build_live_read_adapters(runtime_paths),
            write_log=mediator.write_log,
            run_id=run_id,
            # WHERE THE WAREHOUSE LIVES, from config.yaml's mirror.storage.
            # Empty means local, which is what every deployment does today.
            #
            # Wired HERE and not only in the class, because a capability the
            # class supports and no caller passes is one a deployment cannot
            # use. That gap existed for a commit: the storage parameter was
            # built and tested end to end against a real S3 endpoint while
            # nothing passed it.
            storage=dict(config.mirror_storage),
            # THE ROW OR THE TABLE, from the deployment rather than a
            # default buried in the sync. Absent keeps refusing.
            on_type_mismatch=config.on_type_mismatch,
            ingest_undeclared_columns=config.ingest_undeclared_columns,
        )

        # ERASURES (R13): the register decides what every read drops.
        erasures = ErasureRegister(runtime_paths.data_dir / "erasures.db")
        sync.suppression = suppression_for(config.schema, erasures)
        # HOW EACH SILO WRITES NUMBERS AND DATES (DEP-1).
        sync.locales = dict(config.source_locales)
        sync.excel_date_silos = config.excel_date_silos
        # CHANGED ROWS ONLY where data_silos.yaml declares a cursor (R2),
        # unless this run was asked to read everything (`--full`).
        sync.incremental = dict(config.incremental)
        sync.force_full_read = full

        # LINEAGE (R15): to lineage.jsonl always, and to a service when
        # config.yaml names one. Never the sync's verdict.
        lineage = LineageEmitter(
            runtime_paths.log_dir, run_id,
            namespace=config.lineage.get("namespace") or DEFAULT_NAMESPACE,
            url=config.lineage.get("url"), api_key_env=config.lineage.get("api_key_env"))
        lineage.emit(START, RUN_JOB)

        failures = 0
        # WHICH TABLES DID NOT SYNC, so gold can skip exactly the
        # types that depend on them rather than all of them.
        unsynced: set = set()
        attempts = SyncAttempts(
            runtime_paths.data_dir / "mirror" / "sync_attempts.db")
        # SWEPT AT THE START, not on a timer. A sync is the only
        # thing that writes here, so it is the only place a sweep
        # can happen without inventing a scheduler -- the same
        # argument api/reload.py makes about keeping one out.
        attempts.forget_older_than()
        # THE RULES THAT WARNED, which nothing kept until now. `warn`
        # lets the row through, so unlike a quarantined one it leaves
        # no trace in the lake -- the finding lived in a log line on
        # whatever process ran this, which on an unattended deployment
        # is a file nobody opens.
        warned = ExpectationWarnings(
            runtime_paths.data_dir / "mirror" / "expectation_warnings.db")
        warned.forget_older_than()
        # ONE CONSISTENT READ PER SILO (R4). Every table of one silo is
        # read inside one snapshot where the source can give one without
        # blocking its own writers -- so an order written between reading
        # customers and reading orders cannot arrive with a customer the
        # mirror lacks. adapters/sqlalchemy_adapter.py says which
        # databases can; the rest read table by table, as before, and
        # this says so.
        for silo_name, silo_targets in _by_silo(targets):
            with _consistent_read(sync.adapters.get(silo_name)) as consistent:
                print(f"reading {silo_name} "
                      + ("as one consistent snapshot" if consistent else "table by table"))
                for target in silo_targets:
                    label = f"{target.silo_name}.{target.table_name}"
                    table_job = f"sync.{label}"
                    table_io = ([source_dataset(target.silo_name, target.table_name)],
                                [lake_dataset(lineage.namespace, "bronze", label),
                                 lake_dataset(lineage.namespace, "silver", label)])
                    lineage.emit(START, table_job, *table_io)
                    try:
                        result = sync.sync_table(
                            target.silo_name, target.table_name, target.id_column,
                            target.columns, target.column_types,
                            target.fields_by_column, target.standardisation,
                            target.expectations, target.duplicate_policy,
                            target.object_types, target.link_pair,
                            f"{target.silo_name}.{target.table_name}" in accepted,
                            rebuilding,
                            # THE COLUMN SILVER MUST NOT CANONICALISE -- LLM3-3.
                            # Standardising a MAC value changes who may see the
                            # row: measured, "N/A" becomes None and the object
                            # belongs to no compartment at all.
                            security_column=target.security_column,
                        )
                    except Exception as exc:
                        # Per-table, deliberately -- see this module's docstring.
                        # The exception itself is printed rather than swallowed
                        # into a generic message: this is an operator-facing
                        # tool, and the real cause is what an operator needs.
                        failures += 1
                        unsynced.add(f"{target.silo_name}.{target.table_name}")
                        print(f"FAILED  {label}: {exc}", file=sys.stderr)
                        # RECORDED BEFORE IT IS PRINTED, because stderr is
                        # the thing nobody sees. A refused sync leaves the
                        # previous snapshot in place, so from the mirror's
                        # own timestamps it is indistinguishable from a
                        # source that has not changed -- and the first is an
                        # incident while the second is Tuesday.
                        attempts.record(
                            target.silo_name, target.table_name, "refused",
                            str(exc), run_id=run_id,
                        )
                        lineage.emit(FAIL, table_job, *table_io, error=str(exc))
                        continue
                    lineage.emit(COMPLETE, table_job, *table_io)
                    # 'unchanged' IS ITS OWN OUTCOME (PA001-A17). The store has
                    # supported three since it was written -- 'synced',
                    # 'unchanged', 'refused' -- and this recorded 'synced' for
                    # both of the first two, so a quiet source and a busy one
                    # were indistinguishable in the history an operator reads
                    # to answer "when did this last actually move?".
                    attempts.record(target.silo_name, target.table_name,
                                    _outcome_for(result),
                                    detail=getattr(result, "degraded", None), run_id=run_id)
                    if getattr(result, "degraded", None):
                        print(f"WARNING {target.silo_name}.{target.table_name}: "
                              f"{result.degraded}", file=sys.stderr)
                    # AFTER THE ATTEMPT, because a warning is about rows that
                    # were read and an attempt may be recorded for a table that
                    # never got that far. Writes nothing when no rule warned.
                    warned.record(target.silo_name, target.table_name,
                                  result.warnings, run_id=run_id)
                    print(f"synced  {label}: {result.row_count} rows at {result.synced_at.isoformat()}"
                          + ("" if result.read == "full" else f" -- read {result.read}"))

        print(f"\n{len(targets) - failures}/{len(targets)} tables synced successfully.")

        # GOLD, FROM THE SILVER JUST WRITTEN (GOLD-2), PER TYPE
        # (PA001-G9).
        #
        # THIS USED TO BE `if failures == 0`, with the reasoning that
        # "gold built from a half-synced mirror would publish a partial
        # picture". The reasoning is right and the scope was wrong: a
        # type whose OWN tables all synced is not a partial picture,
        # and one unrelated table failing skipped gold for EVERY type,
        # SILENTLY -- the run printed "1/2 tables synced successfully"
        # and then nothing at all about gold.
        #
        # WHAT THAT COST: gold is the only read path (GOLD-8), so every
        # type kept serving its PREVIOUS publication while fresh silver
        # sat unused, and nothing in the output said so.
        failures += _build_gold(sync, config, runtime_paths.data_dir,
                                 unsynced=unsynced, run_id=run_id, accepted=accepted,
                                 lineage=lineage)

        # ERASURES NOT YET APPLIED TO THE LAKE -- a new request, or a
        # restore that brought an older lake back -- are applied before
        # anything else reads it, and the files removed outright.
        if sync.suppression:
            erasures.mark_source_cleared(sync.erased_still_in_source)
            if sync.erased_still_in_source:
                print(f"ERASURE  {len(sync.erased_still_in_source)} erased key(s) are still "
                      f"returned by a source; suppressed, and still to be erased there")
        if erasures.unpurged():
            removed = apply_erasures(sync._catalog, config.schema, erasures,
                                     runtime_paths.data_dir / "mirror")
            print(f"ERASURE  applied: {sum(removed.values())} row(s) removed from "
                  f"{len(removed)} table(s), older snapshots and their files deleted")

        # CLASSIFICATIONS, CARRIED TO EVERY COPY (R12) -- after gold, so
        # a table created by this run is labelled by this run, and never
        # a failure: labels are metadata, and a published gold must not
        # be reported as failed over them.
        try:
            relabelled = record_classifications(sync._catalog, config.schema)
        except Exception as exc:  # noqa: BLE001 - metadata, never the sync's verdict
            print(f"WARNING classifications not recorded: {exc}", file=sys.stderr)
            relabelled = []
        if relabelled:
            print(f"classifications recorded on {len(relabelled)} table(s): "
                  f"{', '.join(relabelled)}")

        # THE CONDITION IS CHECKED AFTER THE SYNC, which is the only
        # moment the facts are current. A separate scheduler would need
        # its own trigger, its own failure mode and its own reason to
        # exist; a sync already runs on whatever schedule the
        # deployment chose.
        # WHAT THE LAKE SAYS ABOUT ITSELF, published beside the data --
        # AFTER the data, not before (PA001-F6.3).
        #
        # It ran before the sync loop, so its table list described the
        # PREVIOUS run: a table synced for the first time was absent
        # from the manifest that was written moments after it appeared,
        # and stayed absent until the NEXT sync. A lake in object
        # storage already survives its installation being deleted;
        # without an accurate manifest it cannot say what any of the
        # data MEANS to whatever comes next, and a manifest describing
        # a different moment is worse than a late one.
        publish_manifest(sync, config)

        # COLUMN PROFILES OF EACH NEW PUBLICATION, and what moved (R7).
        try:
            drifts = profile_publications(
                sync._catalog, config.schema,
                ProfileStore(runtime_paths.data_dir / "mirror" / "column_profiles.db"))
        except Exception as exc:  # noqa: BLE001 - a profile is never the sync's verdict
            print(f"WARNING columns not profiled: {exc}", file=sys.stderr)
            drifts = []
        for drift in drifts:
            print(f"DRIFT   {drift}")

        _notify_mirror_health(runtime_paths, config, attempts, targets, drifts)
        _evaluate_user_triggers(runtime_paths, config, mediator)

        lineage.emit(COMPLETE if failures == 0 else FAIL, RUN_JOB,
                     error=f"{failures} table(s) or type(s) failed" if failures else None)
        # THE ID AT BOTH ENDS (R9), so a log holding several runs can be
        # cut at the right line, and the last line says how it went.
        print(f"run {run_id} finished: "
              + ("ok" if failures == 0 else f"{failures} table(s) or type(s) failed"))
        return failures


if __name__ == "__main__":
    _parser = argparse.ArgumentParser(description=__doc__)
    _parser.add_argument(
        "--rebuild", action="append", default=[], metavar="SILO.TABLE",
        help="drop and rebuild this table's SILVER because a declared type "
             "changed. Iceberg cannot change a column's type in place. "
             "Bronze is untouched, so every raw value survives; what is "
             "discarded is silver's snapshot history for this table. "
             "Repeatable.",
    )
    _parser.add_argument(
        "--accept-deletions", action="append", default=[], metavar="SILO.TABLE",
        help="let this table sync even though more than half its rows are gone. "
             "Without it the sync refuses and leaves the mirror as it was, "
             "because a partially failed read looks exactly like a mass "
             "deletion. Repeatable.",
    )
    _parser.add_argument(
        "--full", action="store_true",
        help="read every table in full this run, including tables data_silos.yaml "
             "declares `incremental:`. A full read is the only kind that notices "
             "rows deleted at the source.",
    )
    _args = _parser.parse_args()
    try:
        sys.exit(run_sync(accept_deletions=set(_args.accept_deletions),
                           rebuild=set(_args.rebuild), full=_args.full))
    except MirrorCatalogStranded as stranded:
        # A REFUSAL, NOT A CRASH. The message already names the table,
        # what is wrong and the command that repairs it; a traceback
        # above it just buries that under pyarrow frames the operator
        # can do nothing with.
        print(f"\n{stranded}", file=sys.stderr)
        sys.exit(1)
