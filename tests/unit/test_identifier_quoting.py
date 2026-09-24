"""
Table and column names that need quoting (LIB-3).

REPRODUCED BEFORE FIXING: a table called `order details` and a column
called `group` are both legal in SQLite, and every query this adapter
built interpolated them into SQL text unquoted -- so a customer
database using either could not be mapped at all. The error was
`near "order": syntax error`, which reads like a bug in Elysium and is
really a name Elysium refused to say properly.

NOT A SECURITY HOLE, and worth being precise about: these names come
from the deployment's own configuration, not from a request. What they
are is a CLASS of failure -- and the answer to a class is a library
that knows the rules, not a patch per instance.

SQLALCHEMY WAS ALREADY A DEPENDENCY (rule 18 prefers one we have), and
its IdentifierPreparer knows which words this dialect reserves, when
quotes are needed, and how to escape a quote inside a name. Writing
that by hand is the sort of thing that looks right for years and then
meets a column called `group`.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter, SQLiteWriteAdapter
from core.filters import as_equality_conditions

AWKWARD = {
    "id_field": "id",
    "security": {"field": "group"},
    "storage": {"silo": "s", "table": "order details", "id_column": "id"},
    "fields": {
        "id": {"type": "data"},
        "unit price": {"type": "data"},
        # A RESERVED WORD, which is the case that bites in practice.
        "group": {"type": "data"},
    },
}


@pytest.fixture
def awkward_database(tmp_path):
    path = tmp_path / "s.db"
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE "order details" '
                 '(id TEXT PRIMARY KEY, "unit price" TEXT, "group" TEXT)')
    conn.executemany('INSERT INTO "order details" VALUES (?,?,?)',
                     [("r1", "9.99", "west"), ("r2", "4.50", "east")])
    conn.commit()
    conn.close()
    return path


class TestReading:
    def test_every_row_can_be_listed(self, awkward_database):
        adapter = SQLiteReadAdapter({"path": awkward_database})

        assert sorted(adapter.find_ids("Order", [], AWKWARD)) == ["r1", "r2"]

    def test_a_filter_on_a_reserved_word_column(self, awkward_database):
        adapter = SQLiteReadAdapter({"path": awkward_database})

        found = adapter.find_ids("Order", as_equality_conditions({"group": "west"}), AWKWARD)

        assert found == ["r1"]

    def test_a_field_whose_name_has_a_space(self, awkward_database):
        adapter = SQLiteReadAdapter({"path": awkward_database})

        assert adapter.get_raw_field("Order", "r1", "unit price", AWKWARD) == "9.99"

    def test_a_bulk_read(self, awkward_database):
        adapter = SQLiteReadAdapter({"path": awkward_database})

        rows = adapter.read_fields_for_ids(
            "order details", "id", ["r1", "r2"], ["unit price"], AWKWARD)

        assert sorted(row["unit price"] for row in rows) == ["4.50", "9.99"]

    def test_free_text_search(self, awkward_database):
        adapter = SQLiteReadAdapter({"path": awkward_database})

        found = adapter.find_ids_matching_text("Order", ["group"], "wes", AWKWARD)

        assert found == ["r1"]

    def test_reading_every_row(self, awkward_database):
        adapter = SQLiteReadAdapter({"path": awkward_database})

        rows = adapter.read_all_rows("order details", ["id", "group"], AWKWARD)

        assert len(rows) == 2

    def test_the_columns_can_be_inspected(self, awkward_database):
        adapter = SQLiteReadAdapter({"path": awkward_database})

        assert "unit price" in adapter.columns_present("order details")


class TestWriting:
    def test_an_update(self, awkward_database):
        write = SQLiteWriteAdapter({"path": awkward_database})
        read = SQLiteReadAdapter({"path": awkward_database})

        assert write.write_fields("Order", "r1", {"unit price": "12.50"}, {}, AWKWARD)
        assert read.get_raw_field("Order", "r1", "unit price", AWKWARD) == "12.50"

    def test_a_create(self, awkward_database):
        write = SQLiteWriteAdapter({"path": awkward_database})
        read = SQLiteReadAdapter({"path": awkward_database})

        write.create_object("Order", {"id": "r3", "unit price": "1.00", "group": "eu"}, AWKWARD)

        assert "r3" in read.find_ids("Order", [], AWKWARD)

    def test_an_update_guarded_by_an_expected_value(self, awkward_database):
        """The compare-and-set path builds its own WHERE clause, so it
        needs quoting too -- and a silent failure here would look like
        a concurrent edit rather than a syntax error."""
        write = SQLiteWriteAdapter({"path": awkward_database})

        changed = write.write_fields(
            "Order", "r1", {"unit price": "3.00"}, {"group": "west"}, AWKWARD)

        assert changed


class TestOrdinaryNamesAreUnaffected:
    """The quoting must not change anything for a normal schema, which
    is every existing deployment."""

    def test_a_plain_table_still_reads(self, tmp_path):
        path = tmp_path / "plain.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, region TEXT)")
        conn.execute("INSERT INTO customers VALUES ('c1', 'us-west')")
        conn.commit()
        conn.close()
        plain = {"id_field": "customer_id", "security": {"field": "region"},
                  "storage": {"silo": "s", "table": "customers", "id_column": "customer_id"},
                  "fields": {"customer_id": {"type": "data"}, "region": {"type": "data"}}}

        adapter = SQLiteReadAdapter({"path": path})

        assert adapter.find_ids("Customer", [], plain) == ["c1"]
        assert adapter.get_raw_field("Customer", "c1", "region", plain) == "us-west"
