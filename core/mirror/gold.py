"""Gold: one table per OBJECT TYPE, audited before anyone can read it
(GOLD-2, MEDALLION_PIPELINE.md's G1 and G4).

WHAT CHANGES FROM SILVER. Silver is one table per SOURCE TABLE, at the
source's grain, with the source's column names. Gold is one table per
object type, keyed by the object's id, with the ONTOLOGY'S property
names -- the shape the ontology actually asks for. For a type with one
source that is a conform and nothing more, which is why the ontology
can move to gold before any identity resolution exists.

WRITE, AUDIT, PUBLISH. New rows go to a branch; the audit runs there;
only if it passes does one commit move `main` and tag the result. A
reader on main sees the previous publication until that instant, and
then sees all of the new one -- Iceberg readers are pinned to the
snapshot they loaded, so nothing sees half a build. A failed audit
moves nothing and says what failed.

WHAT THE AUDIT CHECKS is the contract an ontology needs from the table
behind an object type:

  the key         unique and non-null. Foundry fails an indexing run
                  over a duplicate primary key, because the ontology
                  cannot say which row the object is. Silver already
                  holds duplicates back; this is the promise, restated
                  where it is relied on.
  required        a property declared required is present.
  link targets    every forward link points at an object that exists,
                  when that target's gold table exists to check
                  against.
  row count       a publication that loses more than half its rows
                  against the last one is refused -- the same bound,
                  and the same reasoning, as the changelog's
                  MAX_DELETED_FRACTION: a source that emptied is
                  usually a broken export, not a business event.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pyarrow as pa
from pyiceberg.exceptions import NoSuchNamespaceError, NoSuchTableError

from core.mirror.changelog import MAX_DELETED_FRACTION
from core.mirror.fusion import FUSED_FROM_COLUMN, fuse
from core.mirror.identity import resolve, rule_for
from core.mirror.lineage import LINEAGE_COLUMNS
from core.mirror.survivorship import fuse_entities
from core.ontology.field_types import arrow_type_for
from core.ontology.gold_view import GOLD_NAMESPACE
from core.ontology.link_types import is_reverse_link

logger = logging.getLogger(__name__)

AUDIT_BRANCH = "audit"
PUBLISHED_TAG = "published"


@dataclass
class GoldResult:
    """What one object type's build did."""

    object_type: str
    rows: int = 0
    published: bool = False
    problems: list[str] = field(default_factory=list)
    skipped: str | None = None
    # Identity resolution's own counts (GOLD-6), zero for a type that
    # declares no rule: entities formed from more than one source,
    # merges refused by D2, and disagreements recorded rather than
    # discarded.
    merged: int = 0
    refused_merges: int = 0
    conflicts: int = 0
    # How many changes this publication recorded (GOLD-4). Zero on a
    # first publication, which has no previous state to differ from.
    history_rows: int = 0

    @property
    def ok(self) -> bool:
        return self.published or self.skipped is not None


def conform(type_def: dict, silver_rows: list[dict]) -> list[dict]:
    """Silver's rows in the ontology's own shape: property names, the
    object's id, and the lineage silver carried."""
    id_column = type_def["storage"]["id_column"]
    id_field = type_def["id_field"]
    mapping = {id_column: id_field}
    for field_name, field_config in (type_def.get("fields") or {}).items():
        if field_config.get("type") == "link" and is_reverse_link(field_config):
            # Computed from the other table; nothing on this row holds it.
            continue
        mapping[field_config.get("column", field_name)] = field_name
    conformed = []
    for row in silver_rows:
        shaped = {field_name: row.get(column) for column, field_name in mapping.items()}
        shaped.update({column: row.get(column) for column in LINEAGE_COLUMNS if column in row})
        conformed.append(shaped)
    return conformed


