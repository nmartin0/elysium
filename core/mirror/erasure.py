"""Erasure: the right to be forgotten, everywhere the mirror copied them (R13).

GDPR Article 17: the controller "shall have the obligation to erase
personal data without undue delay". Elysium does not own the source
systems -- it reads them -- but the mirror is a copy, and since the
changelog it is a SYSTEM OF RECORD: bronze, silver, the changelog, gold,
gold's history and its conflicts each hold the person, and the
changelog in particular holds what the source has already overwritten.
An erasure that stopped at "no longer served" would leave every one of
them. The owner chose (2026-10-12) the strongest of three shapes:

EVERYWHERE, REWRITTEN. Every table holding one of the person's keys is
rewritten without those rows, every older snapshot and publication tag
that still references them is dropped, and the files are deleted --
nothing in the lake can show them again, time travel included.

SUPPRESSED UNTIL THE SOURCE CATCHES UP. The source may still return
them; Elysium cannot erase it. So every sync drops their rows on the way
in, and the register records when the source stopped returning them --
so "erased here, still in the CRM" is a fact the operator can see and
take to the source's owner, not a silent reappearance.

RE-APPLIED ON RESTORE. A backup taken before the erasure holds them. The
register is backed up with everything else, and restoring marks every
erasure unpurged, so the next sync rewrites the restored lake before
anything is served from it -- the backup practice the ICO describes as
putting the data "beyond use" and erasing it when it is restored.

THE REGISTER HOLDS NO PERSONAL DATA. An erasure is recorded as a salted
hash of "<type>:<id>", never the id: a list of who asked to be forgotten
is itself personal data, and the worst place to keep it is the one
record that must survive. Matching never needs the id back -- every row
is hashed the same way and compared.

A PERSON IS AN OBJECT AND WHAT POINTS AT IT. Erasing a Customer erases
the rows of every type that links to it -- their transactions, their
tickets, their tag memberships -- found through the ontology's own
links, so a type added later is covered by declaring its link.
"""

import hashlib
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from core.sqlite_connection import connection_with_schema

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS erasure_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS erasures (
    key_hash TEXT NOT NULL,
    object_type TEXT NOT NULL,
    erasure_id TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    requested_at REAL NOT NULL,
    -- WHEN THE MIRROR LAST HELD NONE OF IT. Cleared by a restore, so
    -- the next sync rewrites the restored lake.
    purged_at REAL,
    -- WHEN THE SOURCE STOPPED RETURNING IT. Until then every sync
    -- suppresses it, and says so.
    source_cleared_at REAL,
    PRIMARY KEY (key_hash, object_type)
)
"""


@dataclass(frozen=True)
class Erasure:
    erasure_id: str
    object_type: str
    requested_by: str
    reason: str
    requested_at: float
    purged_at: "float | None"
    source_cleared_at: "float | None"


class ErasureRegister:
    """Who has been forgotten, as hashes. Backed up; never pruned."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def _salt(self, conn) -> str:
        # IN THE REGISTER ITSELF, so a restore brings it back with the
        # hashes it made. A salt kept anywhere else could be lost
        # separately, and every recorded erasure would stop matching.
        row = conn.execute("SELECT value FROM erasure_meta WHERE key = 'salt'").fetchone()
        if row is not None:
            return row["value"]
        salt = secrets.token_hex(16)
        conn.execute("INSERT INTO erasure_meta (key, value) VALUES ('salt', ?)", (salt,))
        conn.commit()
        return salt

    def hasher(self):
        """A function (type, id) -> hash, with this register's salt."""
        with self._connection() as conn:
            salt = self._salt(conn)

        def key_hash(object_type: str, object_id) -> str:
            return hashlib.sha256(f"{salt}|{object_type}:{object_id}".encode()).hexdigest()

        return key_hash

    def record(self, keys: list[tuple[str, str]], requested_by: str, reason: str) -> str:
        """Records one erasure covering these (type, id) keys."""
        erasure_id = str(uuid.uuid4())
        key_hash = self.hasher()
        with self._connection() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO erasures (key_hash, object_type, erasure_id, "
                "requested_by, reason, requested_at) VALUES (?, ?, ?, ?, ?, ?)",
                [(key_hash(object_type, object_id), object_type, erasure_id,
                  requested_by, reason, time.time()) for object_type, object_id in keys])
            conn.commit()
        return erasure_id

    def hashes_by_type(self) -> dict[str, set[str]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT key_hash, object_type FROM erasures").fetchall()
        found: dict[str, set[str]] = {}
        for row in rows:
            found.setdefault(row["object_type"], set()).add(row["key_hash"])
        return found

    def unpurged(self) -> bool:
        with self._connection() as conn:
            return conn.execute(
                "SELECT 1 FROM erasures WHERE purged_at IS NULL LIMIT 1").fetchone() is not None

    def mark_purged(self) -> None:
        with self._connection() as conn:
            conn.execute("UPDATE erasures SET purged_at = ? WHERE purged_at IS NULL",
                         (time.time(),))
            conn.commit()

    def mark_restored(self) -> int:
        """A restore brought back a lake older than some erasures: every
        one must be applied again before anything is served."""
        with self._connection() as conn:
            cursor = conn.execute("UPDATE erasures SET purged_at = NULL")
            conn.commit()
            return cursor.rowcount

    def mark_source_cleared(self, still_in_source: set[str]) -> None:
        """Records which erased keys the source no longer returns."""
        with self._connection() as conn:
            for row in conn.execute(
                    "SELECT key_hash FROM erasures WHERE source_cleared_at IS NULL").fetchall():
                if row["key_hash"] not in still_in_source:
                    conn.execute("UPDATE erasures SET source_cleared_at = ? WHERE key_hash = ?",
                                 (time.time(), row["key_hash"]))
            conn.commit()

    def erasures(self) -> list[Erasure]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT erasure_id, object_type, requested_by, reason, "
                "MIN(requested_at) AS requested_at, MIN(purged_at) AS purged_at, "
                "MIN(source_cleared_at) AS source_cleared_at FROM erasures "
                "GROUP BY erasure_id, object_type ORDER BY requested_at").fetchall()
        return [Erasure(**dict(row)) for row in rows]


