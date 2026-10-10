"""
A truncated search says so.

THE MEDIATOR LOGS IT AND THE CALLER COULD NOT SEE IT: a user got a
short list and no reason. That is the worst shape for a limit --
indistinguishable from "that is all there is".

"WE STOPPED LOOKING", NEVER "THERE IS MORE FOR YOU". Where MAC could
not be pushed into the query, the ceiling bounds a SCAN whose
survivors are filtered afterwards, so the rows beyond it might all
have been invisible to this user anyway. The flag reports rows
SCANNED, which is how governed query engines report the same thing.
"""

from unittest.mock import patch

import core.ontology.mediator as mediator_module
from tests.integration.test_api import _csrf_headers, _login  # noqa: F401


def test_an_ordinary_search_is_not_truncated(client):
    client.app.state.user_directory.create_user(
        "alice", "correct-pw", "us-west", "editor")
    _login(client, "alice", "correct-pw")

    body = client.get("/api/objects/Customer/search?q=").json()

    assert body["scan_truncated"] is False


def test_a_search_that_hits_the_ceiling_says_so(client):
    """THE CONTROL IS THE TEST ABOVE. A flag that were always true
    would pass this one and fail that one, which is why both exist."""
    client.app.state.user_directory.create_user(
        "alice", "correct-pw", "us-west", "editor")
    _login(client, "alice", "correct-pw")

    with patch.object(mediator_module, "MAX_SEARCH_SCAN", 1):
        body = client.get("/api/objects/Customer/search?q=").json()

    assert body["scan_truncated"] is True


def test_results_are_still_served_when_truncated(client):
    """TRUNCATION IS NOT FAILURE. A capped search returns what it
    found; refusing would turn a slow query into a broken one."""
    client.app.state.user_directory.create_user(
        "alice", "correct-pw", "us-west", "editor")
    _login(client, "alice", "correct-pw")

    with patch.object(mediator_module, "MAX_SEARCH_SCAN", 1):
        body = client.get("/api/objects/Customer/search?q=").json()

    assert body["results"]


# --- A COUNT AND AN AGGREGATE SAY IT TOO -------------------------------
#
# WHAT WAS WRONG. search_object() records the ceiling only `if outcome
# is not None`, and count_objects() and aggregate_by_field() both
# called it without one -- so the flag existed, the search path carried
# it, and the two paths that turn a set into a NUMBER dropped it. A
# count or a facet came back short with nothing saying so.
#
# WHY IT IS WORSE ON THESE TWO than on the search above. A truncated
# search returns a short LIST, and a short list looks short. A
# truncated count returns a confident integer; a truncated aggregate
# draws a bar. Nothing about a bar labelled 3,000 suggests it should
# have read 4,000.
#
# IT CANNOT BE A LEAK, and that is why it survived: every id still
# passes check_access() individually, so the error is always downward.
# A correctness and trust defect rather than a confidentiality one.
#
# THE SAME PATCH THE SEARCH TESTS USE, for the same reason: a fixture
# with 10,001 rows would make this file slow and the number would be
# the thing under test rather than the plumbing.


def _as_customer_service(client):
    client.app.state.user_directory.create_user(
        "alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")


def _post(client, path, body):
    # COUNT AND AGGREGATE ARE POSTs -- a structured criteria object
    # will not fit in a query string -- so they are CSRF-gated like any
    # other write-shaped request, despite being reads.
    return client.post(path, json=body, headers=_csrf_headers(client))


def test_an_ordinary_count_is_not_truncated(client):
    _as_customer_service(client)

    body = _post(client, "/api/objects/Customer/count", {"criteria": {}}).json()

    assert body["scan_truncated"] is False


def test_a_count_that_hits_the_ceiling_says_so(client):
    """THE CONTROL IS THE TEST ABOVE -- a flag hard-coded true would
    pass here and fail there."""
    _as_customer_service(client)

    with patch.object(mediator_module, "MAX_SEARCH_SCAN", 1):
        body = _post(client, "/api/objects/Customer/count", {"criteria": {}}).json()

    assert body["scan_truncated"] is True


def test_a_truncated_count_still_returns_the_number_it_reached(client):
    """A FLOOR IS USEFUL; nothing is not. The same judgement the
    search above makes -- report what was found and say it is partial,
    rather than refusing."""
    _as_customer_service(client)

    with patch.object(mediator_module, "MAX_SEARCH_SCAN", 1):
        body = _post(client, "/api/objects/Customer/count", {"criteria": {}}).json()

    assert body["count"] >= 1


def test_an_ordinary_aggregate_is_not_truncated(client):
    _as_customer_service(client)

    body = _post(client, "/api/objects/Transaction/aggregate",
                 {"criteria": {}, "aggregate": "count", "group_by": "category"}).json()

    assert body["scan_truncated"] is False
    assert body["results"], "the control needs a real aggregate, not an empty one"


def test_an_aggregate_that_hits_the_ceiling_says_so(client):
    _as_customer_service(client)

    with patch.object(mediator_module, "MAX_SEARCH_SCAN", 1):
        body = _post(client, "/api/objects/Transaction/aggregate",
                     {"criteria": {}, "aggregate": "count", "group_by": "category"}).json()

    assert body["scan_truncated"] is True


def test_a_truncated_aggregate_reports_fewer_than_the_whole(client):
    """THE DEFECT, STATED AS A NUMBER. This is the pair that shows why
    the flag is needed at all: the same request, same user, same
    filters, returns two different totals depending on a ceiling the
    caller never set -- and before the flag, the two were
    indistinguishable in the response."""
    _as_customer_service(client)
    body = {"criteria": {}, "aggregate": "count"}

    whole = _post(client, "/api/objects/Transaction/aggregate", body).json()
    with patch.object(mediator_module, "MAX_SEARCH_SCAN", 1):
        capped = _post(client, "/api/objects/Transaction/aggregate", body).json()

    assert capped["results"][""] < whole["results"][""]
    assert whole["scan_truncated"] is False
    assert capped["scan_truncated"] is True
