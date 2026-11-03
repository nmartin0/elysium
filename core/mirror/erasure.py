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

A REMOVED TYPE'S TABLES ARE STILL SEARCHED. Each table records its own key
columns (KEY_COLUMNS_PROPERTY), so removing a type from the ontology does
not take its people out of reach, and a link from an erased person is
followed to the removed type's rows. What cannot be searched is NAMED --
never skipped -- and the erasure is recorded `incomplete` until it can be.
A table that held data before it recorded its columns stays "partly
known" -- no sync can recover what a removed type kept there; only an
operator's --adopt can -- and the erasure is `incomplete` until then. The
limits are in BLOCKING.md, "Erasure and a removed type".

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
from dataclasses import dataclass, field, replace
from pathlib import Path

import pyarrow as pa

from core.sqlite_connection import add_column_if_missing, connection_with_schema

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
    -- THE LAKE TABLES THIS ERASURE COULD NOT FULLY SEARCH, as a JSON list
    -- of names (never a value). NULL: none. Re-evaluated every time the
    -- erasure is applied again, so it clears when they become searchable.
    incomplete_tables TEXT,
    -- 1 FOR THE KEYS ASKED FOR, 0 FOR THOSE FOUND THROUGH THEM; NULL in a
    -- register made before this column, whose every key is treated as asked
    -- for. An incomplete erasure is worked out again from its seeds.
    seed INTEGER,
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
    incomplete_tables: tuple[str, ...] = ()