# --- Which columns hold whose keys ------------------------------------

def source_key_columns(schema: dict) -> dict[tuple[str, str], dict[str, set[str]]]:
    """{(silo, table): {column: {object types whose ids it holds}}}.

    FROM THE ONTOLOGY'S OWN DECLARATIONS: every storage's id column, the
    columns of every link (a forward link's own column, a reverse link's
    via_column in the other table, both columns of a join table).
    """
    found: dict[tuple[str, str], dict[str, set[str]]] = {}

    def add(silo, table, column, object_type):
        if silo and table and column:
            found.setdefault((silo, table), {}).setdefault(column, set()).add(object_type)

    for object_type, type_def in schema.items():
        primary = type_def.get("storage") or {}
        add(primary.get("silo"), primary.get("table"), primary.get("id_column"), object_type)
        storages = {None: primary, **(type_def.get("additional_storage") or {})}
        for block in (type_def.get("additional_storage") or {}).values():
            add(block.get("silo"), block.get("table"), block.get("id_column"), object_type)
        for field_name, info in (type_def.get("fields") or {}).items():
            if info.get("type") != "link":
                continue
            if info.get("via_table") and info.get("via_column"):
                add(primary.get("silo"), info["via_table"], info["via_column"], object_type)
                if info.get("via_target_column"):
                    add(primary.get("silo"), info["via_table"], info["via_target_column"],
                        info.get("target"))
            elif info.get("cardinality") == "one":
                storage = storages.get(info.get("storage")) or primary
                add(storage.get("silo"), storage.get("table"),
                    info.get("column", field_name), info.get("target"))
    return found


