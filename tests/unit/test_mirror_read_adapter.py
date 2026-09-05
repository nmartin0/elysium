"""
Tests for core/mirror/mirror_adapter.py -- Phase 4 of the read-only
mirror architecture (see ROADMAP.md).

THE CENTRAL PROPERTY, and the reason most of this file is written as
side-by-side comparisons rather than fixed expected values: a
mirror-backed read must answer IDENTICALLY to a live read of the same
data. Asserting against hardcoded expectations would prove only that
the mirror adapter does something; comparing it against the real
SQLiteReadAdapter on the same source data proves it does the SAME
thing -- which is the only property that makes a cutover safe.

This is the "read the same real object both live and from the mirror,
and diff them" verification the roadmap calls for, made permanent
rather than run once by hand.

Every test uses a REAL SQLite source, a REAL sync, and a REAL on-disk
Iceberg mirror -- never a mock of any of them.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.mirror_adapter import MirrorReadAdapter

CUSTOMER_CONFIG = {"storage": {"table": "customers", "id_column": "customer_id"}}
CUSTOMER_COLUMNS = ["customer_id", "name", "region", "email"]
TRANSACTION_COLUMNS = ["transaction_id", "customer_id", "amount"]


@pytest.fixture
def source_db(tmp_path):
    path = tmp_path / "business_data.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, region TEXT, email TEXT)"
    )
    conn.executemany(
        "INSERT INTO customers VALUES (?, ?, ?, ?)",
        [
            ("cust_001", "Ada Okafor", "us-west", "ada@example.com"),
            ("cust_002", "Bram Feldman", "us-west", "bram@example.com"),
            ("cust_003", "Chidi Nwosu", "us-east", "chidi@example.com"),
            # A real NULL, deliberately -- NULL handling is exactly the
            # kind of thing that silently differs between two backends.
            ("cust_004", "Dana Petrova", "eu", None),
        ],
    )
    conn.execute(
        "CREATE TABLE transactions (transaction_id TEXT PRIMARY KEY, customer_id TEXT, amount TEXT)"
    )
    conn.executemany(
        "INSERT INTO transactions VALUES (?, ?, ?)",
        [("t1", "cust_001", "49.99"), ("t2", "cust_001", "120.00"), ("t3", "cust_002", "12.50")],
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def adapters(tmp_path, source_db):
    """The live adapter and a mirror adapter over a real sync of the
    same data -- the pair every comparison below runs against."""
    live = SQLiteReadAdapter({"path": source_db})
    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": live})
    sync.sync_table("primary", "customers", "customer_id", CUSTOMER_COLUMNS)
    sync.sync_table("primary", "transactions", "transaction_id", TRANSACTION_COLUMNS)
    return live, MirrorReadAdapter(sync._catalog, "primary")


def test_find_ids_with_no_criteria_matches_live(adapters):
    live, mirror = adapters
    assert sorted(mirror.find_ids("Customer", {}, CUSTOMER_CONFIG)) == sorted(
        live.find_ids("Customer", {}, CUSTOMER_CONFIG)
    )


def test_find_ids_with_one_criterion_matches_live(adapters):
    live, mirror = adapters
    criteria = {"region": "us-west"}
    assert sorted(mirror.find_ids("Customer", criteria, CUSTOMER_CONFIG)) == sorted(
        live.find_ids("Customer", criteria, CUSTOMER_CONFIG)
    )


def test_find_ids_with_several_criteria_matches_live(adapters):
    # Several criteria must AND together, not OR -- getting this
    # backwards would silently return too many rows.
    live, mirror = adapters
    criteria = {"region": "us-west", "name": "Ada Okafor"}
    result = mirror.find_ids("Customer", criteria, CUSTOMER_CONFIG)

    assert sorted(result) == sorted(live.find_ids("Customer", criteria, CUSTOMER_CONFIG))
    assert result == ["cust_001"]


def test_find_ids_with_no_match_returns_empty_like_live(adapters):
    live, mirror = adapters
    criteria = {"region": "nowhere"}
    assert mirror.find_ids("Customer", criteria, CUSTOMER_CONFIG) == live.find_ids(
        "Customer", criteria, CUSTOMER_CONFIG
    )


def test_get_raw_field_matches_live(adapters):
    live, mirror = adapters
    assert mirror.get_raw_field(
        "Customer", "cust_001", "name", CUSTOMER_CONFIG
    ) == live.get_raw_field("Customer", "cust_001", "name", CUSTOMER_CONFIG)


def test_get_raw_field_returns_none_for_a_real_null_like_live(adapters):
    # NULL must come back as None, never the string "None" -- a real,
    # easy-to-get-wrong case given the mirror stores strings.
    live, mirror = adapters
    assert mirror.get_raw_field("Customer", "cust_004", "email", CUSTOMER_CONFIG) is None
    assert live.get_raw_field("Customer", "cust_004", "email", CUSTOMER_CONFIG) is None


def test_get_raw_field_returns_none_for_a_missing_row_like_live(adapters):
    # A missing row is None, never an error -- matching the live
    # adapter's own documented behavior.
    live, mirror = adapters
    assert mirror.get_raw_field("Customer", "no_such_id", "name", CUSTOMER_CONFIG) is None
    assert live.get_raw_field("Customer", "no_such_id", "name", CUSTOMER_CONFIG) is None


def test_free_text_search_matches_live(adapters):
    live, mirror = adapters
    result = mirror.find_ids_matching_text("Customer", ["name", "email"], "ada", CUSTOMER_CONFIG)

    assert sorted(result) == sorted(
        live.find_ids_matching_text("Customer", ["name", "email"], "ada", CUSTOMER_CONFIG)
    )
    assert result == ["cust_001"]


def test_free_text_search_is_case_insensitive_like_live(adapters):
    # SQLite's LIKE is case-insensitive for ASCII by default; the
    # mirror path must match that, not accidentally become
    # case-sensitive.
    live, mirror = adapters
    assert sorted(
        mirror.find_ids_matching_text("Customer", ["name"], "ADA", CUSTOMER_CONFIG)
    ) == sorted(live.find_ids_matching_text("Customer", ["name"], "ADA", CUSTOMER_CONFIG))


def test_free_text_search_matches_a_substring_not_just_a_prefix(adapters):
    # CONTAINS, not STARTS WITH -- "kafor" is mid-word in "Ada Okafor".
    live, mirror = adapters
    result = mirror.find_ids_matching_text("Customer", ["name"], "kafor", CUSTOMER_CONFIG)

    assert result == ["cust_001"]
    assert sorted(result) == sorted(
        live.find_ids_matching_text("Customer", ["name"], "kafor", CUSTOMER_CONFIG)
    )


def test_free_text_search_skips_null_columns_without_erroring(adapters):
    # cust_004 has a NULL email -- searching the email column must not
    # crash on it, and must not match it either.
    live, mirror = adapters
    result = mirror.find_ids_matching_text("Customer", ["email"], "example.com", CUSTOMER_CONFIG)

    assert "cust_004" not in result
    assert sorted(result) == sorted(
        live.find_ids_matching_text("Customer", ["email"], "example.com", CUSTOMER_CONFIG)
    )


def test_free_text_search_with_no_columns_returns_empty_like_live(adapters):
    live, mirror = adapters
    assert mirror.find_ids_matching_text("Customer", [], "ada", CUSTOMER_CONFIG) == live.find_ids_matching_text(
        "Customer", [], "ada", CUSTOMER_CONFIG
    )


def test_a_literal_percent_is_not_treated_as_a_wildcard(tmp_path):
    # The mirror path does a Python substring check, so SQL's LIKE
    # wildcards are literal characters here by construction -- proven
    # rather than assumed, since this is exactly the class of bug the
    # SQLite path needs explicit escaping to avoid.
    path = tmp_path / "pct.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT)")
    conn.executemany(
        "INSERT INTO customers VALUES (?, ?)", [("c1", "50% off"), ("c2", "50X off")]
    )
    conn.commit()
    conn.close()

    live = SQLiteReadAdapter({"path": path})
    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": live})
    sync.sync_table("primary", "customers", "customer_id", ["customer_id", "name"])
    mirror = MirrorReadAdapter(sync._catalog, "primary")

    config = {"storage": {"table": "customers", "id_column": "customer_id"}}
    result = mirror.find_ids_matching_text("Customer", ["name"], "50%", config)

    assert result == ["c1"]
    assert sorted(result) == sorted(live.find_ids_matching_text("Customer", ["name"], "50%", config))


def test_resolve_reverse_link_matches_live(adapters):
    live, mirror = adapters
    link_config = {"via_table": "transactions", "via_column": "customer_id"}

    result = mirror.resolve_reverse_link("cust_001", link_config, "transaction_id")

    assert sorted(result) == sorted(
        live.resolve_reverse_link("cust_001", link_config, "transaction_id")
    )
    assert sorted(result) == ["t1", "t2"]


def test_resolve_reverse_link_with_no_matches_is_empty_like_live(adapters):
    live, mirror = adapters
    link_config = {"via_table": "transactions", "via_column": "customer_id"}

    assert mirror.resolve_reverse_link("cust_004", link_config, "transaction_id") == (
        live.resolve_reverse_link("cust_004", link_config, "transaction_id")
    )


def test_an_unsynced_table_reads_as_empty_rather_than_erroring(tmp_path, source_db):
    # A table the mirror has never synced. Returning empty rather than
    # raising is deliberate (see the adapter's own _scan docstring) --
    # the sync itself is where a genuinely missing table fails loudly.
    live = SQLiteReadAdapter({"path": source_db})
    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": live})
    sync.sync_table("primary", "customers", "customer_id", CUSTOMER_COLUMNS)
    mirror = MirrorReadAdapter(sync._catalog, "primary")

    never_synced = {"storage": {"table": "transactions", "id_column": "transaction_id"}}
    assert mirror.find_ids("Transaction", {}, never_synced) == []
    assert mirror.get_raw_field("Transaction", "t1", "amount", never_synced) is None


def test_the_mirror_serves_the_last_sync_not_later_source_changes(adapters, source_db):
    # The defining property of a mirror: it is a point-in-time copy.
    # A source change after the sync must NOT appear until the next
    # sync -- and this is precisely the staleness the roadmap's own
    # read-your-writes design exists to handle.
    _live, mirror = adapters

    conn = sqlite3.connect(source_db)
    conn.execute("UPDATE customers SET name = 'CHANGED' WHERE customer_id = 'cust_001'")
    conn.commit()
    conn.close()

    assert mirror.get_raw_field("Customer", "cust_001", "name", CUSTOMER_CONFIG) == "Ada Okafor"