class ErasureRegister:
    """Who has been forgotten, as hashes. Backed up; never pruned."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA, (
            # A register made before this column existed.
            add_column_if_missing("erasures", "incomplete_tables", "TEXT"),
            add_column_if_missing("erasures", "seed", "INTEGER")))

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

    def record(self, keys: list[tuple[str, str]], requested_by: str, reason: str,
               seeds: "list[tuple[str, str]] | None" = None) -> str:
        """Records one erasure covering these (type, id) keys. `seeds` are
        the ones asked for (default: all of them): the rest were found
        through them, and are found again if the erasure is worked out anew."""
        erasure_id = str(uuid.uuid4())
        key_hash = self.hasher()
        asked = {(object_type, str(object_id)) for object_type, object_id in (
            keys if seeds is None else seeds)}
        with self._connection() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO erasures (key_hash, object_type, erasure_id, "
                "requested_by, reason, requested_at, seed) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(key_hash(object_type, object_id), object_type, erasure_id,
                  requested_by, reason, time.time(),
                  1 if (object_type, str(object_id)) in asked else 0)
                 for object_type, object_id in keys])
            conn.commit()
        return erasure_id

    def seeds_by_erasure(self) -> dict[str, set[tuple[str, str]]]:
        """{erasure id: {(type, hash)}} of the keys asked for."""
        with self._connection() as conn:
            rows = conn.execute("SELECT erasure_id, object_type, key_hash FROM erasures "
                                "WHERE seed IS NULL OR seed = 1").fetchall()
        found: dict[str, set[tuple[str, str]]] = {}
        for row in rows:
            found.setdefault(row["erasure_id"], set()).add((row["object_type"], row["key_hash"]))
        return found

    def types_by_erasure(self) -> dict[str, set[str]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT DISTINCT erasure_id, object_type FROM erasures").fetchall()
        found: dict[str, set[str]] = {}
        for row in rows:
            found.setdefault(row["erasure_id"], set()).add(row["object_type"])
        return found

    def add_derived(self, erasure_id: str, tokens: set[tuple[str, str]]) -> None:
        """Adds keys (already hashed) found through an erasure's seeds, as
        part of that erasure and not yet applied."""
        if not tokens:
            return
        with self._connection() as conn:
            row = conn.execute("SELECT requested_by, reason, requested_at FROM erasures "
                               "WHERE erasure_id = ? LIMIT 1", (erasure_id,)).fetchone()
            if row is None:
                return
            conn.executemany(
                "INSERT OR IGNORE INTO erasures (key_hash, object_type, erasure_id, requested_by, "
                "reason, requested_at, seed) VALUES (?, ?, ?, ?, ?, ?, 0)",
                [(key_hash, object_type, erasure_id, row["requested_by"], row["reason"],
                  row["requested_at"]) for object_type, key_hash in tokens])
            conn.commit()

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

    def mark_purged(self, incomplete: "dict[str, list[str]] | None" = None) -> None:
        """Every erasure now applied to what could be searched. `incomplete`
        is {erasure id: the tables that could affect it and could not be
        fully searched}; it replaces what was recorded, so an erasure not in
        it is complete. The server is not held back for it: what could be
        reached has been."""
        with self._connection() as conn:
            conn.execute("UPDATE erasures SET purged_at = ? WHERE purged_at IS NULL",
                         (time.time(),))
            conn.execute("UPDATE erasures SET incomplete_tables = NULL")
            for erasure_id, names in (incomplete or {}).items():
                conn.execute("UPDATE erasures SET incomplete_tables = ? WHERE erasure_id = ?",
                             (json.dumps(sorted(names)), erasure_id))
            conn.commit()

    def incomplete_erasures(self) -> list[str]:
        with self._connection() as conn:
            rows = conn.execute("SELECT DISTINCT erasure_id FROM erasures "
                                "WHERE incomplete_tables IS NOT NULL").fetchall()
        return sorted(row["erasure_id"] for row in rows)

    def incomplete(self) -> list[str]:
        """The tables some erasure could not fully search, as last found."""
        with self._connection() as conn:
            rows = conn.execute("SELECT DISTINCT incomplete_tables FROM erasures "
                                "WHERE incomplete_tables IS NOT NULL").fetchall()
        return sorted({name for row in rows for name in json.loads(row["incomplete_tables"])})

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
                "MIN(source_cleared_at) AS source_cleared_at, "
                "MAX(incomplete_tables) AS incomplete_tables FROM erasures "
                "GROUP BY erasure_id, object_type ORDER BY requested_at").fetchall()
        return [Erasure(**{**dict(row), "incomplete_tables": tuple(
            json.loads(row["incomplete_tables"]) if row["incomplete_tables"] else ())})
            for row in rows]


# --- Which columns hold whose keys ------------------------------------

#: What joins the parts of a join table's composite id (iceberg_sync's
#: LINK_ID_COLUMN), which is what a quarantine or cleaning record of a join
#: row names as its object.
LINK_SEPARATOR = "\x1f"

#: A key "column" naming one PART of a composite object id: `object_id#1` is
#: the second part. The parts are in the order of the join table's sorted
#: column names (sync_targets' link_pair).
PART_MARK = "#"

Link = tuple[str, str]       # (owner type, target type)


@dataclass(frozen=True)
class SourceColumns:
    """What the ontology says about every source table's columns.

    keys: every column holding some object's id, whoever's it is.
    ids: the columns holding the table's OWN rows' identity (a storage's id
    column). links: the columns of a forward link, each with the type that
    owns the link and the type it points at. joins: the tables that exist
    only to join two types."""
    keys: dict[tuple[str, str], dict[str, set[str]]]
    ids: dict[tuple[str, str], dict[str, set[str]]]
    links: dict[tuple[str, str], dict[str, set[Link]]]
    joins: set[tuple[str, str]]


def _source_columns(schema: dict) -> SourceColumns:
    found = SourceColumns({}, {}, {}, set())

    def add(into, silo, table, column, value):
        if silo and table and column:
            into.setdefault((silo, table), {}).setdefault(column, set()).add(value)

    for object_type, type_def in schema.items():
        primary = type_def.get("storage") or {}
        for block in (primary, *(type_def.get("additional_storage") or {}).values()):
            add(found.keys, block.get("silo"), block.get("table"), block.get("id_column"), object_type)
            add(found.ids, block.get("silo"), block.get("table"), block.get("id_column"), object_type)
        storages = {None: primary, **(type_def.get("additional_storage") or {})}
        for field_name, info in (type_def.get("fields") or {}).items():
            if info.get("type") != "link":
                continue
            if info.get("via_table") and info.get("via_column"):
                add(found.keys, primary.get("silo"), info["via_table"], info["via_column"], object_type)
                if primary.get("silo"):
                    found.joins.add((primary["silo"], info["via_table"]))
                if info.get("via_target_column"):
                    add(found.keys, primary.get("silo"), info["via_table"],
                        info["via_target_column"], info.get("target"))
            elif info.get("cardinality") == "one":
                storage = storages.get(info.get("storage")) or primary
                column = info.get("column", field_name)
                add(found.keys, storage.get("silo"), storage.get("table"), column, info.get("target"))
                add(found.links, storage.get("silo"), storage.get("table"), column,
                    (object_type, info.get("target")))
    return found


def source_key_columns(schema: dict) -> dict[tuple[str, str], dict[str, set[str]]]:
    """{(silo, table): {column: {object types whose ids it holds}}}.

    FROM THE ONTOLOGY'S OWN DECLARATIONS: every storage's id column (the
    primary one and every additional_storage), the columns of every link
    (a forward link's own column, a reverse link's via_column in the other
    table, both columns of a join table).
    """
    return _source_columns(schema).keys


def _storage_types(schema: dict, silo: str, table: str) -> set[str]:
    """Every type that keeps rows in this source table, as its primary
    storage or as an additional_storage."""
    return {object_type for object_type, type_def in schema.items()
            for block in ((type_def.get("storage") or {}),
                          *(type_def.get("additional_storage") or {}).values())
            if block.get("silo") == silo and block.get("table") == table}


def _join_copies(schema: dict, table: str) -> list[tuple[str, str]]:
    """The join tables of this name, one per silo that has one."""
    return sorted(key for key in _source_columns(schema).joins if key[1] == table)


def table_key_columns(schema: dict, identifier: str) -> dict[str, set[str]]:
    """The key columns of ONE mirror table, whichever layer it is."""
    namespace, _, table = identifier.partition(".")
    for prefix in ("bronze_", "changelog_"):
        if namespace.startswith(prefix):
            return source_key_columns(schema).get((namespace[len(prefix):], table), {})
    if namespace.startswith(("quarantine_", "cleaning_")):
        # Both record findings by OBJECT ID, not by the source's columns:
        # the cleaning record (R33) holds a cell's before and after, so an
        # erased person's text is there too, and goes with them. A join
        # table's record names the composite id of its row, whose parts are
        # tested one by one against the type that owns that part. A table
        # several types keep rows in is tested against each of them (see
        # Reach.shared_findings): which id column the sync keyed it by is
        # not known here.
        silo = namespace.partition("_")[2]
        owners = source_key_columns(schema).get((silo, table), {})
        if not owners:
            return {}
        if (silo, table) in _source_columns(schema).joins:
            return {f"object_id{PART_MARK}{index}": set(owners[column])
                    for index, column in enumerate(sorted(owners))}
        types = _storage_types(schema, silo, table)
        return {"object_id": types} if types else {}
    if namespace == "gold" and table in schema:
        type_def = schema[table]
        columns = {type_def["id_field"]: {table}}
        for field_name, info in (type_def.get("fields") or {}).items():
            if info.get("type") == "link" and info.get("cardinality") == "one":
                columns.setdefault(field_name, set()).add(info.get("target"))
        return columns
    if namespace == "gold":
        # A JOIN TABLE'S GOLD COPY (gold.customer_tags), which is no object
        # type. It carries the join table's own columns, so it has that
        # table's keys. Gold does not say which silo it came from: where
        # two silos have a join table of this name the columns of both are
        # taken, and survey() reports the table as only partly known.
        found: dict[str, set[str]] = {}
        columns_of = source_key_columns(schema)
        for key in _join_copies(schema, table):
            for column, types in columns_of.get(key, {}).items():
                found.setdefault(column, set()).update(types)
        return found
    if namespace == "gold_history" and table in schema:
        return {schema[table]["id_field"]: {table}}
    if namespace == "gold_conflicts" and table in schema:
        return {"entity_id": {table}}
    return source_key_columns(schema).get((namespace, table), {})


def table_roles(schema: dict, identifier: str) -> tuple[dict[str, set[str]], dict[str, set[Link]]]:
    """(ids, links) of one table: which columns are the identity of the
    rows it holds, and which point at another object (with the type that
    owns each link). Only the tables that hold a type's own rows have
    either -- the source layers and gold."""
    namespace, _, table = identifier.partition(".")
    if namespace == "gold":
        if table not in schema:
            return {}, {}
        type_def = schema[table]
        return ({type_def["id_field"]: {table}},
                {field_name: {(table, info.get("target"))}
                 for field_name, info in (type_def.get("fields") or {}).items()
                 if info.get("type") == "link" and info.get("cardinality") == "one"})
    if namespace.startswith(("quarantine_", "cleaning_", "gold_")):
        return {}, {}
    for prefix in ("bronze_", "changelog_"):
        if namespace.startswith(prefix):
            namespace = namespace[len(prefix):]
    columns = _source_columns(schema)
    return columns.ids.get((namespace, table), {}), columns.links.get((namespace, table), {})


# --- What each table says about its own keys --------------------------

#: THE KEY COLUMNS OF A TABLE, AND THE OBJECT TYPES THEY IDENTIFY, kept on
#: the table itself (Iceberg table property, like iceberg_sync's
#: SOURCE_COLUMNS_PROPERTY) and written by every sync. The current schema
#: only knows the types that still exist, and removing a type deliberately
#: keeps its tables (core/ontology/removal.py): without this, the day a type
#: was removed an erasure would stop reaching its tables, for good, with
#: nothing saying so. A property travels with the table -- a backup, a
#: restore, a copy of the warehouse -- so there is no second list to go stale.
#:
#: {"v": 2, "keys": ..., "ids": ..., "links": ..., "known": ..., "adopted": ...}.
#: keys and ids are {column: [types]}; links {column: [[owner, target]]}: which
#: column names the type's own rows, and which point at another object, so
#: erasing a customer still finds a removed type's rows about them and,
#: through those, their per-id history.
#:
#: `known` IS STICKY AND NEVER RAISED BY A SYNC. A record can only say what
#: the schema mapped on the day it was written: it cannot recover the
#: columns of a type that was removed before. So a table that already held
#: data when its first record was written is `partial`, and stays so --
#: however many syncs record it again -- until an operator adopts it
#: (adopt_table) or it is dropped. `complete` is written only for a table
#: the very sync that records it created, or one adopted.
KEY_COLUMNS_PROPERTY = "elysium.erasure_keys"
COMPLETE = "complete"
PARTIAL = "partial"


@dataclass(frozen=True)
class Recorded:
    """What a table says about its own columns. `present` is False for a
    table written before the record existed, or recorded in an earlier
    form that lacked what is needed to rely on it (never guessed at)."""
    keys: dict[str, set[str]]
    ids: dict[str, set[str]]
    links: dict[str, set[Link]]
    present: bool
    known: str = PARTIAL
    adopted: bool = False

    @property
    def complete(self) -> bool:
        return self.present and self.known == COMPLETE


def _encode(record: "Recorded") -> str:
    def plain(columns):
        return {column: sorted(types) for column, types in sorted(columns.items()) if types}
    return json.dumps({"v": 2, "keys": plain(record.keys), "ids": plain(record.ids),
                       "links": plain(record.links), "known": record.known,
                       "adopted": record.adopted}, sort_keys=True)


def _decoded(raw) -> dict[str, set[str]]:
    return {str(column): {str(name) for name in types if name is not None}
            for column, types in raw.items()}


def recorded_columns(table) -> Recorded:
    raw = table.properties.get(KEY_COLUMNS_PROPERTY)
    if not raw:
        return Recorded({}, {}, {}, False)
    try:
        recorded = json.loads(raw)
        if recorded.get("v") == 2 and "known" in recorded:
            return Recorded(
                _decoded(recorded.get("keys") or {}), _decoded(recorded.get("ids") or {}),
                {str(column): {(str(owner), str(target)) for owner, target in pairs}
                 for column, pairs in (recorded.get("links") or {}).items()},
                True, COMPLETE if recorded["known"] == COMPLETE else PARTIAL,
                bool(recorded.get("adopted")))
        if isinstance(recorded.get("v"), int):         # an earlier form: no owners, no `known`
            return Recorded(_decoded(recorded.get("keys") or {}), _decoded(recorded.get("ids") or {}),
                            {}, False)
        return Recorded(_decoded(recorded), {}, {}, False)         # the first form: keys only
    except (ValueError, AttributeError, TypeError):
        return Recorded({}, {}, {}, False)


def recorded_key_columns(table) -> dict[str, set[str]]:
    """What a table says its key columns are. Empty when it says nothing."""
    return recorded_columns(table).keys


def _union(*parts: dict) -> dict:
    merged: dict = {}
    for columns in parts:
        for column, values in columns.items():
            merged.setdefault(column, set()).update(values)
    return merged


def schema_columns(schema: dict, identifier: str) -> Recorded:
    """What the current schema alone says about one table."""
    ids, links = table_roles(schema, identifier)
    return Recorded(table_key_columns(schema, identifier), ids, links, False)


def known_columns(schema: dict, identifier: str, table) -> Recorded:
    """One table's columns: the current schema's answer, plus whatever the
    table recorded. present, known and adopted are the record's.

    THE UNION, NOT EITHER ALONE. A type that was removed leaves its tables
    to the record. A source table that another type still reads is known
    to the schema only by the columns THAT type maps, so the removed
    type's own key columns there would be missed if the schema were taken
    at its word. A column re-pointed at another type keeps its old type
    too, which can over-erase (see stale_types): under-erasing a person is
    the worse failure, so the union stays and the over-erasure is shown.
    Extra columns are otherwise harmless: a value is erased only when its
    hash is in the register."""
    now, before = schema_columns(schema, identifier), recorded_columns(table)
    return Recorded(_union(now.keys, before.keys), _union(now.ids, before.ids),
                    _union(now.links, before.links), before.present, before.known, before.adopted)


def stale_types(schema: dict, identifier: str, table) -> list[tuple[str, str]]:
    """[(column, type)] the table recorded for a column that the schema
    now maps to a different type -- the recorded type may be one that still
    exists or one that was removed. Erasing it removes rows of whoever now
    owns the column's values."""
    now = table_key_columns(schema, identifier)
    return sorted((column, name) for column, names in recorded_columns(table).keys.items()
                  if now.get(column)            # a column the ontology no longer maps is not re-pointed
                  for name in names if name not in now[column])


