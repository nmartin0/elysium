"""
sqlite.py  (a silo that is a file, because that is what it really is)

The awkward one, and the honest one. A SQLite silo has no port, no
process, and nothing to start. Every method below that does nothing is
doing nothing for a real reason, not as a placeholder.

Why it belongs here at all. Small businesses run a great deal of
SQLite without ever calling it that: it is embedded in desktop
point-of-sale software, in line-of-business applications, in the
accounting package on the back-office PC. The business does not have
"a SQLite database" -- it has an application, and the application's
file is what a data platform ends up pointing at. Foundry lists SQLite
among its relational connectors for exactly this reason.

It was dropped from an earlier version of this design on the grounds
that it cannot listen on a port. That is true and it was the wrong
conclusion: the fix is not to exclude the technology, it is to stop
assuming every silo is reached the same way. A consumer of a SQLite
silo really does open a file, and `connection()` says so.

WAL is SET at creation, and verified rather than assumed: with the
database in WAL mode, a reader is not blocked while a writer holds an
open transaction, and sees the commit immediately afterwards. Journal
mode is a persistent property of the file, so a consumer picks it up
with no configuration. In the default rollback-journal mode a live
consumer would intermittently block on the simulator's own writes, and
that contention would be an artefact of the tool rather than a
property of the business being simulated.
"""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

from simulator.silo import ConnectionDescriptor, Silo, SiloError
from simulator.silos.connection import SharedConnection

#: The first sixteen bytes of every SQLite database file. Checking for
#: it is the only way to tell a real database from a zero-byte file,
#: because SQLite treats a zero-length file as a valid empty DATABASE
#: -- measured: opening one and querying sqlite_master succeeds and
#: returns 0. A silo this module created always carries the header,
#: since setting the journal mode writes it.
SQLITE_MAGIC = b"SQLite format 3\x00"

#: What a terminated silo's file is renamed to. Recoverable on purpose:
#: a real outage here is usually a backup script or a sync client
#: moving the file, not a deletion, and a test that wants the file back
#: can move it back.
TERMINATED_SUFFIX = ".gone"

#: Where the file is while it is out (simulator/outages.py).
OFFLINE_SUFFIX = ".offline"


