"""
Point 9: batched security-value resolution.

THE MEASURED PROBLEM. check_access() resolved each object's security
value individually, and a via_field chain added a read per hop.
Profiling an aggregate over 20,000 objects: 6.25s total, 6.10s of it
in check_access(), 40,020 SQL queries. Point 8 measured this and
concluded no query engine could help, because the bottleneck was
authorization rather than data access.

THE FIX. A security chain is a walk over object TYPES, not over
objects: every Transaction resolves through Customer, so the whole set
needs one read of Transaction's via_field and one read of Customer's
security field, regardless of how many objects there are.
_prefetch_security_values() walks the chain level by level, reading
each level in bulk. Measured after: 40,020 queries to 3, 6.25s to
0.49s.

WHAT IS DELIBERATELY UNCHANGED, because correctness matters more than
speed here. check_access() is untouched -- same call, same order, same
audit logging, per object. The batch only pre-populates a cache that
_get_security_value() already reads; a cache MISS falls through to the
original per-object path unchanged. A security check that took a
different route when batched would be a genuinely different check.

The tests below therefore assert correctness FIRST -- that batching
changes no authorization decision -- and performance second.
"""

import sqlite3

import pytest
import yaml

from core.deployment_loader import _WRITE_ADAPTER_REGISTRY, _build_adapters
from core.intermediate_layer.auth import UserRecord
from core.ontology.link_types import expand_link_types
from core.ontology.mediator import DataMediator

FIXTURES = "tests/integration/fixtures/"
WEST = UserRecord(user_id="u1", security_value="us-west", role_name="customer_service")
EAST = UserRecord(user_id="u2", security_value="us-east", role_name="customer_service")


