"""
Point 7 of the machinery audit: Search Around -- link traversal as a
real query primitive.

FOUNDRY'S PRECEDENT. Search Around is a first-class query type in their
Object Set Service: it "takes an incoming object set and runs a
secondary filter on another object set based on a certain property of
the incoming set." Asking "every transaction belonging to a us-west
customer" is one operation there, not one per customer.

WHAT ELYSIUM HAD. resolve_reverse_link() resolves links for ONE object.
The same question cost 907 SQL queries across 302 customers, measured
directly -- the N+1 pattern again, one layer above the one the sync
had.

THE SECURITY PROPERTY THAT MATTERS MOST, and the reason this is a
mediator method rather than a join. MAC is applied on BOTH sides: the
source set comes from search_object(), so a caller only traverses from
objects they can see, and every target id is then authorized
individually. Skipping either check would turn a link into a way
around the security boundary -- reaching an object by following a
reference to it, when reading it directly would have been denied.
"""

import sqlite3

import pytest
import yaml

from core.deployment_loader import _WRITE_ADAPTER_REGISTRY, _build_adapters
from core.intermediate_layer.auth import UserRecord
from core.ontology.link_types import expand_link_types
from core.ontology.mediator import DataMediator

FIXTURES = "tests/integration/fixtures/"
CUSTOMER_SERVICE = UserRecord(user_id="u1", security_value="us-west", role_name="customer_service")
OTHER_REGION = UserRecord(user_id="u2", security_value="us-east", role_name="customer_service")


@pytest.fixture
def mediator(tmp_path):
    schema = yaml.safe_load(open(FIXTURES + "ontology_schema.yaml"))
    # Link fields are GENERATED from link_types at load; the raw
    # YAML no longer declares them (see core/ontology/link_types.py).
    schema["object_types"] = expand_link_types(
        schema.get("link_types", {}), schema["object_types"]
    )
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


def test_search_around_follows_a_reverse_link_across_a_whole_set(mediator):
    result = mediator.search_around(
        CUSTOMER_SERVICE, "Customer", {"region": "us-west"}, "transactions"
    )

    assert sorted(result) == [1, 2, 3, 4]


def test_search_around_matches_what_per_object_traversal_would_return(mediator):
    # The batch form must be a pure optimization -- same answer, fewer
    # queries. Compared against the per-object path rather than a
    # hardcoded list.
    source_ids = mediator.search_object(CUSTOMER_SERVICE, "Customer", {"region": "us-west"})
    one_at_a_time = []
    for source_id in source_ids:
        linked = mediator.get_field(CUSTOMER_SERVICE, "Customer", source_id, "transactions")
        one_at_a_time.extend(linked or [])

    batched = mediator.search_around(
        CUSTOMER_SERVICE, "Customer", {"region": "us-west"}, "transactions"
    )

    assert sorted(batched) == sorted(set(one_at_a_time))


def test_results_are_deduplicated(mediator):
    # Two source objects legitimately linking to the same target should
    # yield it once, not twice.
    result = mediator.search_around(
        CUSTOMER_SERVICE, "Customer", {"region": "us-west"}, "transactions"
    )

    assert len(result) == len(set(result))


def test_traversal_respects_mac_on_the_SOURCE_side(mediator):
    # A caller only traverses from objects they can see. us-east
    # customers are not in this caller's set, so their transactions are
    # not reachable through them.
    west = mediator.search_around(
        CUSTOMER_SERVICE, "Customer", {}, "transactions"
    )
    east = mediator.search_around(
        OTHER_REGION, "Customer", {}, "transactions"
    )

    assert west
    assert set(west) != set(east), "different MAC values must reach different objects"


def test_traversal_respects_mac_on_the_TARGET_side(mediator):
    # THE property that stops a link becoming a way around the security
    # boundary. Every id returned must also be readable directly --
    # following a reference must never reveal what a direct read would
    # deny.
    result = mediator.search_around(
        CUSTOMER_SERVICE, "Customer", {"region": "us-west"}, "transactions"
    )

    for target_id in result:
        assert (
            mediator.get_field(CUSTOMER_SERVICE, "Transaction", target_id, "amount") is not None
        ), f"search_around returned {target_id!r}, which a direct read denies"


def test_an_ungranted_link_field_returns_nothing(mediator):
    # Uniform denial: the caller learns nothing about whether the field
    # exists, is a link, or is merely ungranted.
    assert mediator.search_around(
        CUSTOMER_SERVICE, "Customer", {}, "not_a_real_field"
    ) == []


def test_a_non_link_field_returns_nothing(mediator):
    assert mediator.search_around(CUSTOMER_SERVICE, "Customer", {}, "name") == []


def test_an_empty_source_set_traverses_nothing(mediator):
    assert mediator.search_around(
        CUSTOMER_SERVICE, "Customer", {"region": "nowhere"}, "transactions"
    ) == []


def test_traversal_is_batched_not_one_query_per_source_object(tmp_path):
    # Deliberately builds its OWN larger fixture rather than using the
    # shared one. A first version used the standard fixture's two
    # customers and PASSED against a deliberately un-batched
    # implementation -- with two sources, per-object traversal costs
    # the same as one batch. The regression is only visible at a size
    # where the two genuinely diverge, so the test creates one.
    schema = yaml.safe_load(open(FIXTURES + "ontology_schema.yaml"))
    # Link fields are GENERATED from link_types at load; the raw
    # YAML no longer declares them (see core/ontology/link_types.py).
    schema["object_types"] = expand_link_types(
        schema.get("link_types", {}), schema["object_types"]
    )
    policy = yaml.safe_load(open(FIXTURES + "policy.yaml"))

    db_path = tmp_path / "many.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(open(FIXTURES + "schema.sql").read())
    conn.executemany(
        "INSERT INTO customers VALUES (?, ?, ?, ?)",
        [(f"c{i}", f"Name {i}", "us-west", f"e{i}@example.com") for i in range(200)],
    )
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
    mediator = DataMediator(
        object_types, adapters, dict.fromkeys(object_types, "primary_sql"), policy["roles"]
    )

    # THE performance property. Measured before this existed: 302
    # customers cost 907 queries. Asserted as a DELTA against
    # search_object() alone, because that method's own per-object MAC
    # resolution is a real, pre-existing cost this inherits rather than
    # introduces (see ROADMAP.md's deferred list).
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
        source_ids = mediator.search_object(CUSTOMER_SERVICE, "Customer", {})
        search_only = counted["n"]

        counted["n"] = 0
        targets = mediator.search_around(CUSTOMER_SERVICE, "Customer", {}, "transactions")
        with_traversal = counted["n"]
    finally:
        sqlite_adapter_module._run_query = real_run_query
        sqlite_adapter_module._run_query_one = real_run_query_one

    # The traversal itself is ONE query; the rest is per-target MAC,
    # which is bounded by the number of TARGETS, never by the number of
    # source objects traversed from.
    # ONE query for the traversal itself, plus per-TARGET MAC. The
    # bound is deliberately on targets, not sources: that is exactly
    # the claim -- cost scales with what you find, never with how many
    # objects you traversed from. (Corrected after a first version
    # asserted the source bound and failed on a fixture with more
    # targets than sources.)
    added = with_traversal - search_only
    mac_per_target = 3
    assert added <= 1 + len(targets) * mac_per_target, (
        f"traversal added {added} queries for {len(targets)} targets "
        f"-- should not scale with the {len(source_ids)} source objects"
    )
