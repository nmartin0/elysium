"""
The security cache holds one search, not one deployment's history.

THE ROADMAP SAID OTHERWISE, and measuring contradicted it. The entry
read: "cleared only at the start of a bulk prefetch, and otherwise
accumulate one entry per object ever security-checked... a long-running
deployment reading many distinct objects grows memory monotonically."

MEASURED: twenty-one identical searches leave the cache exactly as one
search does, and a search of a different type REPLACES it rather than
adding to it. Both writes live inside `_prefetch_security_values`,
which clears first.

SO THE BOUND IS ONE SEARCH'S CANDIDATE SET, which the scan ceiling
capped in the previous phase-0.2 commit. Measured against a patched
ceiling: 2 gives 3 entries, 1 gives 2.

THIS FILE EXISTS BECAUSE THAT BOUND IS INCIDENTAL. Nothing declared
it, and a future prefetch that forgot to clear -- or a write added
outside it -- would restore the unbounded growth the roadmap feared,
with no test objecting.
"""

from unittest.mock import patch

import pytest

import core.ontology.mediator as mediator_module
from core.intermediate_layer.auth import UserRecord


@pytest.fixture
def mediator(synced_deployment):
    from core.deployment_loader import build_generation

    # E-08: a deployment of its own, not the developer's.
    paths = synced_deployment
    return build_generation(
        paths.config_dir, paths.data_dir, paths.log_dir,
    ).mediator


@pytest.fixture
def user():
    return UserRecord("u", "us-west", "customer_service")


def _cache_size(mediator):
    """The ACTIVE SCOPE's cache -- there is no mediator-level one now
    (004-F6). These tests run their searches inside one scope, as a long
    request or an agent query does, because the bound still matters
    there: many searches, one scope."""
    values, links = mediator_module._SECURITY_CACHE.get()
    return len(values) + len(links)


def test_repeated_searches_do_not_accumulate(mediator, user):
    with mediator_module.security_cache_scope():
        mediator.search_object(user, "Transaction", [])
        after_one = _cache_size(mediator)

        for _ in range(20):
            mediator.search_object(user, "Transaction", [])

        assert _cache_size(mediator) == after_one


def test_a_different_type_replaces_rather_than_adds(mediator, user):
    """REPLACED, NOT MERGED: the prefetch clears before it fills, so
    the cache describes the most recent search and nothing else.

    A FIRST VERSION COMPARED SIZES and a control removing the clear
    did not fail it -- with the clear gone the two searches' entries
    simply add up, and any arithmetic on totals still looked
    plausible. The keys carry their object type, so asking WHOSE
    entries these are answers it exactly.
    """
    with mediator_module.security_cache_scope():
        mediator.search_object(user, "Transaction", [])
        mediator.search_object(user, "Customer", [])

        values, links = mediator_module._SECURITY_CACHE.get()
        keys = [*values, *links]
    assert keys
    assert not [key for key in keys if key[0] == "Transaction"]


def test_the_cache_is_bounded_by_the_scan_ceiling(mediator, user):
    """THE PROPERTY THAT MATTERS, and the reason phase 0.3 needed no
    code: whatever bounds a search's candidate set bounds this too."""
    with patch.object(mediator_module, "MAX_SEARCH_SCAN", 1), \
            mediator_module.security_cache_scope():
        mediator.search_object(user, "Transaction", [])
        small = _cache_size(mediator)

    with patch.object(mediator_module, "MAX_SEARCH_SCAN", 10_000), \
            mediator_module.security_cache_scope():
        mediator.search_object(user, "Transaction", [])
        large = _cache_size(mediator)

    assert small < large


def test_every_write_happens_inside_the_prefetch(mediator):
    """A SOURCE-LEVEL TRIPWIRE, because the bound is INCIDENTAL.

    Both writes are inside `_prefetch_security_values`, which clears
    first. A write added anywhere else would restore unbounded growth
    and every behavioural test above would still pass, because they
    exercise the search path rather than the new one.
    """
    import inspect

    source = inspect.getsource(mediator_module.DataMediator)
    prefetch = inspect.getsource(
        mediator_module.DataMediator._prefetch_security_values,
    )

    # The writes are `value_cache[...] =` and `link_cache[...] =` on the
    # SCOPE's dicts now; the property -- every write inside the prefetch,
    # which clears first -- is unchanged.
    for cache in ("value_cache[", "link_cache["):
        assert source.count(cache) == prefetch.count(cache), (
            f"{cache} is written outside _prefetch_security_values, "
            f"which clears first -- the cache's bound depends on that."
        )
