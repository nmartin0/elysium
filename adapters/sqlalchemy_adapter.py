"""Reading a customer's database through SQLAlchemy Core.

WHY CORE AND NOT THE ORM. The ORM maps classes to tables; Elysium
already has an ontology that does that job, and a second mapping layer
would mean two descriptions of the same schema disagreeing. Core is
the SQL expression toolkit underneath it -- "many applications are
built strictly on the Core, using the SQL expression system to provide
succinct and exact control over database interactions".

WHY CORE AND NOT A NATIVE DRIVER. Our queries are simple -- no joins,
no subqueries, no window functions -- so almost everything that
differs between engines is the four things Core's dialects handle:

    placeholder style       %s / ? / :1
    identifier quoting      "x" / [x] / "X"
    row-limit syntax        LIMIT n / TOP n / FETCH FIRST
    schema introspection    information_schema / PRAGMA / sys.columns

The last is the one that decided it. The schema-drift work needs to
know what a source says its column types are, and hand-writing that
per database is real work Core's Inspector does uniformly.

AIRFLOW IS THE PRECEDENT: SQLAlchemy underneath, with per-database
overrides where they matter.

THE SQLITE ADAPTER STAYS AS IT IS. It serves Elysium's OWN storage on
the stdlib module, it works, and churning it would buy nothing. Two
mechanisms is the accepted cost, and they divide on a real line:
embedded fixture storage against a customer's real database.

IDENTIFIERS ARE NEVER INTERPOLATED. Table and column names come from a
deployment's configuration -- not from a user -- but a configuration
is still text somebody typed, and `sqlalchemy.text()` with a
hand-built name would put it straight into the SQL. Every name here
goes through `Table`/`Column` objects, which the dialect quotes.
"""

import logging
import threading
from contextlib import contextmanager
from datetime import UTC
from typing import Any

from sqlalchemy import (
    Column,
    MetaData,
    Table,
    and_,
    create_engine,
    event,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import NoSuchTableError, SQLAlchemyError

from core.ontology.interface import (
    ExternalReadAdapter,
    RowsHidden,
    SourceBehind,
    StorageUnavailable,
    TableNotFound,
)
from core.ontology.schema import get_column_for_field

logger = logging.getLogger(__name__)

# HOW LONG ONE QUERY MAY RUN, in seconds.
#
# The same default the SQLite path uses, and the same reasoning: there
# is ONE worker process, so a hung query does not slow the service --
# it stops it.
#
# SERVER-SIDE, NOT CLIENT-SIDE. PostgreSQL's `statement_timeout` makes
# the SERVER abandon the query; a client-side timeout only stops
# waiting, leaving the database still working on something nobody will
# read.
DEFAULT_QUERY_TIMEOUT_SECONDS = 30
#: Under MySQL and MariaDB's default wait_timeout of eight hours.
MYSQL_POOL_RECYCLE_SECONDS = 3600

# ONE SNAPSHOT FOR A WHOLE SYNC OF A SILO (R4), by dialect: the isolation
# level under which every read in one transaction sees the database as
# of its first read -- WITHOUT blocking the source's own writers, which
# is the condition for doing this to somebody else's production
# database at all. pg_dump's guarantee, "consistent backups even if the
# database is being used concurrently", is this mechanism.
#
#   postgresql   REPEATABLE READ   MVCC snapshot at the first statement
#   mysql        REPEATABLE READ   InnoDB consistent read, ditto
#   oracle       SERIALIZABLE      transaction-level read consistency
#
# THE COST, STATED: the transaction stays open while the silo's tables
# are read and mirrored -- minutes, on a large source. PostgreSQL cannot
# vacuum rows the snapshot might still see until it ends, the same cost
# pg_dump imposes for the same guarantee. A sync is short and
# periodic; a source that cannot afford it can be read by a role whose
# default isolation is lower, and will be read table by table.
#
# ABSENT DIALECTS GET TABLE-BY-TABLE READS, said so per run. SQL Server's
# non-blocking level (SNAPSHOT) needs a database option the source may
# not have set, and SQLite holds a lock that BLOCKS the source's writers
# for as long as the sync reads, unless the file is in WAL mode -- which
# a read-only connection cannot check.
SNAPSHOT_ISOLATION = {
    "postgresql": "REPEATABLE READ",
    "mysql": "REPEATABLE READ",
    "mariadb": "REPEATABLE READ",
    "oracle": "SERIALIZABLE",
}

def _type_text(column_type) -> str:
    """A column's type as the source declared it, time zone included.

    FOUND AGAINST A REAL POSTGRESQL (19 October): `str()` of
    TIMESTAMP(timezone=True) is "TIMESTAMP" -- the same text as a column
    without one. So the change the drift report was built to catch first,
    timestamptz -> timestamp losing the offset (core/mirror/
    iceberg_sync.py), compared equal and was never reported; and a
    declaration copied from this report would be the wrong one, which
    quarantined every row of a simulated till. The zone is added back in
    the SQL standard's own words, which PostgreSQL and Oracle both use.
    """
    text = str(column_type)
    if getattr(column_type, "timezone", False) and "TIME ZONE" not in text.upper():
        text += " WITH TIME ZONE"
    return text



def _age(interval) -> str:
    """An interval as a person says it: 40 s, 12 min, 3 h 5 min."""
    seconds = int(interval.total_seconds()) if interval is not None else 0
    if seconds < 120:
        return f"{seconds} s"
    if seconds < 7200:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60} min"