def _created_since(table, since: "float | None") -> bool:
    """Whether the table first held data at or after `since` (a time) --
    that is, the sync recording it created it, and nothing older can be in it."""
    if since is None:
        return False
    stamps = [snapshot.timestamp_ms for snapshot in table.snapshots()]
    return not stamps or min(stamps) / 1000 >= since


def record_key_columns(catalog, schema: dict, created_since: "float | None" = None,
                       failed: "list[str] | None" = None) -> list[str]:
    """Writes each table's columns where they differ; returns the tables
    changed. Called by every sync, after the layers are written, and by a
    removal before the type goes.

    `created_since`: when the recording sync began. A table first written
    after it is `complete`; any other table without a record is `partial`
    (see KEY_COLUMNS_PROPERTY), and a table with a record keeps its `known`.

    NEVER NARROWS. What the table already recorded stays in the union, so
    a type removed from the ontology cannot take its tables' keys with
    it, nor can a type that now maps fewer columns of a shared table. And
    nothing is written for a table the schema does not know and that
    recorded nothing: an empty answer here would read, later, as "holds no
    keys", which is precisely what is not known.

    PER TABLE, NEVER FATAL, like record_classifications: a table that
    cannot take a property is named in the log (and in `failed`), and
    erasure will then report it rather than skip it.
    """
    changed = []
    for namespace in catalog.list_namespaces():
        for parts in catalog.list_tables(namespace):
            identifier = ".".join(parts)
            try:
                table = catalog.load_table(identifier)
                wanted = known_columns(schema, identifier, table)
                if not wanted.keys and not wanted.present:
                    continue
                known = wanted.known if wanted.present else (
                    COMPLETE if _created_since(table, created_since) else PARTIAL)
                record = Recorded(wanted.keys, wanted.ids, wanted.links, True, known, wanted.adopted)
                if record == recorded_columns(table):
                    continue
                with table.transaction() as tx:
                    tx.set_properties({KEY_COLUMNS_PROPERTY: _encode(record)})
                changed.append(identifier)
            except Exception as e:  # noqa: BLE001 - see the docstring
                logger.warning("could not record the key columns of %s: %s", identifier, e)
                if failed is not None:
                    failed.append(identifier)
    return changed