def table_key_columns(schema: dict, identifier: str) -> dict[str, set[str]]:
    """The key columns of ONE mirror table, whichever layer it is."""
    namespace, _, table = identifier.partition(".")
    for prefix in ("bronze_", "changelog_"):
        if namespace.startswith(prefix):
            return source_key_columns(schema).get((namespace[len(prefix):], table), {})
    if namespace.startswith(("quarantine_", "cleaning_")):
        # Both record findings by OBJECT ID, not by the source's columns:
        # the cleaning record (R33) holds a cell's before and after, so an
        # erased person's text is there too, and goes with them.
        silo = namespace.partition("_")[2]
        owners = source_key_columns(schema).get((silo, table), {})
        types = {object_type for object_type, type_def in schema.items()
                 if (type_def.get("storage") or {}).get("table") == table}
        return {"object_id": types} if types and owners else {}
    if namespace == "gold" and table in schema:
        type_def = schema[table]
        columns = {type_def["id_field"]: {table}}
        for field_name, info in (type_def.get("fields") or {}).items():
            if info.get("type") == "link" and info.get("cardinality") == "one":
                columns.setdefault(field_name, set()).add(info.get("target"))
        return columns
    if namespace == "gold":
        # A JOIN TABLE'S GOLD COPY (gold.customer_tags), which is no object
        # type. It carries the source table's own columns, so it has the
        # source table's keys. Matched by table name in any silo -- gold
        # does not say which -- and a column too many is harmless, a value
        # being erased only when its hash is in the register.
        found: dict[str, set[str]] = {}
        for (_silo, source_table), columns in source_key_columns(schema).items():
            if source_table == table:
                for column, types in columns.items():
                    found.setdefault(column, set()).update(types)
        return found
    if namespace == "gold_history" and table in schema:
        return {schema[table]["id_field"]: {table}}
    if namespace == "gold_conflicts" and table in schema:
        return {"entity_id": {table}}
    return source_key_columns(schema).get((namespace, table), {})


# --- What each table says about its own keys --------------------------

#: THE KEY COLUMNS OF A TABLE, AND THE OBJECT TYPES THEY IDENTIFY, kept on
#: the table itself (Iceberg table property, like iceberg_sync's
#: SOURCE_COLUMNS_PROPERTY) and written by every sync. The current schema
#: only knows the types that still exist, and removing a type deliberately
#: keeps its tables (core/ontology/removal.py): without this, the day a type
#: was removed an erasure would stop reaching its tables, for good, with
#: nothing saying so. A property travels with the table -- a backup, a
#: restore, a copy of the warehouse -- so there is no second list to go stale.
KEY_COLUMNS_PROPERTY = "elysium.erasure_keys"


def _encode(columns: dict[str, set[str]]) -> str:
    return json.dumps({column: sorted(types) for column, types in sorted(columns.items())
                       if types}, sort_keys=True)


def recorded_key_columns(table) -> dict[str, set[str]]:
    """What a table says its key columns are. Empty when it says nothing --
    a table written before this property existed, or one that could not
    be decoded (never guessed at)."""
    raw = table.properties.get(KEY_COLUMNS_PROPERTY)
    if not raw:
        return {}
    try:
        recorded = json.loads(raw)
        return {str(column): {str(name) for name in types}
                for column, types in recorded.items()}
    except (ValueError, AttributeError, TypeError):
        return {}


def known_key_columns(schema: dict, identifier: str, table) -> dict[str, set[str]]:
    """The key columns of one table: the current schema's answer, plus
    whatever the table recorded.

    THE UNION, NOT EITHER ALONE. A type that was removed leaves its tables
    to the property. A source table that another type still reads is
    known to the schema only by the columns THAT type maps, so the removed
    type's own key columns there would be missed if the schema were taken
    at its word. Extra columns are harmless: a value is erased only when
    its hash is in the register."""
    merged = {column: set(types) for column, types in table_key_columns(schema, identifier).items()}
    for column, types in recorded_key_columns(table).items():
        merged.setdefault(column, set()).update(types)
    return merged


def record_key_columns(catalog, schema: dict) -> list[str]:
    """Writes each table's key columns where they differ; returns the
    tables changed. Called by every sync, after the layers are written.

    NEVER NARROWS. What the table already recorded stays in the union, so
    a type removed from the ontology cannot take its tables' keys with
    it. And nothing is written for a table the schema does not know and
    that recorded nothing: an empty answer here would read, later, as
    "holds no keys", which is precisely what is not known.

    PER TABLE, NEVER FATAL, like record_classifications: a table that
    cannot take a property is named in the log, and erasure will then
    report it as unreachable rather than skip it.
    """
    changed = []
    for namespace in catalog.list_namespaces():
        for parts in catalog.list_tables(namespace):
            identifier = ".".join(parts)
            try:
                table = catalog.load_table(identifier)
                wanted = known_key_columns(schema, identifier, table)
                if not wanted or wanted == recorded_key_columns(table):
                    continue
                with table.transaction() as tx:
                    tx.set_properties({KEY_COLUMNS_PROPERTY: _encode(wanted)})
                changed.append(identifier)
            except Exception as e:  # noqa: BLE001 - see the docstring
                logger.warning("could not record the key columns of %s: %s", identifier, e)
    return changed