class SQLAlchemyReadAdapter(ExternalReadAdapter):
    """Reads objects from a database SQLAlchemy has a dialect for."""

    # WHICH FILTERS REACH THE DATABASE. The mediator applies anything not
    # listed here in Python afterwards, so an operator missing from this
    # set is slower rather than wrong.
    #
    # `contains` IS HERE AND `relative_date` IS NOT: LIKE is expressible
    # in Core, and a relative date needs today's date resolved first --
    # which the mediator does before calling, turning it into a
    # date_range (core/filters.py, resolved). This comment said so for
    # months before anything did; see that function for what it cost.
    pushable_operators = frozenset({
        "equals", "in", "not_in", "range", "date_range", "contains",
    })

    def __init__(self, connection: dict):
        # `url` IS THE WHOLE CONNECTION, which is how SQLAlchemy names
        # a database: "postgresql+psycopg://user@host/db". Keeping the
        # deployment's config in that shape rather than inventing
        # host/port/user keys means a deployment can reach anything
        # SQLAlchemy can, without this file learning about each.
        self._url = connection["url"]
        self._timeout_seconds = connection.get(
            "query_timeout_seconds", DEFAULT_QUERY_TIMEOUT_SECONDS,
        )
        self._mysql_family = make_url(self._url).get_backend_name() in ("mysql", "mariadb")
        self._engine = create_engine(
            self._url,
            # POOLED, because a connection per query to a network
            # database is a handshake per query. SQLAlchemy pools by
            # default; naming it here is documentation rather than
            # configuration.
            pool_pre_ping=True,
            # MYSQL AND MARIADB CLOSE AN IDLE CONNECTION after
            # wait_timeout, eight hours by default; SQLAlchemy's advice
            # is to recycle pooled connections sooner than that.
            **({"pool_recycle": MYSQL_POOL_RECYCLE_SECONDS} if self._mysql_family else {}),
            connect_args=self._connect_args(),
        )
        if self._mysql_family:
            event.listen(self._engine, "connect", self._on_mysql_connect)
        self._metadata = MetaData()
        # THE CONNECTION A CONSISTENT READ IS HOLDING, per thread: the
        # sync reads on one thread, and anything else that shares this
        # adapter must never find itself inside the sync's transaction.
        self._pinned = threading.local()

    @contextmanager
    def consistent_read(self):
        """Every read inside this block sees ONE snapshot of the source
        (R4). Yields True when the dialect provides one, False when reads
        fall back to table by table -- the caller says which happened.

        WITHOUT IT, a sync read each table at a different moment: an
        order written between the customers read and the transactions
        read arrived with a customer the mirror did not have. Inside it,
        both reads see the same instant.

        A FAILED READ DOES NOT POISON THE REST. PostgreSQL aborts a
        whole transaction on any error, so each read inside runs in a
        SAVEPOINT and only that read is rolled back -- the snapshot,
        fixed at the first statement, is kept.
        """
        isolation = SNAPSHOT_ISOLATION.get(self._engine.dialect.name)
        if isolation is None or getattr(self._pinned, "conn", None) is not None:
            yield False
            return
        try:
            conn = self._engine.connect().execution_options(isolation_level=isolation)
        except SQLAlchemyError as e:
            raise StorageUnavailable(f"{self._describe_source()}: {type(e).__name__}: {e}") from e
        try:
            with conn.begin():
                self._pinned.conn = conn
                try:
                    yield True
                finally:
                    self._pinned.conn = None
        finally:
            conn.close()

    def _connect_args(self) -> dict:
        """Per-dialect connection settings, chiefly the timeout.

        THE ONE PLACE THIS FILE KNOWS ABOUT A SPECIFIC DATABASE, and
        it says so (with _on_mysql_connect, for the MySQL family).
        `statement_timeout` is PostgreSQL's spelling; MySQL has
        `max_execution_time`, MariaDB `max_statement_time`, and Oracle
        its own. A dialect Elysium has not met gets no timeout rather
        than a wrong one, and that gap is visible here rather than
        buried.
        """
        if self._url.startswith("postgresql"):
            # READ ONLY AS WELL (19 October): INSTALL.md asks for a
            # SELECT-only account, and this is the second lock, for the
            # account that was given more. Every transaction this
            # adapter opens refuses to write.
            # THE URL'S OWN OPTIONS KEPT, AND FIRST (21 October). These
            # connect_args replaced a URL's `?options=` outright, so
            # `-c search_path=reporting` was dropped without a word and the
            # wrong schema read. Theirs first, ours after: of two settings
            # of one parameter the later wins, so a URL cannot switch
            # read-only off.
            theirs = make_url(self._url).query.get("options") or ""
            if isinstance(theirs, tuple):
                theirs = " ".join(theirs)
            return {
                "options": (f"{theirs} " if theirs else "")
                + (f"-c statement_timeout={self._timeout_seconds * 1000} "
                   f"-c default_transaction_read_only=on"),
            }
        if self._mysql_family:
            # A SERVER THAT STOPS SENDING, caught by the driver: how long
            # one read from the socket may wait. Not the statement's
            # length -- a long streamed copy reads continually -- which is
            # why it can stand in while the stream lifts the server's limit.
            return {"read_timeout": max(60, int(self._timeout_seconds * 2))}
        return {}

    def _on_mysql_connect(self, dbapi_connection, _record) -> None:
        """The MySQL family's equivalents, set on each new connection.

        AT CONNECT, NOT IN THE URL: the time limit is spelled differently
        by the two servers SQLAlchemy treats as one dialect -- MariaDB's
        `max_statement_time` in seconds, MySQL's `max_execution_time` in
        milliseconds and for SELECT only -- and which one answered is
        known only once it has. Setting the wrong one is an error.

        READ ONLY as on PostgreSQL. The isolation level a consistent read
        sets later is a separate setting and leaves this one alone.
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SELECT VERSION()")
            self._mariadb = "mariadb" in str(cursor.fetchone()[0]).lower()
            cursor.execute(self._time_limit_sql(self._timeout_seconds))
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
        finally:
            cursor.close()

    def _table(self, table_name: str, columns: list[str]) -> Table:
        """A Table object for the columns being asked about.

        BUILT FROM THE ONTOLOGY'S NAMES, not reflected from the
        database. Reflection would make every query depend on the
        source's current schema being readable, and turn a missing
        column into a connection-time failure rather than the drift
        report this project already has.
        """
        key = (table_name, tuple(sorted(columns)))
        cached = self._metadata.tables.get(str(key))
        if cached is not None:
            return cached
        return Table(
            table_name, MetaData(),
            *(Column(name) for name in columns),
        )

    def _clause_for(self, table: Table, condition) -> Any:
        """One filter, as a Core expression."""
        column = table.c[condition.field]
        operator, value = condition.operator, condition.value

        if operator == "equals":
            return column == value
        if operator == "in":
            return column.in_(list(value))
        if operator == "not_in":
            return column.notin_(list(value))
        if operator == "contains":
            # WILDCARDS IN THE BOUND VALUE, not the pattern, so a value
            # containing % or _ cannot widen its own match. The same
            # rule the SQLite adapter states.
            escaped = str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            return column.like(f"%{escaped}%", escape="\\")
        if operator in ("range", "date_range"):
            low = value.get("min") if operator == "range" else value.get("start")
            high = value.get("max") if operator == "range" else value.get("end")
            bounds = []
            if low is not None:
                bounds.append(column >= low)
            if high is not None:
                bounds.append(column <= high)
            if not bounds:
                # BOTH ABSENT MATCHES NOTHING AND REPORTS NO ERROR,
                # which the SQLite adapter calls the hardest kind of
                # wrong answer. Refuse instead.
                raise ValueError(
                    f"{condition.field}: a {operator} needs at least one bound"
                )
            return and_(*bounds)
        raise ValueError(f"cannot express {operator!r} in SQL")

    def _execute(self, statement) -> list[dict]:
        """Runs one statement, or says the storage is unavailable."""
        pinned = getattr(self._pinned, "conn", None)
        try:
            if pinned is not None:
                # Inside a consistent read: the held snapshot, and a
                # savepoint so a failure costs this read only.
                with pinned.begin_nested():
                    return [dict(row) for row in pinned.execute(statement).mappings()]
            with self._engine.connect() as conn:
                return [dict(row) for row in conn.execute(statement).mappings()]
        except SQLAlchemyError as e:
            # ONE TYPE FOR EVERY WAY A SOURCE CAN BE UNREACHABLE, which
            # is what the mediator's degrade-rather-than-die path
            # expects. The original is chained so the cause survives.
            raise StorageUnavailable(
                f"{self._describe_source()}: {type(e).__name__}: {e}"
            ) from e

    def _describe_source(self) -> str:
        """The connection, WITHOUT its password.

        A URL carries credentials, and an error message is the most
        likely place for one to end up in a log somebody pastes.
        """
        from sqlalchemy.engine import make_url

        return str(make_url(self._url).render_as_string(hide_password=True))

    # ---- the read interface ------------------------------------------

    def find_ids(self, object_type: str, conditions: list, type_config: dict,
                 limit: int | None = None) -> list[Any]:
        storage = type_config["storage"]
        id_column = storage["id_column"]
        columns = {id_column} | {c.field for c in conditions}
        table = self._table(storage["table"], sorted(columns))

        statement = select(table.c[id_column])
        for condition in conditions:
            statement = statement.where(self._clause_for(table, condition))
        if limit is not None and limit > 0:
            statement = statement.limit(limit)

        return [row[id_column] for row in self._execute(statement)]

    def find_ids_matching_text(self, object_type: str, columns: list[str],
                               query_text: str, type_config: dict,
                               limit: int | None = None) -> list[Any]:
        storage = type_config["storage"]
        id_column = storage["id_column"]
        table = self._table(storage["table"], sorted({id_column, *columns}))

        escaped = query_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        matches = [
            table.c[column].like(f"%{escaped}%", escape="\\") for column in columns
        ]
        if not matches:
            return []

        from sqlalchemy import or_

        statement = select(table.c[id_column]).where(or_(*matches))
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return [row[id_column] for row in self._execute(statement)]

    def get_raw_field(self, object_type: str, object_id: Any, field_name: str,
                      type_config: dict) -> Any:
        storage = type_config["storage"]
        id_column = storage["id_column"]
        column = get_column_for_field(type_config, field_name)
        table = self._table(storage["table"], sorted({id_column, column}))

        rows = self._execute(
            select(table.c[column]).where(table.c[id_column] == object_id).limit(1),
        )
        return rows[0][column] if rows else None

    def read_fields_for_ids(self, table_name: str, id_column: str,
                            object_ids: list, columns: list[str],
                            type_config: dict) -> list[dict]:
        if not object_ids:
            # ANSWERED WITHOUT ASKING, which saves a round trip rather
            # than preventing an error: SQLAlchemy renders an empty
            # `IN` through its own postcompile mechanism and produces
            # a condition matching nothing, so removing this is slower
            # and not wrong. Verified, after a control on it failed to
            # fire.
            return []
        table = self._table(table_name, sorted({id_column, *columns}))
        statement = select(
            *(table.c[name] for name in sorted({id_column, *columns}))
        ).where(table.c[id_column].in_(list(object_ids)))
        return self._execute(statement)

    def read_all_rows(self, table_name: str, columns: list[str],
                      type_config: dict) -> list[dict]:
        table = self._table(table_name, sorted(columns))
        return self._execute(select(*(table.c[name] for name in sorted(columns))))

    def iter_all_rows(self, table_name: str, columns: list[str], type_config: dict,
                      batch_size: int = 50_000):
        """read_all_rows, a batch at a time (R5), through a SERVER-SIDE
        cursor (`stream_results`), so neither this process nor the driver
        holds the whole table. Inside a consistent read (R4) it streams
        from the held snapshot, in a savepoint like every other read."""
        table = self._table(table_name, sorted(columns))
        yield from self._stream(select(*(table.c[name] for name in sorted(columns))), batch_size)

    def iter_rows_since(self, table_name: str, columns: list[str], cursor_column: str,
                        since, batch_size: int = 50_000):
        """iter_all_rows WHERE cursor >= since (R2), the mark bound as a
        parameter of the type it was read as -- never interpolated."""
        table = self._table(table_name, sorted(set(columns) | {cursor_column}))
        statement = select(*(table.c[name] for name in sorted(columns))).where(
            table.c[cursor_column] >= since)
        yield from self._stream(statement, batch_size)

    def _time_limit_sql(self, seconds: float) -> str:
        """MariaDB's spelling, in seconds, or MySQL's, in milliseconds; 0 is
        no limit on both."""
        if getattr(self, "_mariadb", True):
            return f"SET SESSION max_statement_time = {float(seconds)}"
        return f"SET SESSION max_execution_time = {int(seconds * 1000)}"

    @contextmanager
    def _no_time_limit_while_streaming(self, conn):
        """A STREAMED READ IS ONE STATEMENT on MariaDB and MySQL, and their
        limits run while the sync is still working through its batches --
        so a table taking longer than the limit to COPY failed partway
        (found in review, 19 October: 80,000 of 200,000 rows on a real
        MariaDB, error 1969). PostgreSQL is unaffected: each FETCH from its
        server-side cursor is a statement of its own. So the limit is lifted
        for the stream and restored after; a server that stops sending is
        still caught, by the driver's read timeout (`_connect_args`)."""
        if not self._mysql_family:
            yield
            return
        conn.exec_driver_sql(self._time_limit_sql(0))
        try:
            yield
        finally:
            conn.exec_driver_sql(self._time_limit_sql(self._timeout_seconds))

    def _stream(self, statement, batch_size: int):
        # ON THE STATEMENT, NOT THE CONNECTION: Connection.execution_options
        # changes the connection IN PLACE, and on the held snapshot that
        # put the savepoint's own RELEASE through a server-side cursor --
        # "syntax error at or near RELEASE", caught by the test.
        statement = statement.execution_options(stream_results=True)
        pinned = getattr(self._pinned, "conn", None)
        try:
            if pinned is not None:
                with pinned.begin_nested(), self._no_time_limit_while_streaming(pinned):
                    result = pinned.execute(statement)
                    for partition in result.mappings().partitions(batch_size):
                        yield [dict(row) for row in partition]
                    result.close()
                return
            with self._engine.connect() as conn, self._no_time_limit_while_streaming(conn):
                result = conn.execute(statement)
                for partition in result.mappings().partitions(batch_size):
                    yield [dict(row) for row in partition]
                result.close()
        except SQLAlchemyError as e:
            raise StorageUnavailable(
                f"{self._describe_source()}: {type(e).__name__}: {e}") from e

    def resolve_reverse_link(self, object_id: Any, field_config: dict,
                             target_id_column: str) -> list:
        return self.resolve_reverse_links_batch(
            [object_id], field_config, target_id_column,
        ).get(object_id, [])

    def resolve_reverse_links_batch(self, object_ids: list, field_config: dict,
                                    target_id_column: str) -> dict:
        if not object_ids:
            # As above: a saved round trip, not a correctness guard.
            return {}
        table_name = field_config["target_table"]
        foreign_key = field_config["target_column"]
        table = self._table(table_name, sorted({foreign_key, target_id_column}))

        rows = self._execute(
            select(table.c[foreign_key], table.c[target_id_column])
            .where(table.c[foreign_key].in_(list(object_ids))),
        )
        # EVERY REQUESTED ID GETS A KEY, including the ones with no
        # links. A caller that has to distinguish "no links" from "not
        # asked about" would otherwise need the input list too.
        grouped: dict = {object_id: [] for object_id in object_ids}
        for row in rows:
            grouped.setdefault(row[foreign_key], []).append(row[target_id_column])
        return grouped

    def source_column_types(self, table_name: str) -> dict[str, str]:
        """Verbatim column types, via Core's Inspector.

        THE SAME CALL `columns_present` MAKES, keeping the type it was
        already discarding. Uniform across every dialect SQLAlchemy
        has -- which is the reason this adapter is on Core at all.
        """
        try:
            return {
                column["name"]: _type_text(column["type"])
                for column in inspect(self._engine).get_columns(table_name)
            }
        except SQLAlchemyError as e:
            # CANNOT SAY, not "no columns". `columns_present` RAISES
            # here because a missing table must not read as an empty
            # one; this is only used for drift reporting, where a
            # silent skip beats a false alarm on every column.
            logger.warning(
                "%s: could not read column types of %r: %s",
                self._describe_source(), table_name, e,
            )
            return {}

    def rows_hidden_from_this_reader(self, table_name: str) -> "str | None":
        """PostgreSQL's row-level security, as it applies to this account.

        It applies when the table has it ON and the account is neither a
        superuser nor BYPASSRLS -- and, for the table's owner, only when
        it is FORCED (PostgreSQL exempts owners otherwise). Other engines
        have no equivalent this can ask about, and say nothing.
        """
        if self._engine.dialect.name != "postgresql":
            return None
        query = text(
            "SELECT c.relrowsecurity, c.relforcerowsecurity, "
            "       pg_get_userbyid(c.relowner) = current_user AS owns, "
            "       r.rolsuper OR r.rolbypassrls AS exempt, "
            "       (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies "
            "FROM pg_class c, pg_roles r "
            # QUOTED, as the adapter's own queries quote it: to_regclass
            # folds a bare name to lower case, so "Orders" was never found
            # (found in review, 19 October).
            "WHERE c.oid = to_regclass(quote_ident(:table)) AND r.rolname = current_user")
        try:
            with self._engine.connect() as conn:
                row = conn.execute(query, {"table": table_name}).mappings().first()
        except SQLAlchemyError as e:
            logger.warning("%s: could not check row-level security on %r: %s",
                           self._describe_source(), table_name, e)
            return None
        if row is None or not row["relrowsecurity"] or row["exempt"]:
            return None
        if row["owns"] and not row["relforcerowsecurity"]:
            return None
        policies = row["policies"]
        return RowsHidden(f"{table_name} has PostgreSQL row-level security switched on, and the account "
                f"Elysium syncs with is subject to it -- "
                + ("no policy is defined, so PostgreSQL returns NO rows to it, without an error"
                   if not policies else
                   f"{policies} polic{'y' if policies == 1 else 'ies'} decide which rows it sees, "
                   f"and rows they hide are not copied")
                + ". Elysium decides who sees which rows on its own copy, so the copy must be "
                  "complete: grant the account BYPASSRLS (ALTER ROLE <account> BYPASSRLS), or a "
                  "policy that lets it read every row.", every_row=not policies)

    def columns_present(self, table_name: str) -> set[str]:
        """What the source actually has, via Core's Inspector.

        THE REASON THIS ADAPTER IS ON SQLALCHEMY. Hand-writing this
        means information_schema on PostgreSQL, PRAGMA on SQLite,
        ALL_TAB_COLUMNS on Oracle and sys.columns on SQL Server --
        four dialects of the same question. The Inspector answers it
        once.
        """
        try:
            return {
                column["name"]
                for column in inspect(self._engine).get_columns(table_name)
            }
        except NoSuchTableError as e:
            raise TableNotFound(
                f"{self._describe_source()}: there is no table {table_name!r}") from e
        except SQLAlchemyError as e:
            raise StorageUnavailable(
                f"{self._describe_source()}: could not read the columns of "
                f"{table_name!r}: {e}"
            ) from e

    def source_behind(self) -> "SourceBehind | None":
        """A PostgreSQL standby whose replay has fallen behind what it has
        received: the commit time of the last change it applied.

        RECEIVED AGAINST REPLAYED, NOT THE CLOCK. `now() -
        pg_last_xact_replay_timestamp()` is the usual measure, and it
        reads as lag whenever the primary is merely idle -- it "might lead
        to wrong conclusions that standby is lagging" (postgres.ai). When
        everything received has been replayed, the standby is as current
        as it can know, and nothing is claimed. WHAT THIS CANNOT SEE: WAL
        not yet received -- "the replica doesn't know the current
        transaction position of the primary" (Adjust's engineering blog,
        which measures on the primary instead, through
        pg_stat_replication). Elysium reaches only the replica.

        PESSIMISTIC, NEVER LATE: WAL that holds no transaction -- a
        checkpoint, a segment switch -- also makes received differ from
        replayed, and the copy is then dated from the last commit, earlier
        than it need be (found in review, 21 October). Earlier is the safe
        side: freshness reads older and more of Elysium's writes are
        overlaid; nothing committed is missed.

        IN UTC, because the overlay compares this as TEXT with the write
        log's UTC stamps: psycopg returns it in the session's time zone,
        and a standby in Tokyo was dated nine hours AHEAD as text --
        hiding every write from the overlay (found in review).
        """
        if self._engine.dialect.name != "postgresql":
            return None
        query = text(
            "SELECT pg_is_in_recovery() AS standby, "
            "       pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() AS caught_up, "
            "       CASE WHEN pg_is_in_recovery() THEN pg_is_wal_replay_paused() END AS paused, "
            "       pg_last_xact_replay_timestamp() AS replayed_at, "
            "       now() - pg_last_xact_replay_timestamp() AS behind")
        try:
            with self._engine.connect() as conn:
                row = conn.execute(query).mappings().first()
        except SQLAlchemyError as e:
            logger.warning("%s: could not ask whether it is a lagging standby: %s",
                           self._describe_source(), e)
            return None
        if row is not None and row["standby"] and row["caught_up"] is None:
            # NOT STREAMING -- restoring from an archive, or its receiver
            # down: nothing says how current it is (found in review).
            logger.warning("%s is a PostgreSQL standby that is not streaming from its "
                           "primary, so how current it is cannot be told",
                           self._describe_source())
        if row is None or not row["standby"] or row["caught_up"] is not False \
                or row["replayed_at"] is None:
            return None
        behind = row["behind"]
        return SourceBehind(
            as_of=row["replayed_at"].astimezone(UTC),
            why=("this source is a PostgreSQL standby "
                 + ("whose replay is PAUSED, " if row["paused"] else "")
                 + f"up to {_age(behind)} behind what it has received: its data stops at "
                   f"{row['replayed_at'].astimezone(UTC).isoformat()}, and the copy is "
                   f"dated from then, "
                   f"not from when it was read."))

    def tables_present(self) -> "set[str] | None":
        """Tables and views, through the Inspector (see columns_present)."""
        try:
            inspector = inspect(self._engine)
            names = set(inspector.get_table_names()) | set(inspector.get_view_names())
            # Materialized views, and PostgreSQL's foreign tables, which
            # the two calls above leave out and a source may be.
            for extra in ("get_materialized_view_names", "get_foreign_table_names"):
                try:
                    names |= set(getattr(inspector, extra)())
                except (AttributeError, NotImplementedError):
                    pass
            return names
        except SQLAlchemyError as e:
            logger.warning("%s: could not list tables: %s", self._describe_source(), e)
            return None

    def health_check(self) -> None:
        from sqlalchemy import text

        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError as e:
            raise StorageUnavailable(
                f"{self._describe_source()}: {type(e).__name__}: {e}"
            ) from e