def audit(type_def: dict, rows: list[dict], previous_count: int | None,
          known_ids: dict[str, set] | None = None) -> list[str]:
    """Everything wrong with this build, in the order it was checked."""
    problems = []
    id_field = type_def["id_field"]

    ids = [row.get(id_field) for row in rows]
    missing = sum(1 for value in ids if value is None)
    if missing:
        problems.append(f"{missing} row(s) have no {id_field}")
    seen, duplicated = set(), set()
    for value in ids:
        if value in seen:
            duplicated.add(value)
        seen.add(value)
    if duplicated:
        shown = ", ".join(repr(value) for value in sorted(duplicated, key=repr)[:5])
        problems.append(f"{len(duplicated)} duplicate {id_field}(s): {shown}")

    for field_name, field_config in (type_def.get("fields") or {}).items():
        if not field_config.get("required"):
            continue
        absent = sum(1 for row in rows if row.get(field_name) is None)
        if absent:
            problems.append(f"{absent} row(s) are missing required {field_name}")

    for field_name, field_config in (type_def.get("fields") or {}).items():
        if field_config.get("type") != "link" or is_reverse_link(field_config):
            continue
        target = field_config.get("target")
        available = (known_ids or {}).get(target)
        if available is None:
            # The target's gold table does not exist yet -- a first
            # build, or a type not yet conformed. Not a finding: a
            # check that cannot run must not pretend to have passed
            # OR to have failed.
            continue
        dangling = {row.get(field_name) for row in rows
                    if row.get(field_name) is not None and row.get(field_name) not in available}
        if dangling:
            shown = ", ".join(repr(value) for value in sorted(dangling, key=repr)[:5])
            problems.append(
                f"{len(dangling)} {field_name} value(s) point at no {target}: {shown}"
            )

    if previous_count and len(rows) < previous_count * (1 - MAX_DELETED_FRACTION):
        problems.append(
            f"{len(rows)} rows, down from {previous_count}: more than "
            f"{MAX_DELETED_FRACTION:.0%} of the last publication is gone"
        )
    return problems


def _arrow(rows: list[dict], type_def: dict) -> pa.Table:
    """Gold's columns, TYPED as the ontology declares them.

    They were strings until the parity test (GOLD-3) compared a read
    from gold against the same read from silver and found two
    disagreements that only typing explains: a decimal filter matched
    NOTHING, because `amount = 49.99` was being compared against text;
    and a sum raised TypeError, because you cannot add a string to a
    running total.

    Silver already coerced these values (transform.py), so the values
    arrive typed and only the SCHEMA was lying. arrow_type_for raises
    on an unknown declared type rather than falling back to string,
    which is how a typo fails loudly here too.

    LINEAGE COLUMNS STAY TEXT: they are ours, and they are text.
    """
    id_field = type_def["id_field"]
    declared = type_def.get("fields") or {}
    names = [id_field]
    names += [
        field_name for field_name, field_config in declared.items()
        if field_name != id_field
        and not (field_config.get("type") == "link" and is_reverse_link(field_config))
    ]
    names += list(LINEAGE_COLUMNS)
    # Present only on a fused type, naming the storages that
    # contributed to each row (GOLD-5).
    if type_def.get("additional_storage") or type_def.get("identity"):
        names.append(FUSED_FROM_COLUMN)

    def _type_for(name: str) -> pa.DataType:
        if name in LINEAGE_COLUMNS or name == FUSED_FROM_COLUMN:
            return pa.string()
        field_config = declared.get(name) or {}
        # A LINK IS A KEY, and a key is whatever the target's id is --
        # declared on the target, not here. Text is the honest default
        # for one, as it is for a field that declares no data_type.
        if field_config.get("type") == "link":
            return pa.string()
        return arrow_type_for(field_config.get("data_type", "string"))

    schema = pa.schema([(name, _type_for(name)) for name in names])

    def _value(row: dict, name: str):
        value = row.get(name)
        if value is None:
            return None
        # An id and a link are keys, and keys are compared as text
        # everywhere else in this system.
        return str(value) if schema.field(name).type == pa.string() else value

    return pa.Table.from_pylist(
        [{name: _value(row, name) for name in names} for row in rows],
        schema=schema,
    )


