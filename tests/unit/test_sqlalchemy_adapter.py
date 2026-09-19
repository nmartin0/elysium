"""
Reading a customer's database, against a REAL PostgreSQL.

WHY THESE TESTS RUN A SERVER. An untested database adapter would be
the largest unverified thing in this codebase, and every other commit
here is verified by measurement. `pgserver` ships PostgreSQL as a
wheel, so the suite exercises a genuine engine rather than a mock --
PostgreSQL 16.2, confirmed.

WHY SQLALCHEMY CORE. Our queries are simple, so almost everything that
differs between engines is what Core's dialects handle: placeholder
style, identifier quoting, row-limit syntax, and schema introspection.
The last decided it -- the schema-drift work needs to know what a
source says its column types are, and hand-writing that means
information_schema, PRAGMA, ALL_TAB_COLUMNS and sys.columns.

THE SQLITE ADAPTER IS UNTOUCHED. It serves Elysium's OWN storage on
the stdlib module. Two mechanisms, divided on a real line: embedded
fixture storage against a customer's real database.
"""

import tempfile

import pytest

from adapters.sqlalchemy_adapter import SQLAlchemyReadAdapter
from core.filters import FieldFilter
from core.ontology.interface import StorageUnavailable

pytest.importorskip("pgserver")
pytest.importorskip("psycopg")


@pytest.fixture(scope="module")
def postgres_url():
    """One server for the module. Starting it is the slow part."""
    import pgserver

    server = pgserver.get_server(tempfile.mkdtemp())
    return server.get_uri().replace("postgresql://", "postgresql+psycopg://")


@pytest.fixture(scope="module")
def seeded(postgres_url):
    import psycopg

    raw = postgres_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(raw) as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE customers (id text primary key, name text, region text)")
        cur.execute(
            "CREATE TABLE txns (tid text primary key, customer_id text, "
            "amount numeric(12,2), seen timestamptz)")
        cur.executemany(
            "INSERT INTO customers VALUES (%s,%s,%s)",
            [("c1", "Ann", "us-west"), ("c2", "Bo", "us-east"),
             ("c3", "Cy", "us-west")])
        cur.executemany(
            "INSERT INTO txns VALUES (%s,%s,%s,%s)",
            [("t1", "c1", "49.99", "2026-03-12T14:30:00Z"),
             ("t2", "c1", "10.50", "2026-03-13T09:00:00Z"),
             ("t3", "c2", "5.00", "2026-03-14T09:00:00Z")])
        conn.commit()
    return postgres_url


@pytest.fixture
def adapter(seeded):
    return SQLAlchemyReadAdapter({"url": seeded})


CUSTOMERS = {
    "storage": {"table": "customers", "id_column": "id"},
    "id_field": "id",
    "fields": {
        "id": {"column": "id"},
        "name": {"column": "name"},
        "region": {"column": "region"},
    },
}


class TestItReachesTheDatabase:
    def test_health_check_passes(self, adapter):
        adapter.health_check()

    def test_it_reads_every_id(self, adapter):
        assert sorted(adapter.find_ids("Customer", [], CUSTOMERS)) == [
            "c1", "c2", "c3",
        ]

    def test_it_reads_one_field(self, adapter):
        assert adapter.get_raw_field("Customer", "c1", "name", CUSTOMERS) == "Ann"

    def test_a_missing_object_reads_as_none(self, adapter):
        assert adapter.get_raw_field("Customer", "nope", "name", CUSTOMERS) is None


class TestFiltersReachTheQuery:
    def test_equals_filters_in_sql(self, adapter):
        """THE MAC PUSHDOWN'S DESTINATION. A `field:` security
        declaration becomes exactly this condition, so the database
        returns only rows the user may see."""
        west = FieldFilter(field="region", operator="equals", value="us-west")

        assert sorted(adapter.find_ids("Customer", [west], CUSTOMERS)) == ["c1", "c3"]

    def test_in_filters_in_sql(self, adapter):
        both = FieldFilter(field="id", operator="in", value=["c1", "c2"])

        assert sorted(adapter.find_ids("Customer", [both], CUSTOMERS)) == ["c1", "c2"]

    def test_contains_escapes_its_wildcards(self, adapter):
        """WILDCARDS IN THE BOUND VALUE, not the pattern, so a value
        containing % cannot widen its own match."""
        everything = FieldFilter(field="name", operator="contains", value="%")

        assert adapter.find_ids("Customer", [everything], CUSTOMERS) == []

    def test_a_range_with_no_bounds_is_refused(self, adapter):
        """BOTH ABSENT MATCHES NOTHING AND REPORTS NO ERROR, which the
        SQLite adapter calls the hardest kind of wrong answer."""
        empty = FieldFilter(field="id", operator="range", value={})

        with pytest.raises(ValueError, match="at least one bound"):
            adapter.find_ids("Customer", [empty], CUSTOMERS)


