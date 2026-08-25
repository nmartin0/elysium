"""
database.py  (the ONE shared connection/schema for credentials,
sessions, and the runtime user directory)

Deliberately NOT a DataSiloAdapter, NOT part of the swappable registry --
a deployer chooses their own business-data backend, but never "which
database stores passwords." This is fixed, private infrastructure, same
reasoning that kept action tools out of adapters/: pluggability is for
things a deployer should genuinely get to choose.

Three tables, one physical database, THIS file is the single source of
truth for what tables exist -- credential_store.py, session_store.py,
and core/user_directory.py each own the QUERIES against their own
table, but none of them declares schema independently.

db_path is always an explicit parameter, never a hardcoded global path --
same dependency-injection discipline as every other adapter in this
project. The real path (e.g. /var/lib/OUR-SOFTWARE/credentials.db in a
real install) is the caller's decision; tests pass a temp path.

Schema created idempotently on every connection (CREATE TABLE IF NOT
EXISTS) -- cheap, and guarantees the schema always exists regardless of
call order, matching sqlite_adapter.py's "fresh connection per call, no
persistent pooling" pattern.
"""

from contextlib import contextmanager
from pathlib import Path

from core.sqlite_connection import open_connection

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
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    mac_value TEXT,
    role_name TEXT NOT NULL
);
"""


@contextmanager
def connection(db_path: Path):
    conn = open_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        yield conn
    finally:
        conn.close()
