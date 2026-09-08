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
from core.filters import FieldFilter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.mirror_adapter import MirrorReadAdapter


def _as_conditions(criteria: dict) -> list[FieldFilter]:
    """The old {column: value} shape as equality conditions.

    find_ids now takes a condition list -- one value per field could
    not express "in these two", which is what selecting values on a
    chart means. These tests predate that and only ever used equality.
    """
    return [FieldFilter(field=k, operator="equals", value=v) for k, v in criteria.items()]

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
    assert sorted(mirror.find_ids("Customer", [], CUSTOMER_CONFIG)) == sorted(
        live.find_ids("Customer", [], CUSTOMER_CONFIG)
    )


def test_find_ids_with_one_criterion_matches_live(adapters):
    live, mirror = adapters
    criteria = {"region": "us-west"}
    assert sorted(mirror.find_ids("Customer", _as_conditions(criteria), CUSTOMER_CONFIG)) == sorted(
        live.find_ids("Customer", _as_conditions(criteria), CUSTOMER_CONFIG)
    )


def test_find_ids_with_several_criteria_matches_live(adapters):
    # Several criteria must AND together, not OR -- getting this
    # backwards would silently return too many rows.
    live, mirror = adapters
    criteria = {"region": "us-west", "name": "Ada Okafor"}
    result = mirror.find_ids("Customer", _as_conditions(criteria), CUSTOMER_CONFIG)

    assert sorted(result) == sorted(live.find_ids("Customer", _as_conditions(criteria), CUSTOMER_CONFIG))
    assert result == ["cust_001"]


def test_find_ids_with_no_match_returns_empty_like_live(adapters):
    live, mirror = adapters
    criteria = {"region": "nowhere"}
    assert mirror.find_ids("Customer", _as_conditions(criteria), CUSTOMER_CONFIG) == live.find_ids(
        "Customer", _as_conditions(criteria), CUSTOMER_CONFIG
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
    assert mirror.find_ids("Transaction", [], never_synced) == []
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


def test_substring_search_reads_only_the_searched_columns(tmp_path):
    # Point 4 of the machinery audit rejected adding DuckDB as a second
    # query engine, on the grounds that the one operation Iceberg cannot
    # push down -- substring search -- is fast enough in Python. That
    # argument only holds while this method keeps PROJECTING: it must
    # read the id column plus the searched columns, never whole rows.
    #
    # Asserted structurally (which columns are fetched) rather than by
    # timing, which would be flaky. If someone later widens this to a
    # full-row scan, the DuckDB decision genuinely deserves revisiting,
    # and this test is what should force that conversation.
    path = tmp_path / "wide.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE people (person_id TEXT PRIMARY KEY, name TEXT, "
        "bio TEXT, unrelated_a TEXT, unrelated_b TEXT)"
    )
    conn.executemany(
        "INSERT INTO people VALUES (?, ?, ?, ?, ?)",
        [(f"p{i}", f"Person {i}", f"bio {i}", "x" * 50, "y" * 50) for i in range(200)],
    )
    conn.commit()
    conn.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": SQLiteReadAdapter({"path": path})})
    sync.sync_table(
        "primary", "people", "person_id",
        ["person_id", "name", "bio", "unrelated_a", "unrelated_b"],
    )
    adapter = MirrorReadAdapter(sync._catalog, "primary")

    scanned_fields = {}
    real_scan = adapter._scan

    def recording_scan(table_name, selected_fields, row_filter=None):
        scanned_fields["fields"] = selected_fields
        return real_scan(table_name, selected_fields, row_filter)

    adapter._scan = recording_scan
    config = {"storage": {"table": "people", "id_column": "person_id"}}
    matches = adapter.find_ids_matching_text("Person", ["name"], "Person 42", config)

    assert matches == ["p42"]
    assert set(scanned_fields["fields"]) == {"person_id", "name"}, (
        "substring search must project, not read whole rows"
    )


# --- Filter operators, against live as the oracle ------------------------
#
# The Iceberg translation for in, not_in, range and date_range was
# written and shipped with NO test -- only the `contains` rejection was
# covered. A coverage run found lines 294-305 untouched, which is the
# whole of _term_for's operator handling.
#
# They work. I did not know that when I shipped them, and "it happened
# to be right" is not verification.
#
# Every one compares against the LIVE adapter rather than an expected
# list: the mirror's job is to answer identically, so live is the
# oracle. An expectation written by hand would encode what I think the
# fixture contains, which is the same guess twice.


