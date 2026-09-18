"""
A Browse request can be asked what it read.

THE WHOLE CHAIN ALREADY EXISTED. RequestContext carries an id,
check_access stamps it on every audit line, entries_for_request reads
them back, and GET /requests/{id}/trace serves them -- scoped to the
caller's own requests.

WHAT WAS MISSING WAS THE HANDLE. Query returned its request_id and its
UI showed the trace. Browse created no context, then created one and
did not return it -- so the trace was recorded and unreachable, which
is the same as absent for anyone trying to use it.
"""

from tests.integration.test_api import _csrf_headers, _login  # noqa: F401


def test_a_search_hands_back_the_id_of_its_own_trace(client):
    client.app.state.user_directory.create_user(
        "alice", "correct-pw", "us-west", "editor")
    _login(client, "alice", "correct-pw")

    search = client.get("/api/objects/Customer/search?q=")
    assert search.status_code == 200
    request_id = search.json()["request_id"]
    assert request_id

    trace = client.get(f"/api/requests/{request_id}/trace")

    assert trace.status_code == 200
    assert len(trace.json()) > 0


def test_a_detail_view_hands_back_its_own(client):
    client.app.state.user_directory.create_user(
        "alice", "correct-pw", "us-west", "editor")
    _login(client, "alice", "correct-pw")

    detail = client.get("/api/objects/Customer/cust_002")
    request_id = detail.json()["request_id"]

    trace = client.get(f"/api/requests/{request_id}/trace")

    assert trace.status_code == 200
    assert len(trace.json()) > 0


def test_one_request_s_trace_does_not_include_another_s(client):
    """THE CONTROL THAT MATTERS. A trace returning everything answers
    "what did this request touch" with "everything", which is the same
    as not answering."""
    client.app.state.user_directory.create_user(
        "alice", "correct-pw", "us-west", "editor")
    _login(client, "alice", "correct-pw")

    first = client.get("/api/objects/Customer/cust_002").json()["request_id"]
    second = client.get("/api/objects/Customer/cust_001").json()["request_id"]

    assert first != second
    objects_in_first = {
        entry.get("object_id") for entry in
        client.get(f"/api/requests/{first}/trace").json()
    }

    assert "cust_001" not in objects_in_first


def test_another_user_cannot_read_your_trace(client):
    """SCOPED TO THE CALLER, which the endpoint already enforced --
    pinned here because a correlation handle returned in a response
    body is the kind of thing that looks like a capability."""
    client.app.state.user_directory.create_user(
        "alice", "correct-pw", "us-west", "editor")
    client.app.state.user_directory.create_user(
        "mallory", "other-pw", "us-west", "editor")

    _login(client, "alice", "correct-pw")
    request_id = client.get("/api/objects/Customer/cust_002").json()["request_id"]

    _login(client, "mallory", "other-pw")
    trace = client.get(f"/api/requests/{request_id}/trace")

    assert trace.json() == []