class SqliteSilo(Silo):
    """One silo, backed by a single SQLite file."""

    kind: ClassVar[str] = "sqlite"
    #: No port, ever. This is the flag's whole reason for existing.
    requires_port: ClassVar[bool] = False

    def __init__(self, name: str, data_dir: Path, filename: str | None = None,
                 database: str | None = None) -> None:
        super().__init__(name, data_dir)
        #: The database a pack declares for it -- the file IS that
        #: database, named after it, as a desktop application names its
        #: company file. None for a silo holding no schema.
        self.database = database
        #: Named after its database, else after the silo, so a directory
        #: of them reads as a list of systems rather than of files.
        self.filename = filename or f"{database or name}.db"
        #: True while an outage has the file moved aside.
        self.offline = False
        #: One connection held across a block, as the server silos hold
        #: theirs (connection.py): a tick's writes commit together.
        self._connections = SharedConnection(open=self._open)

    @property
    def home(self) -> Path:
        """Where consumers are told the file is."""
        return self.data_dir / self.filename

    @property
    def path(self) -> Path:
        """Where the file really is now: the home, or -- during an outage
        (simulator/outages.py) -- moved aside, where the business's own
        application goes on writing to it, as a desktop application keeps
        its database while the share a reader used has gone."""
        return self.home.with_name(self.filename + OFFLINE_SUFFIX) if self.offline else self.home

    # -- lifecycle ---------------------------------------------------

    def create(self) -> None:
        if self.path.exists():
            raise SiloError(
                f"{self.name}: {self.path} already exists; remove the world's "
                f"directory to rebuild it"
            )
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # The one place creation is the intent, so a bare path is
        # correct here -- everywhere else opens with mode=rw so that a
        # missing file fails instead of silently reappearing.
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.commit()
        finally:
            connection.close()

    def start(self) -> None:
        """Nothing to start. A file is openable or it is not.

        Not a stub: this is what starting a file-based silo means, and
        the Silo contract allows it precisely so that this can be
        honest rather than fake a daemon.
        """
        return None

    def stop(self) -> None:
        """Nothing to stop. See start()."""
        return None

    def is_reachable(self) -> bool:
        """Whether the file exists and opens as a database.

        Existence alone is not enough, and the difference is not
        academic: a zero-byte file is what gets left behind when
        something calls sqlite3.connect() on a path that is not there,
        since a bare connect creates rather than fails. A silo that has
        been terminated and then touched by a careless reader would
        pass an exists() check forever after.
        """
        if not self.home.exists():
            return False
        # The header check comes first and is not redundant with the
        # query below. A zero-byte file is a valid empty database as far
        # as SQLite is concerned -- querying sqlite_master on one
        # succeeds -- so opening it proves nothing. The header is what
        # distinguishes a database from a file something else created.
        try:
            with self.home.open("rb") as handle:
                if handle.read(len(SQLITE_MAGIC)) != SQLITE_MAGIC:
                    return False
        except OSError:
            return False
        try:
            connection = sqlite3.connect(f"file:{self.home}?mode=rw", uri=True)
        except sqlite3.Error:
            return False
        try:
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
            return True
        except sqlite3.DatabaseError:
            return False
        finally:
            connection.close()

    def connection(self, database: str | None = None) -> ConnectionDescriptor:
        """A path, not a host and port. That is the point. No account
        either: whoever can read the file reads every table."""
        if database is not None and database != self.database:
            _refuse_database(self.name, self.kind, database)
        details: dict[str, Any] = {"path": str(self.home)}
        if self.database is not None:
            details["database"] = self.database
        return ConnectionDescriptor(kind=self.kind, details=details)

    def driver_errors(self) -> tuple[type[Exception], ...]:
        # OSError as well as sqlite3.Error: a file-based silo fails at
        # the filesystem before it fails at the database.
        return (sqlite3.Error, OSError)

    def terminate(self) -> None:
        """Move the file aside, so the silo abruptly stops answering.

        The file-based equivalent of killing a server, and a real
        failure rather than an invented one: a backup script, a cloud
        sync client or somebody tidying a shared drive is how a desktop
        application's database actually goes missing.

        Renamed rather than deleted so the condition is recoverable and
        so a test can put it back.
        """
        if self.path.exists():
            self.path.replace(self.path.with_suffix(self.path.suffix + TERMINATED_SUFFIX))

    def session(self, database: str | None = None):
        """Hold one connection open for a block. See connection.py."""
        return self._connections.session(self._checked(database))

    def connect(self, database: str | None = None, *, autocommit: bool = False):
        """A connection for one piece of work, inside a session's if one is
        open (connection.py). The same shape as the server silos', so
        relational.py and drift.py drive this file as they drive them.

        `mode=rw` rather than a bare path, because sqlite3.connect()
        creates a missing database instead of failing -- which turns
        "the silo is gone" into "here is an empty database" silently,
        and defeats any check based on the file's existence.
        """
        return self._connections.use(self._checked(database), autocommit=autocommit)

    def _checked(self, database: str | None) -> str:
        """The one database this file is, by whatever name it was asked for."""
        if database is not None and self.database is not None and database != self.database:
            raise SiloError(f"silo {self.name!r} is the {self.database!r} database; it holds no "
                            f"database called {database!r}")
        return self.database or self.name

    @contextmanager
    def _open(self, database: str, *, autocommit: bool) -> Iterator["SqliteConnection"]:
        try:
            # `autocommit`, Python 3.12's PEP 249 control: False keeps a
            # transaction open always, DDL included, so a retype's four
            # statements (dialect.py) commit or roll back as one, as
            # SQLite's documented procedure asks. sqlite3's older
            # default opened one only before INSERT and the like.
            raw = sqlite3.connect(f"file:{self.path}?mode=rw", uri=True, timeout=10.0,
                                  autocommit=autocommit)
        except sqlite3.OperationalError as error:
            raise SiloError(f"{self.name}: cannot open {self.path}: {error}") from error
        raw.row_factory = sqlite3.Row
        try:
            yield SqliteConnection(raw)
        finally:
            raw.close()


