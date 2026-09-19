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

import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

# HOW LONG ONE QUERY MAY RUN, in seconds.
#
# THERE IS ONE WORKER PROCESS, so a hung query does not slow the
# service down -- it stops it. A few of them and nothing is served at
# all.
#
# THIRTY SECONDS is far above any query a deployment should be issuing
# (the scan ceiling bounds the largest read at about 50ms, measured)
# and far below a person's patience. It is a backstop against a query
# that will never finish, not a performance target.
#
# SQLite ON LOCAL DISK RARELY HANGS. This exists because the same
# mechanism must be there when a NETWORK database is the source, and a
# timeout added with the first network adapter would be a timeout
# nobody had ever seen fire.
DEFAULT_QUERY_TIMEOUT_SECONDS = 30.0

# HOW OFTEN THE DEADLINE IS CHECKED, in SQLite virtual-machine steps.
#
# The handler runs every N instructions, so this trades responsiveness
# against overhead. 10,000 is roughly a millisecond of work on a
# modern machine: fine enough that a runaway query stops promptly,
# coarse enough that an ordinary one never notices.
_PROGRESS_STEPS = 10_000


def open_connection(db_path: Path, read_only: bool = False,
                    timeout_seconds: float | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # A DEADLINE PER CONNECTION, enforced by SQLite itself.
    #
    # set_progress_handler runs a callback every _PROGRESS_STEPS
    # virtual-machine instructions; returning non-zero ABORTS the
    # statement with OperationalError("interrupted"). Verified.
    #
    # PER CONNECTION AND NOT PER STATEMENT, which is a real
    # simplification: a connection used for several statements shares
    # one deadline from when it opened. Every read path here opens a
    # connection, runs its query and closes, so the two coincide --
    # and a caller that held one open across many queries would get a
    # stricter bound than it asked for, which is the safe direction to
    # be wrong in.
    limit = (
        DEFAULT_QUERY_TIMEOUT_SECONDS if timeout_seconds is None
        else timeout_seconds
    )
    if limit and limit > 0:
        deadline = time.monotonic() + limit
        conn.set_progress_handler(
            lambda: 1 if time.monotonic() > deadline else 0, _PROGRESS_STEPS,
        )
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


# THE SQLITE THAT `json_each` NEEDS.
#
# The function comes from the json1 extension, ALWAYS present from
# 3.38 (2022) and usually present from 3.9 (2015) because most builds
# compile it in. 3.38 is the line where it stops depending on how the
# library was built.
#
# WHY A FLOOR AT ALL: the write log passes a list of ids as ONE JSON
# parameter rather than building placeholders, which is what removed
# two `S608` suppressions and the chunking loop that existed to
# respect SQLite's variable limit.
MINIMUM_SQLITE_FOR_JSON_EACH = (3, 38, 0)


def require_json_each() -> None:
    """Refuses to start if this SQLite cannot expand a JSON array.

    AT STARTUP, NOT AT THE FIRST READ. Without this the failure
    arrives as "no such function: json_each" from inside a write-log
    lookup -- accurate, and it names neither the requirement nor what
    to do about it.

    THE SAME SHAPE AS require_assertions_enabled(), and for the same
    reason: a deployment that cannot satisfy an assumption should say
    so before it starts serving, not while it is.
    """
    version = tuple(int(part) for part in sqlite3.sqlite_version.split("."))
    if version >= MINIMUM_SQLITE_FOR_JSON_EACH:
        return

    # BELOW THE LINE IS NOT AUTOMATICALLY BROKEN. json_each may still
    # be compiled in, so this ASKS rather than assuming -- an
    # unnecessary refusal on a working build would be its own defect.
    try:
        sqlite3.connect(":memory:").execute(
            "SELECT value FROM json_each('[1]')",
        ).fetchone()
    except sqlite3.OperationalError as e:
        raise RuntimeError(
            f"This SQLite ({sqlite3.sqlite_version}) cannot run json_each, "
            f"which Elysium's write log needs: {e}. Build or install SQLite "
            f"{'.'.join(str(n) for n in MINIMUM_SQLITE_FOR_JSON_EACH)} or "
            f"later, where it is always available."
        ) from e


def require_assertions_enabled() -> None:
    """Refuses to start if Python's assertions have been disabled.

    Several of this project's INVARIANTS are enforced by `assert`, not
    by raises: that a batch is only marked applied when every sub-write
    produced an id, that a write-log row is only marked applied when
    every storage group committed, that a lock set contains no
    duplicate (threading.Lock is not reentrant, so a duplicate HANGS),
    and that a committed mirror snapshot holds what was written.

    Running with -O or PYTHONOPTIMIZE=1 strips all of them. The
    failures they catch do not become louder -- they become silent, and
    two of them are unrecoverable once missed: a batch marked applied
    is never revisited, and a stale index row nothing reconciles.

    REFUSING TO START rather than warning, deliberately. This project's
    stated discipline is to fail loudly rather than silently
    substitute, and running with invariants stripped while the
    documentation says they are live is exactly a silent substitution.
    Nobody sets -O for this application by accident and on purpose at
    the same time; if they did, they should be told what it costs.

    This check was added because the claim "asserts are live in
    production" had been made in PRINCIPLES.md and a commit message
    after checking install/ and scripts/ -- and NOT the systemd unit or
    any container entrypoint, which are the paths that would actually
    carry the setting. The claim happened to be true. It was not
    verified.
    """
    if not __debug__:
        raise RuntimeError(
            "Elysium requires Python assertions to be enabled: several data-integrity "
            "invariants are enforced by `assert` and are stripped by -O / "
            "PYTHONOPTIMIZE. Remove -O from the interpreter flags and unset "
            "PYTHONOPTIMIZE, then start again."
        )


@contextmanager
def immediate_transaction(conn: sqlite3.Connection):
    """Runs a read-modify-write as ONE genuinely atomic transaction.

    THE REAL PROBLEM THIS SOLVES, proven empirically before writing it
    rather than reasoned about: Python's sqlite3 defaults to
    isolation_level='' , which opens a transaction lazily on the first
    INSERT/UPDATE/DELETE -- NOT on a SELECT. So the classic
    "read current state, decide, then write" sequence has its READ
    outside any transaction, and two concurrent callers can both read
    the same pre-state and both proceed.

    A real, reproduced demonstration: two threads calling LockStore's
    own acquire() against a free resource were BOTH told they had
    acquired it, while only one actually held it afterwards -- a lock
    service granting the same lock twice, which defeats its entire
    purpose.

    BEGIN IMMEDIATE takes SQLite's write lock up front, before the
    read, so a second caller blocks (up to the connection's own
    timeout) rather than reading stale state and acting on it. Verified
    directly: with this in place, exactly one of two concurrent
    acquirers succeeds and the other is correctly denied.

    Deliberately NOT solved with a Python-level threading.Lock: these
    stores are reached from a real, multi-worker deployment where two
    processes can genuinely race, and an in-process lock protects
    neither. The database is the only shared thing, so the database has
    to be where the ordering is decided.
    """
    # isolation_level=None hands transaction control to us explicitly,
    # rather than sqlite3 guessing where a transaction should start.
    previous = conn.isolation_level
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.isolation_level = previous


_schema_verified: set[Path] = set()
_schema_verified_lock = threading.Lock()
logger = logging.getLogger(__name__)


def _enable_wal(conn: sqlite3.Connection, db_path: Path) -> None:
    """Write-ahead logging, so a commit does not stall readers.

    MEASURED BEFORE CHANGING, because changing journal mode blind on
    the store holding credentials and the write log is not the shape of
    change this project makes. Four readers against one writer, three
    seconds, same machine:

        rollback  606,793 reads  p50 0.003ms  p99 0.02ms  max 241ms
        WAL     1,312,596 reads  p50 0.002ms  p99 0.01ms  max  48ms

    Twice the read throughput and a fifth of the worst case. The p50
    barely moves, which is the tell: this is entirely about the tail.

    THE RECORDED CONCERN WAS OVERSTATED AND THE MEASUREMENT SAYS SO.
    IDEAS.md described rollback mode as one where "a writer blocks all
    readers for the duration of its transaction". It does not -- a
    BEGIN IMMEDIATE takes a RESERVED lock, and RESERVED permits
    readers. Only the brief EXCLUSIVE phase during COMMIT blocks them,
    which is why the median is unaffected and the maximum is not.

    SET ONCE, AT SCHEMA CREATION, not per connection. Journal mode is
    persistent -- SQLite stores it in the database header -- so setting
    it on every open would be a redundant write, and read-only
    connections cannot do it at all: their authorizer denies PRAGMA,
    the same control that shaped columns_present().

    WAL DOES NOT WORK OVER A NETWORK FILESYSTEM. Every database this
    touches (credentials, write_log, artifacts, config_history) lives
    under the deployment's own data_dir on local disk. A deployment
    putting data_dir on NFS would find this failing loudly at startup
    rather than silently degrading, which is the right direction: the
    return value is checked.

    It also creates -wal and -shm files beside the database, which a
    backup has to account for. Noted in INSTALL.md.
    """
    mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    if mode.lower() != "wal":
        # Loudly, not silently. A deployment that cannot use WAL is
        # still correct -- rollback journal is safe, just slower under
        # concurrent reads -- so this warns rather than refusing to
        # start.
        logger.warning(
            f"could not enable WAL on {db_path} (journal_mode is {mode!r}). "
            f"Reads will stall briefly during writes. This usually means the "
            f"database is on a network filesystem, which WAL does not support."
        )


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
        # The lock is held ACROSS the check, the work and the add --
        # not released in between. Releasing it made this a
        # check-then-act: two threads both saw the database
        # unverified, and both ran the schema and every migration.
        #
        # That is harmless TODAY only because the schema uses CREATE
        # TABLE IF NOT EXISTS and the one existing migration catches
        # the "column already exists" error. It is safe by coincidence,
        # not by construction: a future migration that is not
        # idempotent would corrupt the database, and nothing here would
        # have warned anyone. Holding the lock costs a brief
        # serialization once per database and removes the trap.
        with _schema_verified_lock:
            if db_path not in _schema_verified:
                _enable_wal(conn, db_path)
                conn.executescript(schema)
                for migrate in migrations:
                    migrate(conn)
                conn.commit()
                _schema_verified.add(db_path)
        yield conn
    finally:
        conn.close()