def adopt_table(catalog, schema: dict, identifier: str, keys: dict[str, set[str]],
                ids: "dict[str, set[str]] | None" = None,
                links: "dict[str, set[Link]] | None" = None) -> Recorded:
    """The operator's statement about ONE table: these columns hold these
    types' ids (and none, if `keys` is empty). Unioned with what is known,
    never narrowing; the table becomes `complete`, marked `adopted` so the
    statement is visible in the property. Raises KeyError for a column the
    table does not have, and the catalog's own error for an unknown table.
    This is the only way a legacy table stops being partly known, because
    it is the only thing that knows what a removed type kept in it."""
    table = catalog.load_table(identifier)
    names = set(table.schema().as_arrow().names)
    stated = [*keys, *(ids or {}), *(links or {})]
    for column in stated:
        if column.partition(PART_MARK)[0] not in names:
            raise KeyError(column)
    now = known_columns(schema, identifier, table)
    record = Recorded(_union(now.keys, keys, ids or {}), _union(now.ids, ids or {}),
                      _union(now.links, links or {}), True, COMPLETE, True)
    with table.transaction() as tx:
        tx.set_properties({KEY_COLUMNS_PROPERTY: _encode(record)})
    return record


def recorded_object_types(catalog) -> set[str]:
    """Every object type some table says it holds the keys of -- so an
    erasure can name a type that has since been removed."""
    found: set[str] = set()
    for namespace in catalog.list_namespaces():
        for parts in catalog.list_tables(namespace):
            try:
                table = catalog.load_table(".".join(parts))
            except Exception:  # noqa: BLE001 - unreadable here is reported by survey()
                continue
            for types in recorded_key_columns(table).values():
                found |= types
    return found


