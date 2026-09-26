"""
database.py  (the ONE shared connection/schema for credentials,
sessions, and the runtime user directory)

Deliberately NOT a DataSiloAdapter, NOT part of the swappable registry --
a deployer chooses their own business-data backend, but never "which
database stores passwords." This is fixed, private infrastructure, same
reasoning that kept action tools out of adapters/: pluggability is for
things a deployer should genuinely get to choose.

Five tables, one physical database, THIS file is the single source of
truth for what tables exist -- credential_store.py, session_store.py,
core/user_directory.py, login_attempt_tracker.py, and
query_rate_limiter.py each own the QUERIES against their own table,
but none of them declares schema independently.

db_path is always an explicit parameter, never a hardcoded global path --
same dependency-injection discipline as every other adapter in this
project. The real path (e.g. /var/lib/OUR-SOFTWARE/credentials.db in a
real install) is the caller's decision; tests pass a temp path.

Schema creation and migration are handled by core/sqlite_connection.py's
shared connection_with_schema() -- cached per db_path within THIS
process, so CREATE TABLE IF NOT EXISTS and the migration below only
actually run once, not on literally every single connection the way
they used to (a real, previously-unnoticed cost on what can be a hot
path, e.g. every login/session check).

_migrate_add_disabled_column exists because CREATE TABLE IF NOT EXISTS
is a no-op against an ALREADY-existing users table -- it does NOT add
new columns to a table that predates this column. Any real, already-
running deployment's credentials.db needs this column added to its
EXISTING table, not just a fresh one created correctly going forward.
SQLite has no "ADD COLUMN IF NOT EXISTS" -- the standard, idiomatic
pattern is attempting the ALTER and catching the OperationalError it
raises if the column already exists.
"""

import sqlite3
from pathlib import Path

from core.sqlite_connection import add_column_if_missing, connection_with_schema

SCHEMA = """
CREATE TABLE IF NOT EXISTS credentials (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
-- `token` HOLDS THE SHA-256 OF THE SESSION TOKEN, never the token --
-- see core/auth/session_store.py. The name is kept so the table need
-- not be rebuilt; this comment is what stops anybody inserting a raw one.
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    mac_value TEXT,
    role_name TEXT NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0,
    -- SET BY AN ADMINISTRATOR'S RESET, cleared by the owner choosing
    -- their own. While set, the account may only change its password.
    must_change_password INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS login_attempts (
    username TEXT PRIMARY KEY,
    failed_count INTEGER NOT NULL DEFAULT 0,
    window_started_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS query_rate_limits (
    user_id TEXT PRIMARY KEY,
    query_count INTEGER NOT NULL DEFAULT 0,
    window_started_at TEXT NOT NULL
);
"""


def _migrate_add_disabled_column(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # already exists -- either a fresh DB (SCHEMA above already
              # included it) or a previously-migrated one


def _migrate_destroy_raw_session_tokens(conn: sqlite3.Connection) -> None:
    """Deletes every session stored as its RAW token.

    THE RAW ROWS ARE THE LEAK. After tokens began to be stored hashed, a
    raw row could no longer be USED -- a lookup by hash cannot match it
    -- but it would still sit in credentials.db, readable by anybody
    with the file, until it expired. So it is destroyed, not left.

    TOLD APART BY LENGTH: a raw token_urlsafe(32) is 43 characters, a
    SHA-256 hex digest 64. So this deletes exactly the raw rows, and on
    every later start finds none -- safe to run each time. Everybody is
    logged out ONCE, by the upgrade that introduces hashing.
    """
    conn.execute("DELETE FROM sessions WHERE length(token) != 64")
    conn.commit()


def connection(db_path: Path):
    return connection_with_schema(
        db_path, SCHEMA,
        migrations=(
            _migrate_add_disabled_column,
            _migrate_destroy_raw_session_tokens,
            # THROUGH add_column_if_missing, which checks the table's
            # columns, rather than swallowing an ALTER's OperationalError
            # as the disabled migration does -- an error swallowed for
            # "already exists" is also swallowed for "read-only" or
            # "locked".
            add_column_if_missing("users", "must_change_password", "INTEGER NOT NULL DEFAULT 0"),
            # WHICH SOURCE CREATED THIS ROW (E-02's residual). Nullable,
            # so every row written before this column existed migrates
            # without a value and is simply never counted against a
            # budget -- see login_attempt_tracker.record_failure().
            add_column_if_missing("login_attempts", "source", "TEXT"),
        ),
    )
