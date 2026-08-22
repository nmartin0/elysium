"""
sqlite_connector.py  (generic driver -- org-agnostic)

Knows how to open a SQLite file and run a parameterized query. Nothing
in this file knows about customers, transactions, regions, or any other
org-specific concept -- that knowledge belongs in deployments/, not here.

Any deployment using a SQLite-backed silo can reuse this file unchanged.

Used by: deployments/<org>/ontology_adapter.py (or equivalent per-org file)
"""

import sqlite3
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # read rows back as dict-like objects
    return conn


def run_query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def run_query_one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row is not None else None