def published_ids(catalog, object_type: str, id_field: str) -> set | None:
    """Every id in the PUBLISHED gold table for a type, or None when it
    has none yet -- what a link check compares against."""
    try:
        table = catalog.load_table(f"{GOLD_NAMESPACE}.{object_type}")
    except (NoSuchTableError, NoSuchNamespaceError, FileNotFoundError):
        return None
    if table.current_snapshot() is None:
        return None
    return set(table.scan(selected_fields=(id_field,)).to_arrow()[id_field].to_pylist())


def published_snapshot_ids(catalog, object_types) -> dict[str, int]:
    """{object type: the snapshot its gold table is published at}.

    A generation PINS these, so every read in a request sees one
    publication and a build finishing mid-request cannot move the
    ground under it. A type with no gold table is simply absent, and
    the caller decides what to do about that -- here, keep serving it
    from the source (GOLD-3).
    """
    pinned: dict[str, int] = {}
    for object_type in object_types:
        try:
            table = catalog.load_table(f"{GOLD_NAMESPACE}.{object_type}")
        except (NoSuchTableError, NoSuchNamespaceError, FileNotFoundError):
            continue
        snapshot = table.current_snapshot()
        if snapshot is not None:
            pinned[object_type] = snapshot.snapshot_id
    return pinned


def published_at(catalog, object_types) -> dict[str, str]:
    """{object type: when its gold table was published}, ISO-8601 UTC.

    THE CLOCK A READER EXPERIENCES (DEV_UI.md 16.6). Silver records
    when the SOURCE WAS READ, which is what the write overlay needs;
    gold records when a PUBLICATION WAS MADE, which is what a person
    looking at an object is actually seeing. A source read hourly but
    published daily is a day stale to that person, and no source-side
    timestamp says so.
    """
    published: dict[str, str] = {}
    for object_type in object_types:
        try:
            table = catalog.load_table(f"{GOLD_NAMESPACE}.{object_type}")
        except (NoSuchTableError, NoSuchNamespaceError, FileNotFoundError):
            continue
        snapshot = table.current_snapshot()
        if snapshot is not None:
            published[object_type] = datetime.fromtimestamp(
                snapshot.timestamp_ms / 1000, tz=UTC,
            ).isoformat()
    return published


