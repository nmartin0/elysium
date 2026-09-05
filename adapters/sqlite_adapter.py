"""
sqlite_adapter.py  (SQLite-specific -- the only place SQL syntax exists)

Two real, separate classes -- SQLiteReadAdapter(ExternalReadAdapter) and
SQLiteWriteAdapter(ExternalWriteAdapter) -- not the single, combined
SQLiteAdapter this file used to define. A real, direct request, worked
through carefully: "adapters/ should just be the veneer that extends
down the implementation-specific interfacing" against the real,
structural ExternalReadAdapter/ExternalWriteAdapter split in core/
ontology/interface.py -- see that file's own module docstring for the
fuller design reasoning. Each class here holds ONLY the SQLite-specific
connection/query mechanics for its own real role; the shared, module-
level _run_query()/_run_query_one() helpers below are pure, stateless
query-execution mechanics, not adapter state or capability, so staying
shared between both classes doesn't blur the real read/write line this
whole split exists to draw.

The raw SQLite mechanics (_connect/_run_query/_run_query_one) are only
ever used by the two classes below -- a real 1:1 relationship, not a
shared layer serving many adapters. Splitting them into a separate
connectors/ package would have added a file without adding a real
architectural seam (see design discussion: adapters/ is pluggable via
config + registry; there is no equivalent second mechanism for a
"connector" layer to plug into).

Purely mechanical -- no security logic, no policy judgment.
core/ontology/mediator.py's DataMediator (reads) and core/ontology/
write_mediator.py's WriteMediator (writes) are the only real callers,
and only ever call a method here after their own checks have already
passed.

CONCURRENCY: SQLiteWriteAdapter declares max_concurrent_writes=1
(SQLite's write lock is whole-FILE -- see core/ontology/interface.py's
own docstring for why this is a real, honest exception, not the
default). Reads are otherwise handled by DataMediator's own per-object
lock plus this adapter's atomic conditional write_fields() -- see that
method's docstring for the actual lost-update-prevention mechanism.

Used by: core/deployment_loader.py (constructs one READ instance and
         one, genuinely SEPARATE, WRITE instance per silo declared in
         a deployment's data_silos.yaml -- see that file's own
         _build_adapters() and its own AI-notes for why two, not one)
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.ontology.interface import ExternalReadAdapter, ExternalWriteAdapter
from core.sqlite_connection import open_connection as _connect


def _run_query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def _run_query_one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row is not None else None


class SQLiteReadAdapter(ExternalReadAdapter):
    # Reads are genuinely fine concurrently -- SQLite handles that
    # natively.
    max_concurrent_reads = None

    def __init__(self, connection: dict):
        # connection comes straight from this silo's config.yaml block,
        # e.g. {"path": "dev_fixtures/mediator.db"} -- opaque to
        # DataMediator, meaningful only here.
        self.db_path = Path(connection["path"])

    @contextmanager
    def _connection(self):
        conn = _connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def find_ids(self, object_type: str, criteria: dict, type_config: dict) -> list[Any]:
        table = type_config["storage"]["table"]
        id_column = type_config["storage"]["id_column"]

        # Column NAMES are validated by DataMediator before this is ever
        # called; VALUES are always bound params, never interpolated.
        where_clause = " AND ".join(f"{key} = ?" for key in criteria.keys())
        values = tuple(criteria.values())

        with self._connection() as conn:
            if where_clause:
                rows = _run_query(conn, f"SELECT {id_column} FROM {table} WHERE {where_clause}", values)
            else:
                rows = _run_query(conn, f"SELECT {id_column} FROM {table}")
            return [row[id_column] for row in rows]

    def find_ids_matching_text(self, object_type: str, columns: list[str], query_text: str,
                                type_config: dict) -> list[Any]:
        # Free-text, CONTAINS (not exact-match) search across several
        # columns at once, ORed together -- the human-facing browse/
        # search counterpart to find_ids()'s own exact-match filtering,
        # which stays completely untouched by this addition (a genuinely
        # different KIND of match, not a mode flag bolted onto the
        # existing method -- see core/ontology/mediator.py's own AI-
        # notes for the fuller reasoning). SQLite's LIKE is already
        # case-insensitive for ASCII by default (verified directly, not
        # assumed) -- no explicit LOWER() needed on either side.
        #
        # query_text is escaped for LIKE's own wildcard characters (%, _)
        # before being wrapped in %...% -- verified directly (not
        # assumed) that an unescaped search for a literal "50%" would
        # otherwise ALSO match "50X" and similar, since % is a genuine
        # SQL wildcard, not a literal character, unless told otherwise
        # via ESCAPE. Column NAMES are validated by DataMediator before
        # this is ever called, same as find_ids(); the query VALUE is
        # always a bound param, never interpolated, same discipline.
        table = type_config["storage"]["table"]
        id_column = type_config["storage"]["id_column"]

        if not columns:
            return []

        escaped = query_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        where_clause = " OR ".join(f"{column} LIKE ? ESCAPE '\\'" for column in columns)
        values = tuple(pattern for _ in columns)

        with self._connection() as conn:
            rows = _run_query(conn, f"SELECT {id_column} FROM {table} WHERE {where_clause}", values)
            return [row[id_column] for row in rows]

    def get_raw_field(self, object_type: str, object_id: Any, field_name: str, type_config: dict) -> Any:
        table = type_config["storage"]["table"]
        id_column = type_config["storage"]["id_column"]

        with self._connection() as conn:
            row = _run_query_one(
                conn, f"SELECT {field_name} FROM {table} WHERE {id_column} = ?", (object_id,)
            )
            return row[field_name] if row else None

    def resolve_reverse_link(self, object_id: Any, field_config: dict, target_id_column: str) -> list[Any]:
        via_table = field_config["via_table"]
        via_column = field_config["via_column"]

        with self._connection() as conn:
            rows = _run_query(
                conn, f"SELECT {target_id_column} FROM {via_table} WHERE {via_column} = ?", (object_id,)
            )
            return [row[target_id_column] for row in rows]


class SQLiteWriteAdapter(SQLiteReadAdapter, ExternalWriteAdapter):
    # Extends SQLiteReadAdapter directly -- not a second, parallel
    # implementation of find_ids/get_raw_field/etc, and not ONLY
    # ExternalWriteAdapter either. A real, necessary correction caught
    # directly, not assumed away: WriteMediator's own write flow
    # genuinely needs to READ a field's current value before writing
    # it (the optimistic-concurrency check -- see write_mediator.py's
    # own _read_group_fields()), so the write-side adapter needs BOTH
    # real capabilities, not write-only. This is the SAME real,
    # established pattern already cited when choosing the whole
    # ReadAdapter/WriteAdapter split in the first place (Python's own
    # typeshed: a concrete type needing both SupportsRead and
    # SupportsWrite composes them via real inheritance from the
    # separate, atomic pieces -- never a third, redundant "does
    # everything" interface invented from scratch). Inheriting from
    # SQLiteReadAdapter directly, rather than re-declaring the same
    # four read methods here, means there is exactly ONE real
    # implementation of find_ids/find_ids_matching_text/get_raw_field/
    # resolve_reverse_link in this whole file, not two to keep in
    # sync.
    #
    # SQLite's write lock is whole-FILE -- coarser than DataMediator's
    # per-object correctness lock, which is why this is a real, honest
    # exception rather than None (see core/ontology/interface.py's own
    # docstring).
    max_concurrent_writes = 1
    supports_atomic_conditional_write = True

    def write_fields(self, object_type: str, object_id: Any, changes: dict,
                      expected_current_values: dict, type_config: dict) -> bool:
        # ONE atomic SQL statement -- all fields in `changes` written
        # together, all-or-nothing, AND conditional on every field in
        # expected_current_values still matching. If another writer
        # changed the row in between, the WHERE clause simply matches
        # nothing: rowcount == 0, we return False, nothing is written.
        # This is a genuine database-level atomicity guarantee -- holds
        # even across separate OS processes, not just threads within
        # this one (see core/ontology/interface.py's own
        # supports_atomic_conditional_write docstring for why that
        # distinction matters).
        table = type_config["storage"]["table"]
        id_column = type_config["storage"]["id_column"]

        set_clause = ", ".join(f"{key} = ?" for key in changes)
        # "IS ?", not "= ?" -- a REAL, confirmed bug otherwise: in SQL,
        # "column = NULL" always evaluates to NULL/unknown, never TRUE,
        # even when the actual stored value genuinely IS NULL. This
        # made the lost-update check silently, always fail for any
        # field whose CURRENT value happens to be NULL -- confirmed
        # directly (a real ValueError, "changed since this write was
        # proposed," on a field that had never actually changed at
        # all) while testing propose_action() against a field that
        # legitimately started NULL. SQLite's "IS" is null-safe
        # equality -- identical to "=" for non-NULL values, but
        # correctly treats NULL as a real, comparable value.
        condition_clause = " AND ".join(f"{key} IS ?" for key in expected_current_values)
        where_clause = f"{id_column} = ?" + (f" AND {condition_clause}" if condition_clause else "")

        with self._connection() as conn:
            cursor = conn.execute(
                f"UPDATE {table} SET {set_clause} WHERE {where_clause}",
                (*changes.values(), object_id, *expected_current_values.values()),
            )
            conn.commit()
            return cursor.rowcount > 0

    def create_object(self, object_type: str, fields: dict, type_config: dict) -> Any:
        table = type_config["storage"]["table"]
        id_column = type_config["storage"]["id_column"]

        columns = ", ".join(fields.keys())
        placeholders = ", ".join("?" for _ in fields)

        with self._connection() as conn:
            cursor = conn.execute(
                f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(fields.values())
            )
            conn.commit()
            new_id = cursor.lastrowid
            # For non-autoincrement / string-keyed tables, lastrowid is
            # meaningless -- fall back to whatever the caller supplied
            # as the id_column value directly, if present.
            return fields.get(id_column, new_id)


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# RESOLVED (kept for history):
# - The single, combined SQLiteAdapter class split into
#   SQLiteReadAdapter/SQLiteWriteAdapter -- see core/ontology/
#   interface.py's own AI-notes for the fuller story (the same real,
#   direct request that motivated the ExternalReadAdapter/
#   ExternalWriteAdapter split this file's two classes now extend).
#   Both classes still point at the SAME real db_path today (see
#   core/deployment_loader.py's own _build_adapters(), called twice --
#   once for DataMediator's own read adapters, once for WriteMediator's
#   own write adapters) -- this split is the real, STRUCTURAL half of
#   the guarantee; the credential-level half (a genuinely different,
#   SELECT-only database user for the read side) is a separate,
#   later phase, not yet done.
# - find_ids_matching_text() -- the free-text, CONTAINS-match search
#   underneath DataMediator.search_object_free_text() (see that
#   method's own AI-notes for the fuller design and why it's a
#   genuinely separate method from find_ids(), not a mode flag on it).
#   A real, confirmed SQL gotcha caught DIRECTLY, empirically, before
#   this method ever shipped, not assumed away: SQLite's own LIKE
#   operator treats "%" and "_" as genuine wildcards, not literal
#   characters -- an unescaped search for a literal "50%" would ALSO
#   match "50X" and similar (proven with a real, in-memory SQLite
#   query before writing the fix, then re-proven with a real row in
#   tests/unit/test_sqlite_adapter_find_ids_matching_text.py, both
#   "%" and "_" separately). Fixed via backslash-escaping both
#   characters in the query text before wrapping it in %...%, plus an
#   explicit ESCAPE '\\' clause on every LIKE. Also confirmed directly
#   (not assumed): SQLite's LIKE is already case-insensitive for ASCII
#   by default, so no explicit LOWER() was needed on either side; and
#   SQLite's own dynamic typing correctly coerces a real INTEGER
#   column to text for a LIKE comparison, so numeric fields (e.g. a
#   year) are genuinely free-text-searchable too, not silently
#   unmatchable.