def as_written(value: Any) -> Any:
    """A value as an ordinary application's database layer binds it.

    The owner's choice (24 October): the simulated business writes as
    typical software does, and SQLite does the rest (dialect.py,
    SqliteDialect). Django's SQLite backend is the model:
      - a timestamp as ISO text, "YYYY-MM-DD HH:MM:SS[.ffffff]", made
        naive in UTC -- SQLite has no date type; its documentation's
        first option is "TEXT as ISO8601 strings";
      - a date as "YYYY-MM-DD";
      - a Decimal as its text, which a DECIMAL column's NUMERIC affinity
        then stores "as INTEGER or REAL" -- so 19.99 arrives as a double
        and 20.00 as the integer 20, which is what a consumer meets;
      - a boolean as 1 or 0, which sqlite3 does by itself.
    Explicit, not sqlite3's default adapters, which Python 3.12
    deprecated for dates.
    """
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


class SqliteConnection:
    """sqlite3's connection, with the PEP 249 shape the rest of the
    simulator uses: cursors that work in a `with` block, as psycopg's
    and PyMySQL's do, and values bound as an application binds them."""

    def __init__(self, raw: sqlite3.Connection) -> None:
        self.raw = raw

    def cursor(self) -> "SqliteCursor":
        return SqliteCursor(self.raw.cursor())

    def execute(self, statement: str, parameters: Sequence[Any] = ()) -> sqlite3.Cursor:
        """Straight through, for the few callers -- and tests -- that use
        sqlite3's own connection-level execute."""
        return self.raw.execute(statement, [as_written(v) for v in parameters])

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        self.raw.close()


class SqliteCursor:
    def __init__(self, raw: sqlite3.Cursor) -> None:
        self.raw = raw

    def __enter__(self) -> "SqliteCursor":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.raw.close()

    def execute(self, statement: str, parameters: Sequence[Any] = ()) -> "SqliteCursor":
        self.raw.execute(statement, [as_written(v) for v in parameters])
        return self

    def executemany(self, statement: str, rows: Sequence[Sequence[Any]]) -> "SqliteCursor":
        self.raw.executemany(statement, [[as_written(v) for v in row] for row in rows])
        return self

    # Tuples, as psycopg's and PyMySQL's cursors give: relational.py and
    # its callers compare rows with tuples, and a sqlite3.Row equals none.
    def fetchone(self) -> Any:
        row = self.raw.fetchone()
        return None if row is None else tuple(row)

    def fetchall(self) -> list[Any]:
        return [tuple(row) for row in self.raw.fetchall()]

    @property
    def rowcount(self) -> int:
        return self.raw.rowcount


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section
# whenever something genuinely open, deferred, or rejected comes up here.
# =============================================================================
#
# RESOLVED (kept for history): SQLite was dropped from an earlier version of
# this design because it cannot listen on a port, and brought back once the
# conclusion was recognised as the wrong one. The requirement was that a
# consumer reach the silos directly; it was never that every silo be a server.
# Small businesses genuinely run SQLite inside desktop applications, and
# Foundry lists it as a relational connector.
#
# RESOLVED: is_reachable() checks the sixteen-byte file header, not just that
# the file opens. Opening is not enough, and this was found by a test that
# failed: SQLite treats a zero-length file as a valid empty database, so
# querying sqlite_master on the artefact a careless sqlite3.connect() leaves
# behind succeeds and returns 0. Measured directly -- zero bytes, query
# returns (0,) -- while a database this module created is 4096 bytes and
# begins "SQLite format 3\x00". Existence alone was the first version and was
# worse still; the same failure mode was measured defeating a health check in
# another system while researching this.
#
# RESOLVED: terminate() renames rather than deletes. A deletion is not the
# realistic failure -- a backup script or sync client moving the file is -- and
# a recoverable condition is more useful to test against.
#
# DEFERRED (known, intentional, not yet built): no support for a silo made of
# several SQLite files, which is how some desktop applications actually store
# things (a company file plus attachments plus an index). One file covers every
# case a pack has needed; the extension is a list of paths in the descriptor.


def _refuse_database(name: str, kind: str, database: str | None) -> None:
    """A sqlite silo holds no databases.

    Refusing rather than ignoring: a pack declaring one would otherwise
    have written something with no effect, and the author would have no
    way to find out.
    """
    if database is not None:
        raise SiloError(
            f"silo {name!r} is a {kind!r} silo and holds no database called {database!r}"
        )