def build_gold(catalog, object_type: str, type_def: dict, silver_rows: list[dict],
               known_ids: dict[str, set] | None = None,
               additional_rows: "dict[str, list[dict]] | None" = None) -> GoldResult:
    """Conform, audit and -- only if it passes -- publish one type.

    A TABLE THAT ALREADY HAS A PUBLICATION is written on a branch, so
    what readers see does not move until the audit passes. A FIRST
    build has nothing to protect: it writes to main and, if the audit
    fails, the table is dropped, leaving no gold rather than unaudited
    gold.
    """
    result = GoldResult(object_type)
    unresolved: list = []
    identity_rule = rule_for(type_def)
    if identity_rule is not None:
        # IDENTITY RESOLUTION (GOLD-6): the sources do not agree on the
        # object's id, so a declared rule decides who is who, and
        # survivorship decides which version of each property wins.
        # A merge refused by D2 leaves its rows unmerged and is
        # recorded as a conflict rather than silently resolved.
        if additional_rows is None and type_def.get("additional_storage"):
            return GoldResult(
                object_type,
                skipped="resolves identity across sources, and their rows were not supplied",
            )
        resolution = resolve(type_def, {None: silver_rows, **(additional_rows or {})},
                              identity_rule)
        fused = fuse_entities(type_def, resolution)
        rows = fused.rows
        result.conflicts = len(fused.conflicts)
        unresolved = fused.conflicts
        result.merged = resolution.merged_count
        result.refused_merges = len(resolution.refused)
    elif type_def.get("additional_storage"):
        # SEVERAL STORAGES, JOINED (GOLD-5). Each storage declares its
        # own id_column and each field names exactly one storage, so
        # this is a join rather than a survivorship contest -- see
        # core/mirror/fusion.py for why that distinction decides what
        # belongs here and what belongs to GOLD-6.
        if additional_rows is None:
            return GoldResult(
                object_type,
                skipped="spans several storages, and their rows were not supplied",
            )
        rows = fuse(type_def, {None: silver_rows, **additional_rows})
    else:
        rows = conform(type_def, silver_rows)
    result.rows = len(rows)
    arrow_table = _arrow(rows, type_def)
    identifier = f"{GOLD_NAMESPACE}.{object_type}"

    try:
        catalog.create_namespace(GOLD_NAMESPACE)
    except Exception:  # noqa: BLE001 - already there is the normal case
        pass

    try:
        table = catalog.load_table(identifier)
        first_build = table.current_snapshot() is None
    except (NoSuchTableError, NoSuchNamespaceError):
        table = catalog.create_table(identifier, schema=arrow_table.schema)
        first_build = True

    previous_count = None
    previous_rows = None
    if not first_build:
        # READ ONCE, used twice: the audit needs the count and the
        # changelog needs the rows themselves, and reading the
        # publication twice would let them disagree if a build landed
        # between (GOLD-4).
        published_now = table.scan().to_arrow().to_pylist()
        previous_count = len(published_now)
        previous_rows = published_now

    if first_build:
        # APPEND, not overwrite: the table is empty, and an overwrite
        # there warns "Delete operation did not match any records" --
        # noise that would teach a reader to ignore pyiceberg's
        # warnings.
        table.append(arrow_table)
        result.problems = audit(type_def, rows, previous_count, known_ids)
        if result.problems:
            # NO GOLD RATHER THAN UNAUDITED GOLD.
            catalog.drop_table(identifier)
            return result
        table = catalog.load_table(identifier)
        _tag_publication(table)
        result.published = True
        # THE LOSING VALUES ARE KEPT (GOLD-6). "Deleting losing values
        # destroys trust": a person asking why the golden record says
        # Leeds must be able to see that the CRM said Hull and was
        # outranked, or the answer is an assertion.
        _write_conflicts(catalog, object_type, unresolved)
        # A FIRST PUBLICATION HAS NO HISTORY, and writing every row as
        # an INSERT would claim one that did not happen. Called anyway,
        # so the decision lives in one place (gold_history).
        result.history_rows = _record_history(catalog, object_type, type_def,
                                               previous_rows, rows)
        return result

    table.manage_snapshots().create_branch(
        table.current_snapshot().snapshot_id, AUDIT_BRANCH,
    ).commit()
    table = catalog.load_table(identifier)
    table.overwrite(arrow_table, branch=AUDIT_BRANCH)
    table = catalog.load_table(identifier)

    result.problems = audit(type_def, rows, previous_count, known_ids)
    if result.problems:
        # NOTHING MOVES. The branch is removed so the next build starts
        # from what is published, not from a refused attempt.
        table.manage_snapshots().remove_branch(AUDIT_BRANCH).commit()
        return result

    audited = table.snapshot_by_name(AUDIT_BRANCH).snapshot_id
    _publish(table, audited)
    result.published = True
    # THE LOSING VALUES ARE KEPT (GOLD-6). "Deleting losing values
    # destroys trust": a person asking why the golden record says
    # Leeds must be able to see that the CRM said Hull and was
    # outranked, or the answer is an assertion.
    _write_conflicts(catalog, object_type, unresolved)
    # AFTER THE PUBLICATION, never before: history describes what was
    # published, and a changelog entry for a build that was refused
    # would be a record of something that did not happen.
    result.history_rows = _record_history(catalog, object_type, type_def,
                                           previous_rows, rows)
    return result