@dataclass(frozen=True)
class Reach:
    """What an erasure can and cannot search.

    unreachable: {table: why} -- holds data, and neither the ontology nor
    the table says which columns are keys (or the table cannot be read; the
    kind of failure, not its message). partly_known: tables whose columns
    are not recorded as complete: a removed type that kept columns there
    cannot be known, and no sync changes that; partly_types: the types such
    a table is known to hold. stale: (table, column, type) where a recorded
    type no longer maps the column. shared_findings: quarantine and
    cleaning tables several types keep rows in."""
    unreachable: dict[str, str]
    partly_known: list[str]
    stale: list[tuple[str, str, str]]
    partly_types: dict[str, set[str]] = field(default_factory=dict)
    shared_findings: list[str] = field(default_factory=list)

    @property
    def incomplete(self) -> list[str]:
        return sorted({*self.unreachable, *self.partly_known})


def survey(catalog, schema: dict, erased_types: "set[str] | None" = None) -> Reach:
    """Every lake table that holds data, as erasure would meet it. Changes
    nothing. `erased_types` limits the stale-type report to the types being
    erased; None asks only which tables cannot be searched."""
    unreachable: dict[str, str] = {}
    partly: list[str] = []
    stale: list[tuple[str, str, str]] = []
    partly_types: dict[str, set[str]] = {}
    shared: list[str] = []
    for namespace in catalog.list_namespaces():
        for parts in catalog.list_tables(namespace):
            identifier = ".".join(parts)
            try:
                table = catalog.load_table(identifier)
                holds_data = table.current_snapshot() is not None or bool(table.snapshots())
                known = known_columns(schema, identifier, table)
            except Exception as e:  # noqa: BLE001 - reported by name and kind, never fatal
                unreachable[identifier] = f"cannot be read ({type(e).__name__})"
                continue
            if not holds_data:
                continue
            if not known.keys:
                if not (known.present and known.adopted):          # adopted: holds no person keys
                    unreachable[identifier] = "no key columns known"
                continue
            tail = identifier.partition(".")[2]
            if not known.complete or (identifier.startswith("gold.") and tail not in schema
                                      and len(_join_copies(schema, tail)) > 1):
                partly.append(identifier)
                partly_types[identifier] = {name for names in known.keys.values() for name in names}
            if identifier.startswith(("quarantine_", "cleaning_")):
                silo = identifier.partition(".")[0].partition("_")[2]
                if len(_storage_types(schema, silo, tail)) > 1:
                    shared.append(identifier)
            if erased_types:
                stale += [(identifier, column, name)
                          for column, name in stale_types(schema, identifier, table)
                          if name in erased_types]
    return Reach(unreachable, sorted(partly), sorted(stale), partly_types, sorted(shared))


