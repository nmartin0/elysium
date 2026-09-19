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
from typing import Any

from sqlalchemy import (
    Column,
    MetaData,
    Table,
    and_,
    create_engine,
    inspect,
    select,
)
from sqlalchemy.exc import SQLAlchemyError

from core.ontology.interface import ExternalReadAdapter, StorageUnavailable
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

class SQLAlchemyReadAdapter(ExternalReadAdapter):
    """Reads objects from a database SQLAlchemy has a dialect for."""

    # WHICH FILTERS REACH THE DATABASE. The mediator applies anything not
    # listed here in Python afterwards, so an operator missing from this
    # set is slower rather than wrong.
    #
    # `contains` IS HERE AND `relative_date` IS NOT: LIKE is expressible
    # in Core, and a relative date needs today's date resolved first --
    # which the mediator does before calling, turning it into a
    # date_range.
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
        self._engine = create_engine(
            self._url,
            # POOLED, because a connection per query to a network
            # database is a handshake per query. SQLAlchemy pools by
            # default; naming it here is documentation rather than
            # configuration.
            pool_pre_ping=True,
            connect_args=self._connect_args(),
        )
        self._metadata = MetaData()

    def _connect_args(self) -> dict:
        """Per-dialect connection settings, chiefly the timeout.

        THE ONE PLACE THIS FILE KNOWS ABOUT A SPECIFIC DATABASE, and
        it says so. `statement_timeout` is PostgreSQL's spelling; MySQL
        has `max_execution_time` and Oracle has its own. A dialect
        Elysium has not met gets no timeout rather than a wrong one,
        and that gap is visible here rather than buried.
        """
        if self._url.startswith("postgresql"):
            return {
                "options": f"-c statement_timeout={self._timeout_seconds * 1000}",
            }
        return {}

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
        try:
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
        except SQLAlchemyError as e:
            raise StorageUnavailable(
                f"{self._describe_source()}: could not read the columns of "
                f"{table_name!r}: {e}"
            ) from e

    def health_check(self) -> None:
        from sqlalchemy import text

        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError as e:
            raise StorageUnavailable(
                f"{self._describe_source()}: {type(e).__name__}: {e}"
            ) from e
