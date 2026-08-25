"""
database.py  (the ONE shared connection/schema for credentials + sessions)

Deliberately NOT a DataSiloAdapter, NOT part of the swappable registry --
a deployer chooses their own business-data backend, but never "which
database stores passwords." This is fixed, private infrastructure, same
reasoning that kept action tools out of adapters/: pluggability is for
things a deployer should genuinely get to choose.

db_path is always an explicit parameter, never a hardcoded global path --
same dependency-injection discipline as every other adapter in this
project. The real path (e.g. /var/lib/OUR-SOFTWARE/credentials.db in a
real install) is the caller's decision; tests pass a temp path.

Schema created idempotently on every connection (CREATE TABLE IF NOT
EXISTS) -- cheap, and guarantees the schema always exists regardless of
call order, matching sqlite_adapter.py's "fresh connection per call, no
persistent pooling" pattern.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS credentials (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""


@contextmanager
def connection(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
    finally:
        conn.close()