ADOPT_HINT = ("adopt it with `python -m scripts.erase --adopt TABLE --keys column=Type` "
              "(or `--adopt-none TABLE` if it holds no person's id), or drop it in the lake")


def gap_notice(reach: Reach) -> list[str]:
    """What an erasure or a sync says about what it could not search -- names
    of lake tables and columns, never a value."""
    lines = []
    if reach.unreachable:
        lines.append(
            f"{len(reach.unreachable)} table(s) hold data that could not be searched: "
            + ", ".join(f"{name} ({why})" for name, why in sorted(reach.unreachable.items()))
            + f". Restore the type and sync so erasure can search the columns the ontology maps there "
              f"(the table then stays partly known), or {ADOPT_HINT}.")
    if reach.partly_known:
        lines.append(
            f"{len(reach.partly_known)} table(s) were searched only by the columns that are mapped or "
            f"recorded for them, because they were written before their columns were recorded in full: "
            f"{', '.join(reach.partly_known)}. A removed type's other columns there cannot be known, and "
            f"no sync changes that: {ADOPT_HINT}. ADOPT BEFORE ERASING: an erasure run first removes the "
            f"rows that link a person to what depended on them, which adopting would have followed.")
    for table, column, name in reach.stale:
        lines.append(f"{table}.{column} was recorded as holding {name} ids but the ontology now maps it "
                     f"to something else: rows of whoever owns those values now are removed too.")
    if reach.shared_findings:
        lines.append(f"{', '.join(reach.shared_findings)} record findings for rows several types keep "
                     f"there, and are matched against each of those types' ids: a finding of another "
                     f"type with the same id is removed too.")
    return lines