class TestTheLimitReachesTheQuery:
    def test_it_reads_no_more_than_asked(self, adapter):
        assert len(adapter.find_ids("Customer", [], CUSTOMERS, 2)) == 2

    def test_none_means_everything(self, adapter):
        assert len(adapter.find_ids("Customer", [], CUSTOMERS, None)) == 3


class TestTypesArriveAsTheOntologyExpects:
    def test_numeric_becomes_decimal(self, adapter):
        """psycopg RETURNS Decimal FOR numeric, which is what the
        ontology's `decimal` type declares -- and the reason the live
        read path was taught to coerce BEFORE this adapter existed."""
        import decimal

        rows = adapter.read_fields_for_ids(
            "txns", "tid", ["t1"], ["amount"], CUSTOMERS)

        assert isinstance(rows[0]["amount"], decimal.Decimal)

    def test_timestamptz_becomes_an_aware_datetime(self, adapter):
        rows = adapter.read_fields_for_ids(
            "txns", "tid", ["t1"], ["seen"], CUSTOMERS)

        assert rows[0]["seen"].tzinfo is not None


class TestReverseLinks:
    def test_it_groups_targets_by_source(self, adapter):
        links = adapter.resolve_reverse_links_batch(
            ["c1", "c2"], {"target_table": "txns", "target_column": "customer_id"},
            "tid",
        )

        assert sorted(links["c1"]) == ["t1", "t2"]

    def test_a_source_with_no_links_gets_an_empty_list(self, adapter):
        """EVERY REQUESTED ID GETS A KEY. A caller that had to
        distinguish "no links" from "not asked about" would need the
        input list too."""
        links = adapter.resolve_reverse_links_batch(
            ["c3"], {"target_table": "txns", "target_column": "customer_id"}, "tid",
        )

        assert links == {"c3": []}

    def test_no_ids_asks_nothing(self, adapter):
        # AN EMPTY IN () IS A SYNTAX ERROR in several engines.
        assert adapter.resolve_reverse_links_batch(
            [], {"target_table": "txns", "target_column": "customer_id"}, "tid",
        ) == {}


class TestIntrospection:
    def test_it_reports_the_columns_a_table_has(self, adapter):
        """THE REASON THIS ADAPTER IS ON SQLALCHEMY. Hand-writing this
        means four dialects of the same question."""
        assert adapter.columns_present("customers") == {"id", "name", "region"}

    def test_a_missing_table_is_unavailable_rather_than_empty(self, adapter):
        # Empty would read as "a table with no columns", which is not
        # a thing, and the drift policy would absorb it.
        with pytest.raises(StorageUnavailable):
            adapter.columns_present("no_such_table")


class TestWhenTheDatabaseIsUnreachable:
    def test_it_raises_storage_unavailable(self):
        """ONE TYPE FOR EVERY WAY A SOURCE CAN BE UNREACHABLE, which
        is what the mediator's degrade-rather-than-die path expects."""
        adapter = SQLAlchemyReadAdapter(
            {"url": "postgresql+psycopg://nobody@127.0.0.1:1/nothing"})

        with pytest.raises(StorageUnavailable):
            adapter.health_check()

    def test_the_password_is_not_in_the_message(self):
        """AN ERROR MESSAGE IS THE MOST LIKELY PLACE for a credential
        to end up in a log somebody pastes."""
        adapter = SQLAlchemyReadAdapter(
            {"url": "postgresql+psycopg://user:hunter2@127.0.0.1:1/nothing"})

        with pytest.raises(StorageUnavailable) as caught:
            adapter.health_check()

        assert "hunter2" not in str(caught.value)