def recorded_object_types(catalog) -> set[str]:
    """Every object type some table says it holds the keys of -- so an
    erasure can name a type that has since been removed."""
    found: set[str] = set()
    for namespace in catalog.list_namespaces():
        for parts in catalog.list_tables(namespace):
            try:
                table = catalog.load_table(".".join(parts))
            except Exception:  # noqa: BLE001 - unreadable here is reported where it matters
                continue
            for types in recorded_key_columns(table).values():
                found |= types
    return found


@dataclass(frozen=True)
class ErasureResult:
    """removed: {table: rows removed}. unreachable_tables: lake tables that
    hold data and that erasure could not search, because neither the
    current schema nor the table itself says which columns are keys."""
    removed: dict[str, int]
    unreachable_tables: list[str]


# --- Applying it ------------------------------------------------------

def erased_mask(table: pa.Table, key_columns: dict[str, set[str]], key_hash,
                hashes: dict[str, set[str]]) -> list[bool]:
    """True for every row holding an erased key in any key column."""
    mask = [False] * table.num_rows
    for column, object_types in key_columns.items():
        if column not in table.column_names:
            continue
        wanted = [(object_type, hashes[object_type]) for object_type in object_types
                  if hashes.get(object_type)]
        if not wanted:
            continue
        for index, value in enumerate(table.column(column).to_pylist()):
            if mask[index] or value is None:
                continue
            if any(key_hash(object_type, value) in erased for object_type, erased in wanted):
                mask[index] = True
    return mask