def test_in_matches_live(adapters):
    live, mirror = adapters
    conditions = [FieldFilter("region", "in", ["us-west", "us-east"])]

    assert sorted(mirror.find_ids("Customer", conditions, CUSTOMER_CONFIG)) == sorted(
        live.find_ids("Customer", conditions, CUSTOMER_CONFIG)
    )


def test_in_with_one_value_matches_live(adapters):
    # The degenerate case: IN with a single literal must behave like
    # equality, not like something Iceberg special-cases away.
    live, mirror = adapters
    conditions = [FieldFilter("region", "in", ["us-west"])]

    assert sorted(mirror.find_ids("Customer", conditions, CUSTOMER_CONFIG)) == sorted(
        live.find_ids("Customer", conditions, CUSTOMER_CONFIG)
    )


def test_not_in_matches_live(adapters):
    live, mirror = adapters
    conditions = [FieldFilter("region", "not_in", ["us-east"])]

    assert sorted(mirror.find_ids("Customer", conditions, CUSTOMER_CONFIG)) == sorted(
        live.find_ids("Customer", conditions, CUSTOMER_CONFIG)
    )


def test_a_two_sided_range_matches_live(adapters):
    live, mirror = adapters
    conditions = [FieldFilter("name", "range", {"min": "A", "max": "z"})]

    assert sorted(mirror.find_ids("Customer", conditions, CUSTOMER_CONFIG)) == sorted(
        live.find_ids("Customer", conditions, CUSTOMER_CONFIG)
    )


def test_a_one_sided_range_matches_live(adapters):
    # The branch that builds ONE bound rather than an And of two --
    # untested, and a different code path.
    live, mirror = adapters
    conditions = [FieldFilter("name", "range", {"min": "A"})]

    assert sorted(mirror.find_ids("Customer", conditions, CUSTOMER_CONFIG)) == sorted(
        live.find_ids("Customer", conditions, CUSTOMER_CONFIG)
    )


def test_several_conditions_are_anded(adapters):
    # _conditions_to_filter's And-folding loop, which only runs with
    # more than one condition.
    live, mirror = adapters
    conditions = [
        FieldFilter("region", "in", ["us-west", "us-east"]),
        FieldFilter("name", "range", {"min": "A"}),
    ]

    assert sorted(mirror.find_ids("Customer", conditions, CUSTOMER_CONFIG)) == sorted(
        live.find_ids("Customer", conditions, CUSTOMER_CONFIG)
    )


def test_a_filter_matching_nothing_matches_live(adapters):
    live, mirror = adapters
    conditions = [FieldFilter("region", "in", ["nowhere", "elsewhere"])]

    assert mirror.find_ids("Customer", conditions, CUSTOMER_CONFIG) == live.find_ids(
        "Customer", conditions, CUSTOMER_CONFIG
    )


def test_read_fields_for_ids_matches_live(adapters):
    """The mirror's narrow read, added with the SQL-alignment work and
    shipped with no test of its own.

    Found by the same coverage run: lines 202-208 untouched. It works.
    That it happened to work is not the same as having checked.
    """
    live, mirror = adapters

    assert mirror.read_fields_for_ids(
        "customers", "customer_id", ["cust_001"], ["name"], CUSTOMER_CONFIG
    ) == live.read_fields_for_ids(
        "customers", "customer_id", ["cust_001"], ["name"], CUSTOMER_CONFIG
    )


def test_read_fields_for_ids_with_no_ids_reads_nothing(adapters):
    # The early return, and the case a caller hits whenever a
    # pushed-down filter matched nothing.
    _live, mirror = adapters

    assert mirror.read_fields_for_ids(
        "customers", "customer_id", [], ["name"], CUSTOMER_CONFIG
    ) == []


def test_read_fields_for_ids_returns_only_the_ids_asked_for(adapters):
    # The Iceberg path filters after a projected scan, because the
    # format has no IN predicate over an arbitrary list. That filter is
    # the whole correctness of this method.
    live, mirror = adapters
    all_ids = live.find_ids("Customer", [], CUSTOMER_CONFIG)
    wanted = all_ids[:1]

    rows = mirror.read_fields_for_ids(
        "customers", "customer_id", wanted, ["name"], CUSTOMER_CONFIG
    )

    assert [row["customer_id"] for row in rows] == wanted
    assert len(all_ids) > 1, "the fixture needs more than one row, or this proves nothing"
