"""
A search-around cannot read more than the ceiling either.

PHASE 0.2 CAPPED THE SOURCE SIDE AND LEFT THE FAN-OUT OPEN.
`search_object` and `search_object_free_text` stop at
MAX_SEARCH_SCAN; `search_around` searched for sources, then followed
their links with no limit at all.

TEN THOUSAND SOURCES HOLDING A HUNDRED LINKS EACH IS A MILLION
TARGETS, and `check_access` writes one audit line per target.

MEASURED: an audit line costs about 11 microseconds, so a
million-target traversal spends ELEVEN SECONDS writing its own trail
before any data reaches the caller. ROADMAP.md profiled the same shape
at 200,000 objects:

    _io.open      1.21s   (200,006 calls -- audit logging)
    file close    0.71s
    SQL query     0.66s

That entry notes it "has now been wrong twice, each time because a fix
moved the bottleneck somewhere the previous profile could not see".
Phase 0.2 moved it a third time, out of the searches and into here.

THE TARGETS, NOT THE SOURCES. Capping sources further would answer a
different question wrongly -- somebody asking about ten customers with
a hundred transactions each wants all thousand, and the limit that
matters is on what comes back.
"""

from unittest.mock import patch

import pytest

import core.ontology.mediator as mediator_module
from core.intermediate_layer.auth import UserRecord
from core.ontology.mediator import SearchOutcome


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
    return UserRecord("debug", "us-west", "debug")


class TestTheFanOutIsBounded:
    def test_it_returns_no_more_than_the_ceiling(self, mediator, user):
        with patch.object(mediator_module, "MAX_SEARCH_SCAN", 2):
            targets = mediator.search_around(
                user, "Customer", [], "transactions",
            )

        assert len(targets) <= 2

    def test_a_smaller_ceiling_returns_less(self, mediator, user):
        """THE CONTROL THAT MATTERS. A cap that always returned
        everything would pass the test above whenever the fixture held
        fewer rows than the ceiling."""
        with patch.object(mediator_module, "MAX_SEARCH_SCAN", 1):
            one = mediator.search_around(user, "Customer", [], "transactions")
        with patch.object(mediator_module, "MAX_SEARCH_SCAN", 10_000):
            many = mediator.search_around(user, "Customer", [], "transactions")

        assert len(one) < len(many)


class TestItSaysSoWhenItStops:
    def test_a_truncated_traversal_reports_it(self, mediator, user):
        outcome = SearchOutcome()

        with patch.object(mediator_module, "MAX_SEARCH_SCAN", 1):
            mediator.search_around(
                user, "Customer", [], "transactions", outcome=outcome,
            )

        assert outcome.scan_truncated is True

    def test_an_untruncated_one_does_not(self, mediator, user):
        # A FLAG ALWAYS TRUE would pass the test above and tell a user
        # to narrow filters on every traversal they ever run.
        outcome = SearchOutcome()

        with patch.object(mediator_module, "MAX_SEARCH_SCAN", 10_000):
            mediator.search_around(
                user, "Customer", [], "transactions", outcome=outcome,
            )

        assert outcome.scan_truncated is False

    def test_the_outcome_is_optional(self, mediator, user):
        """CALLERS THAT DO NOT CARE PASS NOTHING, which is what makes
        this additive rather than a signature change every caller must
        absorb."""
        assert mediator.search_around(
            user, "Customer", [], "transactions",
        ) is not None