def cascade(catalog, schema: dict, keys: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The keys, plus every object whose forward link points at one.

    READ FROM GOLD, which holds every type's links in the ontology's
    words. Repeated until nothing new is found, so a chain -- a ticket
    on a transaction of the customer -- is followed to its end.
    """
    erased = {(object_type, str(object_id)) for object_type, object_id in keys}
    frontier = set(erased)
    while frontier:
        found = set()
        for object_type, type_def in schema.items():
            links = [field_name for field_name, info in (type_def.get("fields") or {}).items()
                     if info.get("type") == "link" and info.get("cardinality") == "one"
                     and any(target == info.get("target") for target, _ in frontier)]
            if not links:
                continue
            try:
                rows = catalog.load_table(f"gold.{object_type}").scan().to_arrow().to_pylist()
            except Exception:  # noqa: BLE001 - a type never published has nothing to cascade
                continue
            for row in rows:
                for field_name in links:
                    target = type_def["fields"][field_name].get("target")
                    if (target, str(row.get(field_name))) in frontier:
                        found.add((object_type, str(row.get(type_def["id_field"]))))
        frontier = found - erased
        erased |= frontier
    return sorted(erased)


def purge(catalog, schema: dict, register: ErasureRegister) -> ErasureResult:
    """Rewrites every mirror table without the erased rows, and drops
    every older snapshot and tag that still holds them.

    The result names the rows removed per table AND every table it could
    not search (ErasureResult.unreachable_tables): a table written before
    key columns were recorded, whose type has since left the ontology. It
    is reported and logged, never skipped quietly. The caller then deletes the unreferenced
    files (integrity.orphaned_data_files with no margin) under the sync
    lock -- this function leaves the warehouse with the old files
    unreferenced, not yet gone.
    """
    from core.mirror.gold import PUBLISHED_TAG, _tag_publication

    hashes = register.hashes_by_type()
    key_hash = register.hasher()
    removed: dict[str, int] = {}
    unreachable: list[str] = []
    for namespace in catalog.list_namespaces():
        for parts in catalog.list_tables(namespace):
            identifier = ".".join(parts)
            table = catalog.load_table(identifier)
            columns = known_key_columns(schema, identifier, table)
            if not columns:
                if table.current_snapshot() is not None or table.snapshots():
                    unreachable.append(identifier)
                continue
            if table.current_snapshot() is None:
                continue
            current = table.scan().to_arrow()
            mask = erased_mask(current, columns, key_hash, hashes)
            held_elsewhere = _older_snapshots_hold_them(table, columns, key_hash, hashes)
            if not any(mask) and not held_elsewhere:
                continue
            if any(mask):
                kept = current.filter(pa.array([not erased for erased in mask]))
                table.overwrite(kept)
                removed[identifier] = sum(mask)
                if identifier.startswith("gold.") and any(
                        name.startswith(f"{PUBLISHED_TAG}-") for name in table.metadata.refs):
                    # A NEW PUBLICATION, so readers -- who pin the newest
                    # tag -- move to the erased version.
                    _tag_publication(catalog.load_table(identifier))
            _forget_every_other_snapshot(catalog.load_table(identifier))
    if unreachable:
        logger.warning(
            "erasure could not search %d table(s) that hold data: neither the ontology nor the "
            "table says which columns are keys (written before they were recorded, type since "
            "removed): %s", len(unreachable), ", ".join(unreachable))
    register.mark_purged()
    return ErasureResult(removed, unreachable)


def _older_snapshots_hold_them(table, columns, key_hash, hashes) -> bool:
    current = table.current_snapshot()
    for snapshot in table.snapshots():
        if current is not None and snapshot.snapshot_id == current.snapshot_id:
            continue
        rows = table.scan(snapshot_id=snapshot.snapshot_id).to_arrow()
        if any(erased_mask(rows, columns, key_hash, hashes)):
            return True
    return False


def _forget_every_other_snapshot(table) -> None:
    """Every tag but the newest publication, every snapshot but current.

    PAST THE SEVEN-DAY READER MARGIN expire_unreferenced keeps, on
    purpose: that margin protects a request pinned to an older snapshot,
    and an erasure is exactly the case where the older snapshot must not
    be readable. A reader mid-request at that instant may fail; the
    alternative is the erased person remaining readable for a week.
    """
    from datetime import UTC, datetime, timedelta

    from core.mirror.gold import PUBLISHED_TAG

    tags = sorted((name for name in table.metadata.refs if name.startswith(f"{PUBLISHED_TAG}-")),
                  key=lambda name: int(name.rsplit("-", 1)[1]))
    for name in tags[:-1]:
        table.manage_snapshots().remove_tag(name).commit()
    table.maintenance.expire_snapshots().older_than(
        datetime.now(UTC) + timedelta(seconds=1)).commit()


def suppression_for(schema: dict, register: ErasureRegister):
    """What a sync drops on the way in: {(silo, table): (key columns,
    hasher, hashes)} for every source table holding an erased key."""
    hashes = register.hashes_by_type()
    if not hashes:
        return {}
    key_hash = register.hasher()
    return {table: (columns, key_hash, hashes)
            for table, columns in source_key_columns(schema).items()
            if any(hashes.get(object_type) for types in columns.values()
                   for object_type in types)}


def suppress_rows(rows: list[dict], columns: dict[str, set[str]], key_hash,
                  hashes: dict[str, set[str]]) -> tuple[list[dict], set[str]]:
    """(rows to keep, hashes of erased keys the source still returned)."""
    kept, seen = [], set()
    for row in rows:
        hit = None
        for column, object_types in columns.items():
            value = row.get(column)
            if value is None:
                continue
            for object_type in object_types:
                digest = key_hash(object_type, value)
                if digest in hashes.get(object_type, ()):
                    hit = digest
                    break
            if hit:
                break
        if hit:
            seen.add(hit)
        else:
            kept.append(row)
    return kept, seen


def apply_erasures(catalog, schema: dict, register: ErasureRegister,
                   mirror_dir: Path) -> ErasureResult:
    """purge(), then delete the files it left unreferenced -- with NO
    age margin, which the orphan sweep keeps for writes in flight. The
    caller holds the sync lock (run_sync does), so none is in flight."""
    from core.mirror.integrity import orphaned_data_files

    result = purge(catalog, schema, register)
    tables = {".".join(parts) for namespace in catalog.list_namespaces()
              for parts in catalog.list_tables(namespace)}
    for files in orphaned_data_files(catalog, mirror_dir / "warehouse", tables,
                                     older_than_hours=0, now=time.time() + 1).values():
        for path in files:
            path.unlink()
    return result


#: What a person is told when an erasure took something of theirs away:
#: a question waiting on an approval, or a change they proposed. Never
#: whom it concerned -- that is what was erased.
ERASED_NOTICE_KIND = "erasure"
ERASED_QUESTION = ("A question of yours that was waiting on an approval was dropped: "
                   "something it had read has been erased. Ask it again if it is still wanted.")
ERASED_WRITE = ("A change you proposed was withdrawn before anyone decided on it: "
                "it concerned something that has been erased.")


def forget_beyond_the_mirror(data_dir: Path, register: "ErasureRegister",
                             audit_log=None) -> dict[str, int]:
    """Every erased id, forgotten by every store outside the lake (R13).

    THE OWNER'S RULE (14 Oct): everything except the audit log forgets
    -- memories and notes (E-14, decided earlier), frozen sets, the
    write log, the approvals queue, paused questions and answer
    notifications, and the merge proposals that name them. Matched by the register's salted hashes, so this is
    the same call after an erasure and after a restore brings an older
    copy of any of them back.

    A STORE THAT DOES NOT EXIST YET IS SKIPPED, not created: a
    deployment that never froze a set has nothing to forget there.

    WHO LOST SOMETHING IS TOLD, without being told what: the asker of a
    dropped question, the proposer of a withdrawn change. A question
    that simply never came back would read as a fault.

    `audit_log` records each withdrawn write. None leaves them to the
    store's own default, which a restore -- offline, with its own
    report -- accepts.
    """
    from core.artifact_store import ArtifactStore
    from core.frozen_sets import FrozenSetStore
    from core.identity_decisions import MergeDecisionStore
    from core.memory.store import MemoryStore
    from core.mirror.source_record import SourceRecordStore
    from core.notifications import NotificationStore
    from core.ontology.write_log import WriteLogWriter
    from core.paused_queries import PausedQueryStore
    from core.pending_write_persistence import PendingWritePersistence
    from core.pending_write_store import PendingWriteStore

    key_hash, hashes = register.hasher(), register.hashes_by_type()
    counts: dict[str, int] = {}
    if not hashes:
        return counts

    def present(name: str) -> "Path | None":
        path = data_dir / name
        return path if path.exists() else None

    if path := present("memories.db"):
        counts["memories"] = MemoryStore(path).forget_erased(key_hash, hashes)
    if path := present("artifacts.db"):
        counts["notes"] = ArtifactStore(path).forget_erased_notes(key_hash, hashes)
    if path := present("identity_decisions.db"):
        counts["merge_proposals"] = MergeDecisionStore(path).forget_erased(key_hash, hashes)
    if path := present("source_record.db"):
        # R60: an ended disagreement names the entity it was about.
        counts["source_track_record"] = SourceRecordStore(path).forget_erased(key_hash, hashes)
    if path := present("frozen_sets.db"):
        counts["frozen_set_members"] = FrozenSetStore(path).forget_erased(key_hash, hashes)
    if path := present("write_log.db"):
        counts["write_log_entries"] = WriteLogWriter(path).forget_erased(key_hash, hashes)
    withdrawn: list[str] = []
    proposers: list[str] = []
    if path := present("pending_writes.db"):
        store = PendingWriteStore(audit_log=audit_log,
                                  persistence=PendingWritePersistence(path))
        pairs = store.forget_erased(key_hash, hashes)
        withdrawn = [write_id for write_id, _ in pairs]
        proposers = [proposer for _, proposer in pairs]
        counts["pending_writes"] = len(pairs)
    askers: list[str] = []
    if path := present("paused_queries.db"):
        askers = PausedQueryStore(path).forget_erased(key_hash, hashes, set(withdrawn))
        counts["paused_questions"] = len(askers)
    notices = NotificationStore(data_dir / "notifications.db")
    if present("notifications.db"):
        counts["notifications"] = notices.forget_erased(key_hash, hashes)
    for user_id in askers:
        notices.notify(user_id, ERASED_NOTICE_KIND, ERASED_QUESTION)
    for user_id in proposers:
        notices.notify(user_id, ERASED_NOTICE_KIND, ERASED_WRITE)
    return counts
