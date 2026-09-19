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
from tests.integration.test_api import _login  # noqa: F401


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
