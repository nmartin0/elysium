"""
sqlite_adapter.py  (SQLite-specific -- the only place SQL syntax exists)

Two halves, deliberately merged into one file rather than split across
adapters/ and a separate connectors/ package: the raw SQLite mechanics
(_connect/_run_query/_run_query_one) are only ever used by SQLiteAdapter
below -- a real 1:1 relationship, not a shared layer serving many
adapters. Splitting them would have added a file without adding a real
architectural seam (see design discussion: adapters/ is pluggable via
config + registry; there is no equivalent second mechanism for a
"connector" layer to plug into).

SQLiteAdapter implements core/ontology/interface.py's DataSiloAdapter
contract. It is purely mechanical -- no security logic, no policy
judgment. core/ontology/mediator.py's DataMediator is the only caller,
and only ever calls this after its own checks have already passed.

Used by: core/deployment_loader.py (constructs one instance per silo
         declared in a deployment's config.yaml)
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _run_query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def _run_query_one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row is not None else None


class SQLiteAdapter:
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
        table = type_config["table"]
        id_column = type_config["id_column"]

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

    def get_raw_field(self, object_type: str, object_id: Any, field_name: str, type_config: dict) -> Any:
        table = type_config["table"]
        id_column = type_config["id_column"]

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

    def write_field(self, object_type: str, object_id: Any, field_name: str,
                     value: Any, type_config: dict) -> None:
        table = type_config["table"]
        id_column = type_config["id_column"]

        with self._connection() as conn:
            conn.execute(f"UPDATE {table} SET {field_name} = ? WHERE {id_column} = ?", (value, object_id))
            conn.commit()

    def create_object(self, object_type: str, fields: dict, type_config: dict) -> Any:
        table = type_config["table"]
        id_column = type_config["id_column"]

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
