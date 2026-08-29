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


def open_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


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