CONFLICT_NAMESPACE = "gold_conflicts"

CONFLICT_SCHEMA = pa.schema([
    ("entity_id", pa.string()),
    ("kind", pa.string()),
    ("field", pa.string()),
    ("chosen", pa.string()),
    ("chosen_source", pa.string()),
    ("losing", pa.string()),
    ("losing_source", pa.string()),
    ("recorded_at", pa.string()),
])


def _write_conflicts(catalog, object_type: str, conflicts: list) -> None:
    """Every disagreement identity resolution could not make disappear.

    APPENDED, like the changelog and for the same reason: a record that
    can be rewritten is not a record. And it holds BOTH kinds -- a
    property whose sources disagreed, and a merge D2 refused -- because
    an operator asking "what did identity resolution decline to do"
    should find one place rather than two.
    """
    if not conflicts:
        return
    recorded_at = datetime.now(UTC).isoformat()
    rows = [
        {
            "entity_id": conflict.entity_id,
            "kind": conflict.kind,
            "field": conflict.field_name,
            "chosen": None if conflict.chosen is None else str(conflict.chosen),
            "chosen_source": conflict.chosen_source,
            "losing": None if conflict.losing is None else str(conflict.losing),
            "losing_source": conflict.losing_source,
            "recorded_at": recorded_at,
        }
        for conflict in conflicts
    ]
    identifier = f"{CONFLICT_NAMESPACE}.{object_type}"
    try:
        catalog.create_namespace(CONFLICT_NAMESPACE)
    except Exception:  # noqa: BLE001 - already there is the normal case
        pass
    try:
        table = catalog.load_table(identifier)
    except (NoSuchTableError, NoSuchNamespaceError):
        table = catalog.create_table(identifier, schema=CONFLICT_SCHEMA)
    table.append(pa.Table.from_pylist(rows, schema=CONFLICT_SCHEMA))


def _record_history(catalog, object_type: str, type_def: dict,
                     previous_rows: "list[dict] | None", rows: list[dict]) -> int:
    """What changed since the last publication, appended. 0 if nothing.

    NEVER RAISES INTO A PUBLICATION. Gold is published; failing to
    describe the change afterwards must not undo that, any more than
    failing to write a notification turns a successful sync into a
    failed one. The failure is logged and the count is zero.
    """
    from core.mirror.gold_history import record_publication

    table = catalog.load_table(f"{GOLD_NAMESPACE}.{object_type}")
    snapshot = table.current_snapshot()
    published_at = datetime.fromtimestamp(snapshot.timestamp_ms / 1000, tz=UTC).isoformat()
    try:
        return record_publication(
            catalog, object_type, type_def["id_field"], previous_rows, rows,
            published_at, snapshot.snapshot_id,
        )
    except Exception as exc:  # noqa: BLE001 - reported, never raised into the publish
        logger.warning(f"gold.{object_type} published, but its history was not recorded: {exc}")
        return 0


def _publish(table, audited_snapshot: int) -> None:
    """One commit: main moves to the audited snapshot, which is tagged,
    and the branch is removed."""
    number = 1 + sum(1 for ref in table.metadata.refs if ref.startswith(f"{PUBLISHED_TAG}-"))
    table.manage_snapshots().set_current_snapshot(
        snapshot_id=audited_snapshot,
    ).create_tag(audited_snapshot, f"{PUBLISHED_TAG}-{number}").remove_branch(
        AUDIT_BRANCH,
    ).commit()


def _tag_publication(table) -> None:
    number = 1 + sum(1 for ref in table.metadata.refs if ref.startswith(f"{PUBLISHED_TAG}-"))
    snapshot = table.current_snapshot()
    table.manage_snapshots().create_tag(
        snapshot.snapshot_id, f"{PUBLISHED_TAG}-{number}",
    ).commit()
