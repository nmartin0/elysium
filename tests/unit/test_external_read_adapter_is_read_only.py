"""
Tests for the REAL, structural read-only guarantee on the external
read path -- Phase 1 of the read-only mirror initiative (see
ROADMAP.md's own "Read-only data mirror architecture" section).

The property under test is deliberately NOT "SQLiteReadAdapter has no
write methods" -- that was Phase 0, and is already true by type alone
(ExternalReadAdapter declares none). What's proven here is the
stronger, genuinely structural guarantee Phase 1 adds: the underlying
CONNECTION itself refuses writes, at the SQLite engine level, so even
a raw conn.execute() -- a future bug, or a careless addition inside
the adapter itself -- cannot write to the customer's own, external,
third-party business data through the read path.

The corresponding negative half matters just as much and is tested
here too: SQLiteWriteAdapter, which inherits SQLiteReadAdapter's four
real read implementations, must still genuinely WRITE (its own
_connection() override), and must still genuinely READ (WriteMediator's
own optimistic-concurrency check depends on reading current values
before writing).
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter, SQLiteWriteAdapter

TYPE_CONFIG = {
    "storage": {"silo": "test", "table": "customers", "id_column": "customer_id"},
}


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "business_data.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO customers VALUES ('c1', 'Ada')")
    conn.commit()
    conn.close()
    return path


def test_read_adapter_genuinely_reads(db_path):
    reader = SQLiteReadAdapter({"path": db_path})
    assert reader.find_ids("Customer", {}, TYPE_CONFIG) == ["c1"]
    assert reader.get_raw_field("Customer", "c1", "name", TYPE_CONFIG) == "Ada"


def test_a_raw_write_through_the_read_adapters_own_connection_is_denied(db_path):
    # THE real Phase 1 proof -- deliberately bypassing the adapter's own
    # public methods entirely and issuing a raw UPDATE straight through
    # its connection, exactly as a future bug inside this class might.
    # Denied by SQLite itself, not by convention or by the absence of a
    # write method.
    reader = SQLiteReadAdapter({"path": db_path})
    with reader._connection() as conn, pytest.raises(Exception, match="not authorized"):
        conn.execute("UPDATE customers SET name = 'HACKED' WHERE customer_id = 'c1'")


def test_a_raw_delete_and_drop_through_the_read_adapter_are_also_denied(db_path):
    # Not just UPDATE -- the authorizer denies every write-type
    # operation, including the destructive ones a real, misconfigured
    # credential would otherwise allow against a customer's own
    # database (the exact scenario Palantir's own docs warn about:
    # "syncs can change the source system if the source credentials
    # allow it... dropping data from a database via arbitrary SQL").
    reader = SQLiteReadAdapter({"path": db_path})
    with reader._connection() as conn:
        with pytest.raises(Exception, match="not authorized"):
            conn.execute("DELETE FROM customers WHERE customer_id = 'c1'")
        with pytest.raises(Exception, match="not authorized"):
            conn.execute("DROP TABLE customers")


def test_the_data_is_genuinely_untouched_after_denied_writes(db_path):
    # Confirms the denials above are real refusals, not silent no-ops
    # that might still have partially applied something.
    reader = SQLiteReadAdapter({"path": db_path})
    with reader._connection() as conn, pytest.raises(Exception, match="not authorized"):
        conn.execute("UPDATE customers SET name = 'HACKED' WHERE customer_id = 'c1'")

    assert reader.get_raw_field("Customer", "c1", "name", TYPE_CONFIG) == "Ada"


def test_the_write_adapter_still_genuinely_writes(db_path):
    # The necessary other half: SQLiteWriteAdapter inherits
    # SQLiteReadAdapter (for its reads) but overrides _connection(), so
    # the read-only guarantee must NOT leak onto the write path.
    reader = SQLiteReadAdapter({"path": db_path})
    writer = SQLiteWriteAdapter({"path": db_path})

    assert writer.write_fields("Customer", "c1", {"name": "Grace"}, {"name": "Ada"}, TYPE_CONFIG) is True
    assert reader.get_raw_field("Customer", "c1", "name", TYPE_CONFIG) == "Grace"


def test_the_write_adapter_can_still_read_too(db_path):
    # WriteMediator's own optimistic-concurrency check genuinely reads
    # current values before writing -- so the inherited read methods
    # must keep working on the write adapter, through its own
    # write-capable connection.
    writer = SQLiteWriteAdapter({"path": db_path})
    assert writer.get_raw_field("Customer", "c1", "name", TYPE_CONFIG) == "Ada"
    assert writer.find_ids("Customer", {}, TYPE_CONFIG) == ["c1"]
