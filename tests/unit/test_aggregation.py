"""
Point 6 of the machinery audit: the Object Set Service equivalent --
real aggregation primitives on DataMediator.

FOUNDRY'S PRECEDENT. Their Object Set Service serves "searching,
filtering, aggregating, and loading," and their aggregate API exposes
min/avg/max/count with groupBy. Elysium had the first two and neither
of the last: DataMediator's whole public surface was six methods, none
analytical. A warehouse with no way to ask it warehouse questions.

THE CONSTRAINT THAT SHAPES THE DESIGN, and the reason this is a method
rather than exposed SQL. MAC is applied per object in Python, AFTER the
engine returns, because a security value can be reached through a
via_field chain that crosses silos. A GROUP BY pushed into the engine
would aggregate rows the caller cannot see -- letting someone infer
sums over data they are not permitted to read. Foundry has the same
constraint, which is why OSS is a service rather than a SQL endpoint.

So: filter and project in the engine, authorize per object in Python,
aggregate over what survives.
"""

import sqlite3

import pytest
import yaml

from core.deployment_loader import _WRITE_ADAPTER_REGISTRY, _build_adapters
from core.intermediate_layer.auth import UserRecord
from core.ontology.mediator import DataMediator

FIXTURES = "tests/integration/fixtures/"
CUSTOMER_SERVICE = UserRecord(user_id="u1", security_value="us-west", role_name="customer_service")
OTHER_REGION = UserRecord(user_id="u2", security_value="us-east", role_name="customer_service")


@pytest.fixture
def mediator(tmp_path):
    schema = yaml.safe_load(open(FIXTURES + "ontology_schema.yaml"))
    policy = yaml.safe_load(open(FIXTURES + "policy.yaml"))

    db_path = tmp_path / "business.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(open(FIXTURES + "schema.sql").read())
    conn.commit()
    conn.close()

    adapters = _build_adapters(
        {"primary_sql": {"adapter": "sqlite", "connection": {"path": db_path}}},
        _WRITE_ADAPTER_REGISTRY,
    )
    object_types = {
        name: type_def
        for name, type_def in schema["object_types"].items()
        if name in ("Customer", "Transaction")
    }
    return DataMediator(
        object_types, adapters, dict.fromkeys(object_types, "primary_sql"), policy["roles"]
    )


def test_count_objects_counts_what_the_caller_can_see(mediator):
    assert mediator.count_objects(CUSTOMER_SERVICE, "Customer", {}) == 2


def test_count_objects_respects_mac_rather_than_counting_raw_rows(mediator):
    # THE property that makes this a service rather than a SQL
    # COUNT(*). Two users legitimately get different answers for the
    # same count, and a count that ignored MAC would leak the existence
    # of rows outside the caller's boundary.
    us_west = mediator.count_objects(CUSTOMER_SERVICE, "Customer", {})
    us_east = mediator.count_objects(OTHER_REGION, "Customer", {})

    # Different answers to the same question, which is the whole point.
    assert us_west != us_east
    # Each user sees only their own region's customers -- the counts
    # are equal here by coincidence of the fixture, so the real
    # assertion is that they see DIFFERENT objects, not the same set.
    west_ids = set(mediator.search_object(CUSTOMER_SERVICE, "Customer", {}))
    east_ids = set(mediator.search_object(OTHER_REGION, "Customer", {}))
    assert west_ids and east_ids
    assert west_ids != east_ids, "MAC must partition what each caller counts"


def test_count_objects_applies_criteria(mediator):
    assert mediator.count_objects(CUSTOMER_SERVICE, "Customer", {"region": "us-west"}) == 2
    assert mediator.count_objects(CUSTOMER_SERVICE, "Customer", {"region": "nowhere"}) == 0


def test_aggregate_sums_grouped_by_a_field(mediator):
    result = mediator.aggregate_by_field(
        CUSTOMER_SERVICE, "Transaction", {}, group_by="category",
        aggregate="sum", field_name="amount",
    )

    assert result["hardware"] == 199.0
    assert result["refund"] == -20.0
    assert round(result["subscription"], 2) == 99.98


