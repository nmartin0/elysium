"""
sqlite_connection.py  (the ONE shared "open a raw connection" helper --
and the ONE shared "open a connection with an idempotent, self-owned
schema" helper)

Used by adapters/sqlite_adapter.py (swappable, business-data adapter)
AND core/auth/database.py (fixed, non-adapter security infrastructure)
AND core/ontology/write_log.py (fixed, non-adapter write-atomicity
infrastructure) -- genuinely different purposes at the architecture
level, which is why they stay separate files, not one merged module.
But the exact mechanical act of opening a connection was, before this,
identical code duplicated across them -- real DRY territory (same
KNOWLEDGE, not just similar syntax): if every connection ever needed an
added pragma (e.g. foreign_keys = ON), it would be easy to update one
file and forget the others. open_connection() is that one shared
mechanical piece, extracted, without collapsing the real separation
between the callers.

open_connection()'s own read_only parameter -- a real, structural,
SQLite-engine-enforced guarantee (sqlite3.Connection.set_authorizer(),
confirmed directly, empirically, before being relied on anywhere: a
real, isolated test proved SELECT succeeds while INSERT/UPDATE/DROP
are all genuinely denied at the engine level, not just skipped by
convention) -- used by core/internal_storage.py's own InternalReadAdapter,
and by adapters/sqlite_adapter.py's own read-side adapter for external,
third-party business data. A read-only connection can NEVER be the one
responsible for lazy schema creation (CREATE TABLE IS a write-type
operation the authorizer denies same as any other) -- see
connection_with_schema() below, which always opens its own connection
WITHOUT read_only, and core/internal_storage.py's own docstring for the
real, load-bearing consequence: schema creation happens once,
explicitly, at real deployment/app-startup time, via a genuine write-
capable connection, before a read-only one for the same database is
ever constructed -- never lazily, on first use, the way it works for a
write-capable connection today.

connection_with_schema() extracts a SECOND, higher-level pattern that
had ALSO ended up duplicated: database.py and write_log.py each own a
FIXED, INTERNAL schema (unlike sqlite_adapter.py, which deliberately
never creates or knows about business-data schema at all -- that's the
deployer's own, arbitrary table, not something this project should be
issuing CREATE TABLE for). Both had independently hand-written their
own "open, ensure my schema exists, commit, yield, close" context
manager -- the SAME pattern, not just similar-looking code. One shared
place for it means one place to fix if it ever needs to change, and
one place that already handles the real, avoidable cost of re-running
CREATE TABLE IF NOT EXISTS on literally every single call (harmless,
but genuinely wasteful on a hot path -- e.g. write_log.py's
get_pending_changes(), called on every single DataMediator.get_field()
once the write log is enabled): schema verification is cached per
db_path, in-process, so it only actually runs once.
"""

import sqlite3
import threading
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path


def open_connection(db_path: Path, read_only: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if read_only:
        # Confirmed directly, empirically, before relying on this (a
        # real, isolated test: SELECT succeeded, INSERT/UPDATE/DROP
        # were all genuinely denied at the SQLite engine level itself,
        # not just skipped by application code) -- see core/
        # internal_storage.py's own module docstring for the fuller
        # story (Phase 0/1 of the read-only mirror initiative, and the
        # internal-adapter hierarchy that followed it). Only SELECT/
        # READ/FUNCTION operations are ever allowed through; every
        # write-type operation (INSERT, UPDATE, DELETE, and DDL like
        # CREATE TABLE) is denied -- which is exactly why a read-only
        # connection must never also be the one responsible for lazy
        # schema creation (see connection_with_schema() below, and
        # core/internal_storage.py's own docstring on the real
        # consequence: schema creation must happen once, explicitly,
        # at startup, via a real write-capable connection, before a
        # read-only one for the same database is ever constructed).
        conn.set_authorizer(_deny_all_writes)
    return conn


def _deny_all_writes(action_code: int, _arg1: str | None, _arg2: str | None,
                      _db_name: str | None, _trigger_name: str | None) -> int:
    if action_code in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


_schema_verified: set[Path] = set()
_schema_verified_lock = threading.Lock()


@contextmanager
def connection_with_schema(db_path: Path, schema: str,
                            migrations: tuple[Callable[[sqlite3.Connection], None], ...] = ()):
    # migrations run AFTER the schema's own CREATE TABLE IF NOT EXISTS,
    # same as database.py's own _migrate_add_disabled_column previously
    # did inline -- for adding a column to an ALREADY-existing table
    # from an earlier version of this schema, which CREATE TABLE IF NOT
    # EXISTS is a no-op against. Only run on the SAME first-verification
    # pass as the schema itself -- a migration only ever needs to run
    # once per db_path per process, exactly like schema creation does.
    #
    # The verified-set check is a harmless race, not a correctness
    # requirement, if two threads somehow both see "not yet verified"
    # at once -- CREATE TABLE IF NOT EXISTS (and a well-written
    # migration) is safe to run twice; the lock just makes the COMMON
    # case avoid the redundant work, not guarantee exactly-once.
    conn = open_connection(db_path)
    try:
        with _schema_verified_lock:
            already_verified = db_path in _schema_verified
        if not already_verified:
            conn.executescript(schema)
            for migrate in migrations:
                migrate(conn)
            conn.commit()
            with _schema_verified_lock:
                _schema_verified.add(db_path)
        yield conn
    finally:
        conn.close()