def relevant_tables(reach: Reach, schema: dict, erased_types: set[str]) -> list[str]:
    """The tables that could still hold what THIS erasure is about: every
    table that cannot be searched at all (nothing says what it holds), and
    every partly known table that holds one of its types -- or any, when it
    is about a type the ontology no longer has, which such a table may keep
    columns for. An unrelated partly known table does not make it incomplete."""
    names = set(reach.unreachable)
    removed_type = bool(erased_types - set(schema))
    for table in reach.partly_known:
        if removed_type or reach.partly_types.get(table, set()) & erased_types:
            names.add(table)
    return sorted(names)


@dataclass(frozen=True)
class ErasureResult:
    """removed: {table: rows removed}; reach: what could not be searched;
    incomplete: {erasure id: the tables that could affect it}."""
    removed: dict[str, int]
    reach: Reach
    incomplete: dict[str, list[str]] = field(default_factory=dict)

    @property
    def unreachable_tables(self) -> dict[str, str]:
        return self.reach.unreachable

    @property
    def partly_known_tables(self) -> list[str]:
        return self.reach.partly_known


# --- Applying it ------------------------------------------------------

def erased_mask(table: pa.Table, key_columns: dict[str, set[str]], key_hash,
                hashes: dict[str, set[str]]) -> list[bool]:
    """True for every row holding an erased key in any key column.

    A key column named `object_id#1` is the second part of a composite id
    (a join row's quarantine or cleaning record), tested against the types
    that own that part only."""
    mask = [False] * table.num_rows
    for column, object_types in key_columns.items():
        name, mark, part = column.partition(PART_MARK)
        if name not in table.column_names:
            continue
        wanted = [(object_type, hashes[object_type]) for object_type in object_types
                  if hashes.get(object_type)]
        if not wanted:
            continue
        for index, value in enumerate(table.column(name).to_pylist()):
            if mask[index] or value is None:
                continue
            if mark:
                pieces = str(value).split(LINK_SEPARATOR)
                value = pieces[int(part)] if int(part) < len(pieces) else None
                if not value:
                    continue
            if any(key_hash(object_type, value) in erased for object_type, erased in wanted):
                mask[index] = True
    return mask


def _removed_types_tables(catalog, schema: dict) -> list:
    """[(rows, owner, id columns, {link column: target types})] for every
    type the ontology no longer has that some table recorded the identity
    and the links of, so the cascade can follow a link from an erased person
    to the removed type's rows. ONLY LINKS THE REMOVED TYPE OWNS: a shared
    table's other types' links are not its. `rows` reads the current rows
    once, when first asked."""
    found = []
    for namespace in catalog.list_namespaces():
        for parts in catalog.list_tables(namespace):
            identifier = ".".join(parts)
            try:
                table = catalog.load_table(identifier)
                recorded = recorded_columns(table)
                if not recorded.links or table.current_snapshot() is None:
                    continue
            except Exception:  # noqa: BLE001 - survey() reports a table that cannot be read
                continue
            for owner in sorted({name for names in recorded.ids.values() for name in names}
                                - set(schema)):
                id_columns = [column for column, names in recorded.ids.items() if owner in names]
                link_columns = {column: {target for who, target in pairs if who == owner}
                                for column, pairs in recorded.links.items()
                                if any(who == owner for who, _ in pairs)}
                if id_columns and link_columns:
                    found.append((_once(table, identifier), owner, id_columns, link_columns))
    return found


def _once(table, identifier: str):
    cache: list = []

    def rows() -> list:
        if not cache:
            try:
                cache.append(table.scan().to_arrow().to_pylist())
            except Exception as e:  # noqa: BLE001 - purge() reports the table that cannot be read
                logger.warning("erasure: %s cannot be read to follow links (%s)",
                               identifier, type(e).__name__)
                cache.append([])
        return cache[0]
    return rows


def plain_token(object_type: str, object_id) -> tuple[str, str]:
    return (object_type, str(object_id))