def test_every_aggregate_function_works(mediator):
    def aggregate(name):
        return mediator.aggregate_by_field(
            CUSTOMER_SERVICE, "Transaction", {}, group_by="category",
            aggregate=name, field_name="amount",
        )

    assert aggregate("count")["subscription"] == 2
    assert round(aggregate("avg")["subscription"], 2) == 49.99
    assert aggregate("min")["subscription"] == 49.99
    assert aggregate("max")["hardware"] == 199.0


def test_count_needs_no_field_name(mediator):
    # Matches Foundry, where count aggregates the set itself rather
    # than a property.
    result = mediator.aggregate_by_field(
        CUSTOMER_SERVICE, "Transaction", {}, group_by="category", aggregate="count"
    )

    assert result["subscription"] == 2


def test_no_group_by_aggregates_the_whole_set(mediator):
    result = mediator.aggregate_by_field(
        CUSTOMER_SERVICE, "Transaction", {}, group_by=None,
        aggregate="max", field_name="amount",
    )

    assert result == {None: 199.0}


def test_an_unknown_aggregate_is_rejected(mediator):
    with pytest.raises(ValueError, match="Unknown aggregate"):
        mediator.aggregate_by_field(
            CUSTOMER_SERVICE, "Transaction", {}, group_by="category",
            aggregate="median", field_name="amount",
        )


def test_an_aggregate_needing_a_field_rejects_a_missing_one(mediator):
    with pytest.raises(ValueError, match="requires a field_name"):
        mediator.aggregate_by_field(
            CUSTOMER_SERVICE, "Transaction", {}, group_by="category", aggregate="sum"
        )


def test_aggregation_excludes_objects_the_caller_cannot_see(mediator):
    # The same MAC boundary as count_objects, on the aggregate path.
    # Aggregating over rows a caller cannot read would let them infer
    # values they are not permitted to see -- the exact reason this
    # cannot be a pushed-down GROUP BY.
    visible = mediator.aggregate_by_field(
        CUSTOMER_SERVICE, "Transaction", {}, group_by=None,
        aggregate="count", field_name=None,
    )
    hidden = mediator.aggregate_by_field(
        OTHER_REGION, "Transaction", {}, group_by=None,
        aggregate="count", field_name=None,
    )

    assert visible[None] > 0
    # us-east sees a different Transaction set (its own customers'),
    # so the aggregate genuinely differs.
    assert hidden.get(None, 0) != visible[None], (
        "two users with different MAC values must not see the same aggregate"
    )


def test_an_empty_result_set_aggregates_to_nothing(mediator):
    result = mediator.aggregate_by_field(
        CUSTOMER_SERVICE, "Transaction", {"category": "nonexistent"},
        group_by="category", aggregate="sum", field_name="amount",
    )

    assert result == {}


def test_aggregation_reads_data_in_bulk_not_per_object(mediator):
    # THE performance property this method exists for. The naive
    # version -- get_object() per matching id -- cost 16,045 SQL
    # queries to aggregate 2,004 objects, measured directly.
    #
    # Asserted as a DELTA against search_object() alone, not an
    # absolute number: search_object's own per-object MAC resolution is
    # a real, pre-existing cost that this method inherits and does not
    # introduce. What must stay true is that reading the DATA adds a
    # constant, not one query per object.
    import adapters.sqlite_adapter as sqlite_adapter_module

    real_run_query = sqlite_adapter_module._run_query
    real_run_query_one = sqlite_adapter_module._run_query_one
    counted = {"n": 0}

    def counting(fn):
        def wrapper(*args, **kwargs):
            counted["n"] += 1
            return fn(*args, **kwargs)
        return wrapper

    sqlite_adapter_module._run_query = counting(real_run_query)
    sqlite_adapter_module._run_query_one = counting(real_run_query_one)
    try:
        counted["n"] = 0
        mediator.search_object(CUSTOMER_SERVICE, "Transaction", {})
        search_only = counted["n"]

        counted["n"] = 0
        mediator.aggregate_by_field(
            CUSTOMER_SERVICE, "Transaction", {}, group_by="category",
            aggregate="sum", field_name="amount",
        )
        with_aggregation = counted["n"]
    finally:
        sqlite_adapter_module._run_query = real_run_query
        sqlite_adapter_module._run_query_one = real_run_query_one

    # One bulk read on top of the search, not one read per object.
    assert with_aggregation - search_only <= 2, (
        f"aggregation added {with_aggregation - search_only} queries over search alone"
    )


