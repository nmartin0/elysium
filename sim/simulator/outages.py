"""A source going away for a reader, and coming back (REAL_SOURCES.md O1).

Real sources go away: a database restarts or a firewall rule changes, an
API is down for maintenance, a share is unmounted. What a reader sees is
what matters here, so an outage cuts off the reader -- the account
consumers are given -- while the simulated business keeps working, as
the business's own applications do through their own connection:

  postgresql  the reader may not log in (`ALTER ROLE ... NOLOGIN`) and
              its open sessions are ended with pg_terminate_backend --
              which a client sees as SQLSTATE 57P01, "terminating
              connection due to administrator command", the error a real
              restart gives.
  mariadb     the reader's account is locked (`ACCOUNT LOCK`) and its
              connections killed; a client's next statement fails as it
              would against a server that went away.
  rest        every request answers 503 with Retry-After: the
              maintenance page real APIs serve.
  filedrop    the folder is moved aside, as an unmounted share vanishes;
              the upstream system goes on exporting into it unseen, and
              the files are there when it comes back.
  sqlite      the file is moved aside; the business's own application
              goes on writing to it there.

Restoring undoes exactly that. Nothing here touches the writer or the
superuser, so no simulated write fails because a reader was cut off.
"""

from simulator.silos.filedrop import OFFLINE_SUFFIX
from simulator.silos.reader import MARIADB_HOST, READER
from simulator.silos.rest import RestSilo


class OutageError(Exception):
    """An outage could not be started or ended."""


def cut_off(silo, database: "str | None") -> str:
    """Make `silo` unreachable to its reader. Returns what was done."""
    kind = silo.kind
    if kind == "postgresql":
        with silo.connect(autocommit=True) as conn:
            conn.execute(f'ALTER ROLE "{READER}" NOLOGIN')
            ended = conn.execute(
                "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
                "WHERE usename = %s", (READER,)).fetchone()[0]
        return f"reader may not log in; {ended} open session(s) ended (57P01)"
    if kind == "mariadb":
        with silo.connect(autocommit=True) as conn, conn.cursor() as cursor:
            cursor.execute(f"ALTER USER '{READER}'@'{MARIADB_HOST}' ACCOUNT LOCK")
            cursor.execute("SELECT ID FROM information_schema.PROCESSLIST WHERE USER = %s", (READER,))
            ids = [row[0] for row in cursor.fetchall()]
            for thread in ids:
                cursor.execute(f"KILL {int(thread)}")
        return f"reader's account locked; {len(ids)} connection(s) killed"
    if isinstance(silo, RestSilo):
        silo.maintenance = True
        return "every request answers 503 with Retry-After"
    if kind == "filedrop":
        if silo.offline:
            return "already out"
        silo.home.replace(silo.home.with_name(silo.folder + OFFLINE_SUFFIX))
        silo.offline = True
        return "the share is gone; exports continue out of sight"
    if kind == "sqlite":
        if silo.offline:
            return "already out"
        _move_sqlite(silo, silo.home, silo.home.with_name(silo.filename + OFFLINE_SUFFIX))
        silo.offline = True
        return "the file is gone; the business goes on writing to it out of sight"
    raise OutageError(f"{silo.name}: no outage for a {kind} silo")


def restore(silo, database: "str | None") -> str:
    """Undo cut_off(). Returns what was done."""
    kind = silo.kind
    if kind == "postgresql":
        with silo.connect(autocommit=True) as conn:
            conn.execute(f'ALTER ROLE "{READER}" LOGIN')
        return "reader may log in again"
    if kind == "mariadb":
        with silo.connect(autocommit=True) as conn, conn.cursor() as cursor:
            cursor.execute(f"ALTER USER '{READER}'@'{MARIADB_HOST}' ACCOUNT UNLOCK")
        return "reader's account unlocked"
    if isinstance(silo, RestSilo):
        silo.maintenance = False
        return "requests are answered again"
    if kind == "filedrop":
        aside = silo.home.with_name(silo.folder + OFFLINE_SUFFIX)
        # By what is on disk, not only the flag: a world that died while
        # a share was out comes back with the flag False and the folder
        # still aside.
        if not aside.exists() or silo.home.exists():
            silo.offline = False
            return "not out"
        aside.replace(silo.home)
        silo.offline = False
        return "the share is back, with what was exported meanwhile"
    if kind == "sqlite":
        aside = silo.home.with_name(silo.filename + OFFLINE_SUFFIX)
        if not aside.exists() or silo.home.exists():
            silo.offline = False
            return "not out"
        _move_sqlite(silo, aside, silo.home)
        silo.offline = False
        return "the file is back, with what was written meanwhile"
    raise OutageError(f"{silo.name}: no outage for a {kind} silo")


def _move_sqlite(silo, source, target) -> None:
    """Move a database in WAL mode without losing what is in its log.

    The file is not the whole database: committed writes can sit in
    `<file>-wal` until a checkpoint, and the log is found by the main
    file's name. Moving the main file alone would leave those writes
    behind under the old name. So the log is folded in first, and any
    side files that remain travel with it. Either step alone keeps the
    writes (measured: tests/test_sqlite_silo.py fails only with both
    removed); the checkpoint is what leaves no log for a reader still
    holding the old name to read from.
    """
    import sqlite3

    connection = sqlite3.connect(f"file:{source}?mode=rw", uri=True)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    source.replace(target)
    for suffix in ("-wal", "-shm"):
        side = source.with_name(source.name + suffix)
        if side.exists():
            side.replace(target.with_name(target.name + suffix))


def restore_leftovers(world) -> dict[str, str]:
    """Undo any outage a previous run of this world left behind.

    A world stopped cleanly restores its outages itself; one that was
    killed, or crashed while restoring, cannot. Whether a source is out
    lives in that process's memory, so the next run would otherwise find
    the reader locked out or a share still moved aside, and `restore`
    would answer "not out". So a resumed world restores every source
    once before anything reads or writes it; each restore is harmless
    when there is nothing to undo.
    """
    done = {}
    for name, silo in sorted(world.silos.items()):
        if silo.kind in ("postgresql", "mariadb", "filedrop", "sqlite"):
            done[name] = restore(silo, world.pack.silos[name].database)
    return done

# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section
# whenever something genuinely open, deferred, or rejected comes up here.
# =============================================================================
#
# RESOLVED (20 October, review): an outage left by a killed run could not be
# ended, because whether a source is out lived only in that process. Restore
# now reads the disk for files and folders, and a resumed world calls
# restore_leftovers() before anything else runs.
#
# KNOWN: a reader that already has a SQLite file or a CSV open keeps reading
# it through the outage; only new opens fail. That is also what happens when
# a real share is unmounted under an open file on most systems, so it is left.
#
# DEFERRED: slow responses and transient 5xx on demand (REAL_SOURCES R3) are
# realism options, step 2 of BLOCKING item 12.