def cascade_tokens(catalog, schema: dict, seeds: set, token=plain_token) -> set:
    """The seeds, plus every object whose forward link points at one.

    A TOKEN stands for an (object type, id): the pair itself for a request
    being made now, the register's salted hash for an erasure being applied
    again, when the ids are no longer kept. Whatever makes the tokens, the
    walk is the same.

    READ FROM GOLD, which holds every type's links in the ontology's
    words -- and, for a type the ontology no longer has, from the tables
    that recorded which of their columns are its ids and which are its
    links (record_key_columns), since gold's schema entry for it is gone.
    Both are repeated until nothing new is found, so a chain -- a ticket on
    a transaction of the customer -- is followed to its end. A removed
    type's rows found this way are erased in every layer by their own id,
    its per-id history and conflicts included.
    """
    erased = set(seeds)
    frontier = set(erased)
    removed_types = _removed_types_tables(catalog, schema)
    while frontier:
        found: set = set()
        for rows, owner, id_columns, link_columns in removed_types:
            for row in rows():
                if any(row.get(column) is not None and token(target, row[column]) in frontier
                       for column, targets in link_columns.items() for target in targets):
                    found |= {token(owner, row[column]) for column in id_columns
                              if row.get(column) is not None}
        frontier_types = {target for target, _ in frontier}
        for object_type, type_def in schema.items():
            links = [field_name for field_name, info in (type_def.get("fields") or {}).items()
                     if info.get("type") == "link" and info.get("cardinality") == "one"
                     and info.get("target") in frontier_types]
            if not links:
                continue
            try:
                rows = catalog.load_table(f"gold.{object_type}").scan().to_arrow().to_pylist()
            except Exception:  # noqa: BLE001 - a type never published, or unreadable (purge() says), has nothing to cascade
                continue
            for row in rows:
                for field_name in links:
                    target = type_def["fields"][field_name].get("target")
                    if row.get(field_name) is not None and token(target, row[field_name]) in frontier:
                        found.add(token(object_type, row.get(type_def["id_field"])))
        frontier = found - erased
        erased |= frontier
    return erased


def cascade(catalog, schema: dict, keys: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The keys, plus every object whose forward link points at one
    (cascade_tokens, with the ids themselves as tokens)."""
    return sorted(cascade_tokens(catalog, schema, {plain_token(*key) for key in keys}))


def purge(catalog, schema: dict, register: ErasureRegister) -> ErasureResult:
    """Rewrites every mirror table without the erased rows, and drops
    every older snapshot and tag that still holds them.

    The result names the rows removed per table AND what it could not
    search (ErasureResult.reach): tables that hold data with no known keys,
    that cannot be read, or whose data cannot be read, and tables searched
    only by the columns known for them. Those are reported, logged and
    recorded on the register against each erasure they could affect, as its
    `incomplete` tables, never skipped quietly -- and one table that cannot
    be read never stops the others. The caller then deletes the
    unreferenced files (integrity.orphaned_data_files with no margin)
    under the sync lock -- this function leaves the warehouse with the old
    files unreferenced, not yet gone.
    """
    from core.mirror.gold import PUBLISHED_TAG, _tag_publication

    hashes = register.hashes_by_type()
    key_hash = register.hasher()
    reach = survey(catalog, schema, {name for name, found in hashes.items() if found})
    removed: dict[str, int] = {}
    unreadable: dict[str, str] = {}
    for namespace in catalog.list_namespaces():
        for parts in catalog.list_tables(namespace):
            identifier = ".".join(parts)
            if reach.unreachable.get(identifier, "").startswith("cannot be read"):
                continue
            try:
                table = catalog.load_table(identifier)
                columns = known_columns(schema, identifier, table).keys
                if not columns or table.current_snapshot() is None:
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
            except Exception as e:  # noqa: BLE001 - named by kind; the others go on
                unreadable[identifier] = f"data cannot be read or rewritten ({type(e).__name__})"
    reach = replace(reach, unreachable={**reach.unreachable, **unreadable})
    for line in gap_notice(reach):
        logger.warning("erasure: %s", line)
    incomplete = {erasure_id: relevant_tables(reach, schema, types)
                  for erasure_id, types in register.types_by_erasure().items()}
    register.mark_purged({erasure_id: names for erasure_id, names in incomplete.items() if names})
    return ErasureResult(removed, reach, {k: v for k, v in incomplete.items() if v})


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
    caller holds the sync lock (run_sync does), so none is in flight.

    AN INCOMPLETE ERASURE IS WORKED OUT AGAIN FROM ITS SEED KEYS first: the
    lake may have changed since (a type restored, a table adopted), and what
    depends on the person is found against the lake as it is now."""
    from core.mirror.integrity import orphaned_data_files

    incomplete = register.incomplete_erasures()
    if incomplete:
        key_hash = register.hasher()

        def hashed(object_type, object_id):
            return (object_type, key_hash(object_type, object_id))
        seeds = register.seeds_by_erasure()
        for erasure_id in incomplete:
            found = cascade_tokens(catalog, schema, seeds.get(erasure_id, set()), hashed)
            register.add_derived(erasure_id, found - seeds.get(erasure_id, set()))
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
