"""
A storage failure names what is wrong, not just that something is.

"no such table: transactions" propagated raw through the adapter, the
mediator, the route and FastAPI, arriving as an opaque 500. Everything
needed to diagnose it -- which database, and that the ontology declares
a table the source does not have -- was available at the point of
failure and thrown away.

core/mirror/drift_policy.py already argues this for the SYNC path:
storage behaviour must not become policy by default. The same applies
on the READ path, where a dropped source table is a deployment problem
with a specific remedy, not a server fault.

MAC WIDENS THE BLAST RADIUS, which is how this was met. Transaction
inherits its security value from its Customer via a link, so ANY read
of a transaction touches two tables and either one missing produces
this -- through _get_security_value, before the read the caller asked
for even begins.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.ontology.interface import StorageUnavailable

TYPE_CONFIG = {"storage": {"table": "transactions", "id_column": "transaction_id"}}


@pytest.fixture
def empty_db(tmp_path):
    path = tmp_path / "silo.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE other (id TEXT)")
    connection.commit()
    connection.close()
    return path


def test_a_missing_table_says_which_table(empty_db):
    adapter = SQLiteReadAdapter({"path": empty_db})

    with pytest.raises(StorageUnavailable) as caught:
        adapter.get_raw_field("Transaction", "1", "category", TYPE_CONFIG)

    assert "transactions" in str(caught.value)


def test_a_missing_table_says_which_database(empty_db):
    # A deployment has several silos. "No such table" without a path
    # leaves an operator checking each one by hand.
    adapter = SQLiteReadAdapter({"path": empty_db})

    with pytest.raises(StorageUnavailable) as caught:
        adapter.get_raw_field("Transaction", "1", "category", TYPE_CONFIG)

    assert str(empty_db) in str(caught.value)


def test_a_missing_table_says_what_it_means(empty_db):
    # The remedy, not just the symptom: the ontology declares something
    # the database does not have, which is a source change rather than
    # a fault in Elysium.
    adapter = SQLiteReadAdapter({"path": empty_db})

    with pytest.raises(StorageUnavailable, match="dropped or renamed"):
        adapter.get_raw_field("Transaction", "1", "category", TYPE_CONFIG)


def test_a_missing_column_is_distinguished_from_a_missing_table(tmp_path):
    # Different causes, different remedies. Collapsing them would send
    # an operator looking for a dropped table when a column was
    # renamed.
    path = tmp_path / "silo.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE transactions (transaction_id TEXT)")
    connection.commit()
    connection.close()

    with pytest.raises(StorageUnavailable, match="column"):
        SQLiteReadAdapter({"path": path}).get_raw_field(
            "Transaction", "1", "category", TYPE_CONFIG,
        )


def test_it_is_a_distinct_type_not_a_bare_RuntimeError(empty_db):
    # THE ROUTE HAS TO TELL THESE APART from a genuine fault: one is
    # worth showing a caller verbatim and the other is not. Catching
    # RuntimeError broadly would eventually swallow a real bug and
    # report it as a configuration problem, which is the more
    # expensive mistake.
    adapter = SQLiteReadAdapter({"path": empty_db})

    with pytest.raises(StorageUnavailable):
        adapter.get_raw_field("Transaction", "1", "category", TYPE_CONFIG)


def test_a_working_read_is_unaffected(tmp_path):
    # THE CONTROL. An adapter that raised on everything would pass every
    # test above.
    path = tmp_path / "silo.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE transactions (transaction_id TEXT, category TEXT)")
    connection.execute("INSERT INTO transactions VALUES ('1', 'subscription')")
    connection.commit()
    connection.close()

    value = SQLiteReadAdapter({"path": path}).get_raw_field(
        "Transaction", "1", "category", TYPE_CONFIG,
    )

    assert value == "subscription"