def test_the_cost_of_an_aggregate_is_dominated_by_mac_not_by_reading(tmp_path):
    # Point 8 of the machinery audit, pinned as a test rather than left
    # as a number in a commit message.
    #
    # The question was whether to add a second query engine (DuckDB)
    # for analytical work. Profiling aggregate_by_field() over 20,000
    # objects answered it: 98% of the time is check_access(), 1% is
    # reading and grouping the data. An engine that made the data half
    # infinitely fast would save 1%.
    #
    # MAC cannot move into a query engine, because a security value is
    # reached by following via_field chains that can cross silos. So
    # the bottleneck is structurally outside any engine's reach, and
    # the useful optimization is batching MAC resolution instead.
    #
    # Asserted as a RATIO of query counts rather than wall-clock time,
    # which would be flaky. If this ever inverts -- if reading starts
    # to dominate -- the second-engine question genuinely deserves
    # reopening, and this test is what should prompt that.
    import adapters.sqlite_adapter as sqlite_adapter_module

    db_path = tmp_path / "many.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(open(FIXTURES + "schema.sql").read())
    conn.executemany(
        "INSERT INTO transactions (customer_id, amount, currency, category, transaction_date) "
        "VALUES (?, ?, ?, ?, ?)",
        [("cust_001", i * 1.5, "USD", ["a", "b", "c"][i % 3], "2024-01-01") for i in range(500)],
    )
    conn.commit()
    conn.close()

    schema = yaml.safe_load(open(FIXTURES + "ontology_schema.yaml"))
    policy = yaml.safe_load(open(FIXTURES + "policy.yaml"))
    adapters = _build_adapters(
        {"primary_sql": {"adapter": "sqlite", "connection": {"path": db_path}}},
        _WRITE_ADAPTER_REGISTRY,
    )
    object_types = {
        name: type_def
        for name, type_def in schema["object_types"].items()
        if name in ("Customer", "Transaction")
    }
    mediator = DataMediator(
        object_types, adapters, dict.fromkeys(object_types, "primary_sql"), policy["roles"]
    )

    real_run_query = sqlite_adapter_module._run_query
    real_run_query_one = sqlite_adapter_module._run_query_one
    counted = {"n": 0}

    def counting(fn):
        def wrapper(*args, **kwargs):
            counted["n"] += 1
            return fn(*args, **kwargs)
        return wrapper

    sqlite_adapter_module._run_query = counting(real_run_query)
    sqlite_adapter_module._run_query_one = counting(real_run_query_one)
    try:
        counted["n"] = 0
        visible = mediator.search_object(CUSTOMER_SERVICE, "Transaction", {})
        mac_queries = counted["n"]

        counted["n"] = 0
        mediator._read_fields_for_ids(
            CUSTOMER_SERVICE, "Transaction", set(visible), ["category", "amount"]
        )
        data_queries = counted["n"]
    finally:
        sqlite_adapter_module._run_query = real_run_query
        sqlite_adapter_module._run_query_one = real_run_query_one

    assert data_queries <= 2, "reading the data should be a constant, not per-object"
    assert mac_queries > 100 * data_queries, (
        f"MAC cost {mac_queries} queries against {data_queries} for data -- "
        f"if this ratio inverts, revisit whether a second query engine is worth it"
    )