def _mediator(tmp_path, extra_transactions=0):
    schema = yaml.safe_load(open(FIXTURES + "ontology_schema.yaml"))
    # Link fields are GENERATED from link_types at load; the raw
    # YAML no longer declares them (see core/ontology/link_types.py).
    schema["object_types"] = expand_link_types(
        schema.get("link_types", {}), schema["object_types"]
    )
    policy = yaml.safe_load(open(FIXTURES + "policy.yaml"))

    tmp_path.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "business.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(open(FIXTURES + "schema.sql").read())
    if extra_transactions:
        conn.executemany(
            "INSERT INTO transactions (customer_id, amount, currency, category, "
            "transaction_date) VALUES (?, ?, ?, ?, ?)",
            [("cust_001", i * 1.5, "USD", "bulk", "2024-01-01") for i in range(extra_transactions)],
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
    return DataMediator(
        object_types, adapters, dict.fromkeys(object_types, "primary_sql"), policy["roles"]
    )


@pytest.fixture
def mediator(tmp_path):
    return _mediator(tmp_path)


# --- Correctness first -------------------------------------------------


def test_batching_returns_the_same_objects_as_the_unbatched_path(tmp_path):
    # THE property that matters most. Compared against the ORIGINAL
    # per-object resolution, reached by disabling the prefetch, rather
    # than against a hardcoded list -- so this genuinely proves
    # equivalence rather than restating today's answer.
    mediator = _mediator(tmp_path, extra_transactions=50)

    batched = mediator.search_object(WEST, "Transaction", {})

    mediator._prefetch_security_values = lambda object_type, object_ids: None
    mediator._security_value_cache.clear()
    mediator._security_link_cache.clear()
    unbatched = mediator.search_object(WEST, "Transaction", {})

    assert sorted(map(str, batched)) == sorted(map(str, unbatched))
    assert batched, "fixture should return something for this to be meaningful"


def test_batching_still_denies_what_mac_denies(tmp_path):
    # A faster authorization check that authorizes MORE is a security
    # regression, not an optimization. Two users with different MAC
    # values must still see genuinely different sets.
    mediator = _mediator(tmp_path, extra_transactions=20)

    west = set(map(str, mediator.search_object(WEST, "Transaction", {})))
    east = set(map(str, mediator.search_object(EAST, "Transaction", {})))

    assert west
    assert west != east
    assert not (west & east), "no object should be visible to both regions here"


def test_a_cache_miss_falls_through_to_the_per_object_path(mediator):
    # Correctness must never depend on the cache being warm. A direct
    # get_field() with no prefetch at all still resolves security
    # correctly.
    mediator._security_value_cache.clear()
    mediator._security_link_cache.clear()

    assert mediator.get_field(WEST, "Customer", "cust_001", "name") is not None
    assert mediator.get_field(EAST, "Customer", "cust_001", "name") is None


def test_the_cache_is_cleared_between_operations(tmp_path):
    # A security value that changed between requests must never be
    # served stale.
    #
    # The case this actually guards is subtler than it first appears,
    # and a first version of this test passed against a deliberately
    # removed clear() -- worth recording. Each prefetch OVERWRITES
    # every key it fetches, so an object re-fetched by the next
    # operation is refreshed regardless. The clear matters for an
    # object cached by one operation and NOT re-fetched by the next:
    # without it, that stale value would survive indefinitely and be
    # served to a later direct read.
    mediator = _mediator(tmp_path)
    mediator.search_object(WEST, "Customer", {})
    assert mediator._security_value_cache, "prefetch should have populated something"

    conn = sqlite3.connect(mediator.adapters["primary_sql"].db_path)
    conn.execute("UPDATE customers SET region = 'us-east' WHERE customer_id = 'cust_001'")
    conn.commit()
    conn.close()

    # An operation that prefetches NOTHING -- cust_001 is not in its
    # result set, so nothing overwrites the stale entry.
    mediator.search_object(WEST, "Customer", {"region": "nowhere"})

    # The now-us-east customer must be denied to this us-west caller.
    assert mediator.get_field(WEST, "Customer", "cust_001", "name") is None, (
        "a stale cached security value was served after the row changed"
    )


def test_a_failing_prefetch_does_not_break_the_read(mediator, monkeypatch):
    # The prefetch is a cache warmer. If a bulk read fails for any
    # reason, every caller must still get the correct answer from the
    # per-object path -- slower, but never wrong and never an error.
    def exploding(*args, **kwargs):
        raise RuntimeError("bulk read unavailable")

    monkeypatch.setattr(mediator, "_read_field_for_ids", exploding)

    assert mediator.search_object(WEST, "Customer", {})


def test_an_object_with_an_unresolvable_security_value_stays_denied(tmp_path):
    # A row whose via_field points nowhere has no security value, and
    # must be denied rather than defaulting to visible.
    mediator = _mediator(tmp_path)
    conn = sqlite3.connect(mediator.adapters["primary_sql"].db_path)
    conn.execute(
        "INSERT INTO transactions (customer_id, amount, currency, category, transaction_date) "
        "VALUES ('does_not_exist', 1.0, 'USD', 'orphan', '2024-01-01')"
    )
    conn.commit()
    orphan_id = conn.execute("SELECT max(transaction_id) FROM transactions").fetchone()[0]
    conn.close()

    visible = set(map(str, mediator.search_object(WEST, "Transaction", {})))

    assert str(orphan_id) not in visible


# --- Performance second ------------------------------------------------


def test_security_resolution_scales_with_chain_depth_not_set_size(tmp_path):
    # THE performance property. Measured before this existed: 20,000
    # objects cost 40,020 queries. Transaction resolves via Customer,
    # so the whole set needs one read per LEVEL -- two -- however many
    # objects there are.
    #
    # Asserted by comparing two genuinely different set sizes rather
    # than against a fixed number: what must hold is that the count
    # does not GROW, which a single measurement cannot show.
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
        small = _mediator(tmp_path / "small", extra_transactions=10)
        counted["n"] = 0
        small_ids = small.search_object(WEST, "Transaction", {})
        small_queries = counted["n"]

        large = _mediator(tmp_path / "large", extra_transactions=500)
        counted["n"] = 0
        large_ids = large.search_object(WEST, "Transaction", {})
        large_queries = counted["n"]
    finally:
        sqlite_adapter_module._run_query = real_run_query
        sqlite_adapter_module._run_query_one = real_run_query_one

    assert len(large_ids) > len(small_ids) * 5, "the two sets must genuinely differ in size"
    assert large_queries == small_queries, (
        f"{len(small_ids)} objects cost {small_queries} queries but "
        f"{len(large_ids)} cost {large_queries} -- security resolution is still per-object"
    )


# --- The cache under concurrent requests ---------------------------------
#
# The cache lives on a DataMediator shared across requests. The
# argument for that being safe -- a security value is a property of the
# OBJECT, not the caller, so a cross-request hit returns the same
# correct answer -- was written down and never tested.
#
# It was also INCOMPLETE. It reasoned about whether the cached VALUE is
# right and said nothing about whether the lookup itself can fail. The
# original code was `if key in cache: return cache[key]`, and another
# request's prefetch clearing between those two lines raises KeyError.
# Confirmed by forcing that exact interleaving; the GIL makes it rare,
# not impossible.


def test_concurrent_requests_from_different_users_get_their_own_answers(tmp_path):
    # THE property the shared cache rests on. Two users hammering one
    # mediator must each see only their own objects, however the cache
    # interleaves between them.
    import threading

    mediator = _mediator(tmp_path, extra_transactions=40)
    results: dict = {"west": [], "east": [], "errors": []}
    stop = threading.Barrier(2)

    def hammer(user, key):
        try:
            stop.wait()
            for _ in range(25):
                results[key].append(tuple(sorted(map(str, mediator.search_object(user, "Transaction", {})))))
        except Exception as exc:
            results["errors"].append(f"{type(exc).__name__}: {exc}")

    threads = [
        threading.Thread(target=hammer, args=(WEST, "west")),
        threading.Thread(target=hammer, args=(EAST, "east")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results["errors"] == [], f"concurrent access raised: {results['errors']}"
    # Every one of a user's reads returned the SAME set -- no request
    # ever saw the other user's cache bleed into its answer.
    assert len(set(results["west"])) == 1
    assert len(set(results["east"])) == 1
    assert results["west"][0] != results["east"][0]


def test_a_cache_cleared_mid_lookup_does_not_raise(tmp_path):
    # The check-then-get race, FORCED rather than hoped for. The GIL
    # makes this interleaving rare, so a probabilistic test passes
    # against the broken code -- which is exactly how it went
    # unnoticed. Three attempts at provoking it by timing found
    # nothing; forcing the order found it immediately.
    import threading

    checked = threading.Event()

    class RacingCache(dict):
        """Signals that a lookup has begun, so a clear lands before it
        completes.

        Intercepts BOTH `in` and `.get`, because the two code shapes
        use different ones -- and a first version of this test hooked
        only `.get`, so the old check-then-get shape never signalled
        and the control passed against broken code. The whole point is
        to catch that shape.
        """

        def __contains__(self, key):
            present = super().__contains__(key)
            checked.set()
            cleared.wait(2)
            return present

        def get(self, key, default=None):
            checked.set()
            cleared.wait(2)
            return super().get(key, default)

    cleared = threading.Event()
    mediator = _mediator(tmp_path)
    mediator._security_value_cache = RacingCache(
        {("Customer", "cust_001"): "us-west"}
    )

    def clearer():
        checked.wait(2)
        mediator._security_value_cache.clear()
        cleared.set()

    thread = threading.Thread(target=clearer)
    thread.start()
    try:
        # Must not raise: the old `if key in cache: return cache[key]`
        # would have, because the key vanished between the two steps.
        mediator._get_security_value("Customer", "cust_001")
    finally:
        thread.join()


def test_a_cached_none_is_not_treated_as_a_cache_miss(tmp_path):
    # None is a REAL security value: the object has none, so it is
    # visible to nobody. A sentinel-less `.get()` would treat it as
    # absent, sending every such object down the slow path forever and
    # making a genuine None indistinguishable from no entry at all.
    mediator = _mediator(tmp_path)
    mediator._security_value_cache[("Customer", "phantom")] = None

    assert mediator._get_security_value("Customer", "phantom") is None


def test_the_cached_value_does_not_depend_on_who_populated_it(tmp_path):
    # The argument itself, finally asserted: a security value is a
    # property of the object. Whoever warmed the cache, the answer is
    # the same.
    mediator = _mediator(tmp_path)

    mediator.search_object(EAST, "Customer", {})
    east_warmed = mediator._get_security_value("Customer", "cust_001")

    mediator._security_value_cache.clear()
    mediator._security_link_cache.clear()
    mediator.search_object(WEST, "Customer", {})
    west_warmed = mediator._get_security_value("Customer", "cust_001")

    assert east_warmed == west_warmed
