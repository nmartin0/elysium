"""
run_sync.py  (copies the customer's own external data into Elysium's
local mirror -- one run, then exits)

Phase 2 of the read-only mirror architecture (see ROADMAP.md). A
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
from typing import Any

from core.deployment_loader import (
    build_live_read_adapters,
    load_deployment_bundle,
    resolve_runtime_paths,
)
from core.mirror.gold import build_gold, published_ids
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.manifest import publish_manifest
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


def _notify_mirror_health(runtime_paths, config, attempts, targets) -> None:
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
        told = notify_mirror_health(
            states, recipients, NotificationStore(
                runtime_paths.data_dir / "notifications.db",
            ),
        )
        if told:
            print(f"notified {told} administrator(s) about mirror health")
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


def _publish_link_tables(sync, schema: dict) -> None:
    """Copy each join table into gold, unchanged."""
    from core.ontology.gold_view import GOLD_NAMESPACE

    for table_name, silo in _link_tables(schema).items():
        try:
            silver = sync._catalog.load_table(f"{silo}.{table_name}").scan().to_arrow()
        except Exception as exc:  # noqa: BLE001 - reported, like any other build
            print(f"FAILED  gold.{table_name}: its silver table could not be read: {exc}",
                  file=sys.stderr)
            continue
        identifier = f"{GOLD_NAMESPACE}.{table_name}"
        with contextlib.suppress(Exception):
            sync._catalog.create_namespace(GOLD_NAMESPACE)
        with contextlib.suppress(Exception):
            sync._catalog.drop_table(identifier)
        table = sync._catalog.create_table(identifier, schema=silver.schema)
        table.append(silver)
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
    order, which is no worse than before, and the deeper fix for them
    is PR001-R18 (dependency-aware builds) or auditing after every
    type is built.

    DECLARATION ORDER IS THE TIE-BREAK, so a schema with no links
    builds in exactly the order it did before and nothing moves
    unnecessarily.
    """
    order = list(schema)
    position = {name: index for index, name in enumerate(order)}
    targets_of = {
        name: {
            (field.get("target") or field.get("object_type"))
            for field in (type_def.get("fields") or {}).values()
            if field.get("type") == "link"
        } & set(order) - {name}
        for name, type_def in schema.items()
    }

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
    return "unchanged" if getattr(result, "unchanged", False) else "synced"


def _build_gold(sync, config, data_dir, unsynced: set | None = None) -> int:
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
            continue
        known = {
            target: ids
            for target, ids in (
                (name, published_ids(sync._catalog, name, other.get("id_field", "")))
                for name, other in (config.schema or {}).items()
            )
            if ids is not None
        }
        try:
            result = build_gold(sync._catalog, object_type, type_def, silver, known,
                                 additional_rows=additional,
                                 approved_pairs=decisions.approved_pairs(object_type),
                                 retain_publications=config.retain_publications)
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
            refused += 1
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
        elif result.published:
            print(f"published gold.{object_type}: {result.rows} rows")
        else:
            refused += 1
            print(f"REFUSED gold.{object_type}: " + "; ".join(result.problems), file=sys.stderr)
    return refused


def run_sync(runtime_paths=None, accept_deletions: set | None = None) -> int:
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
    accepted = set(accept_deletions or ())
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
            # WHERE THE WAREHOUSE LIVES, from config.yaml's mirror.storage.
            # Empty means local, which is what every deployment does today.
            #
            # Wired HERE and not only in the class, because a capability the
            # class supports and no caller passes is one a deployment cannot
            # use. That gap existed for a commit: the storage parameter was
            # built and tested end to end against a real S3 endpoint while
            # nothing passed it.
            storage=dict(config.mirror_storage),
        )

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
        for target in targets:
            label = f"{target.silo_name}.{target.table_name}"
            try:
                result = sync.sync_table(
                    target.silo_name, target.table_name, target.id_column,
                    target.columns, target.column_types,
                    target.fields_by_column, target.standardisation,
                    target.expectations, target.duplicate_policy,
                    target.object_types, target.link_pair,
                    f"{target.silo_name}.{target.table_name}" in accepted,
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
                    str(exc),
                )
                continue
            # 'unchanged' IS ITS OWN OUTCOME (PA001-A17). The store has
            # supported three since it was written -- 'synced',
            # 'unchanged', 'refused' -- and this recorded 'synced' for
            # both of the first two, so a quiet source and a busy one
            # were indistinguishable in the history an operator reads
            # to answer "when did this last actually move?".
            attempts.record(target.silo_name, target.table_name,
                            _outcome_for(result))
            print(f"synced  {label}: {result.row_count} rows at {result.synced_at.isoformat()}")

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
                                 unsynced=unsynced)

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

        _notify_mirror_health(runtime_paths, config, attempts, targets)
        _evaluate_user_triggers(runtime_paths, config, mediator)

        return failures


if __name__ == "__main__":
    _parser = argparse.ArgumentParser(description=__doc__)
    _parser.add_argument(
        "--accept-deletions", action="append", default=[], metavar="SILO.TABLE",
        help="let this table sync even though more than half its rows are gone. "
             "Without it the sync refuses and leaves the mirror as it was, "
             "because a partially failed read looks exactly like a mass "
             "deletion. Repeatable.",
    )
    sys.exit(run_sync(accept_deletions=set(_parser.parse_args().accept_deletions)))
