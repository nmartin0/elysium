"""A question shows its steps as it goes (19 October).

On a CPU a question takes minutes, and Query said nothing until the end.
A client accepting NDJSON now gets each step as it is done -- the same
read-back sentences the answer ends with -- then one last line carrying
the status and body the plain route answers with. The answer itself is
not streamed: it is checked whole and shown whole (the owner, 19
October). Over HTTP, with the model scripted through the same patch as
test_api.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.mocked_llm

SEARCH = {"step": "search_object", "object_type": "Customer", "filter": {"name": "Ada Okafor"}}
EMAIL = {"step": "get_field", "object_type": "Customer", "object_id": "cust_001",
         "field_name": "email"}


def _login(client, role="customer_service"):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", role)
    response = client.post("/api/login", json={"username": "alice", "password": "correct-pw"})
    assert response.status_code == 204, response.text


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("elysium_csrf")}


def _scripted(steps, during=None):
    """Takes these steps in order, then finishes, then answers. `during`
    runs while the model is writing call n: {n: callable}."""
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs.get("json") or {})
        index = len(calls) - 1
        if during and index in during:
            during[index]()
        if index < len(steps):
            content = json.dumps(steps[index])
        elif index == len(steps):
            content = json.dumps({"step": "finish"})
        else:
            content = "Ada Okafor's email is ada.okafor@example.com [R1]."
        response = MagicMock()
        response.json.return_value = {"message": {"content": content}}
        response.raise_for_status.return_value = None
        return response
    return fake_post


def _stream(client, question, steps, during=None):
    with patch("adapters.http_transport.post", side_effect=_scripted(steps, during)):
        response = client.post("/api/query", json={"query": question},
                               headers={**_csrf(client), "Accept": "application/x-ndjson"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def _plain(client, question, steps):
    with patch("adapters.http_transport.post", side_effect=_scripted(steps)):
        return client.post("/api/query", json={"query": question}, headers=_csrf(client))


def test_each_step_as_it_is_done_then_the_answer_whole(client):
    _login(client)
    events = _stream(client, "What is Ada's email?", [SEARCH, EMAIL])

    kinds = [event["type"] for event in events]
    assert kinds[-1] == "done" and "answering" in kinds
    steps = [event["lines"] for event in events if event["type"] == "steps"]
    # AS IT HAPPENS: the search shown before the read was made.
    assert steps[0] == ["Found 1 Customer whose Name is Ada Okafor"]
    assert len(steps[-1]) == 2
    done = events[-1]
    assert done["status"] == 200
    assert done["body"]["answer"].startswith("Ada Okafor's email is ada.okafor@example.com")
    # THE SAME BODY the plain route answers with.
    plain = _plain(client, "What is Ada's email?", [SEARCH, EMAIL]).json()
    assert done["body"]["read_back"] == plain["read_back"]
    assert set(done["body"]) == set(plain)


def test_the_answer_is_not_streamed(client):
    """Checked whole and shown whole: no line before the last carries it."""
    _login(client)
    events = _stream(client, "What is Ada's email?", [SEARCH, EMAIL])

    assert not any("ada.okafor@example.com" in json.dumps(event) for event in events[:-1])


def test_a_read_the_asker_may_not_make_is_not_shown(client):
    _login(client, role="customer_service_no_email")
    events = _stream(client, "What is Ada's email?", [SEARCH, EMAIL])

    shown = [line for event in events[:-1] for line in event.get("lines", [])]
    assert shown and not any("mail" in line for line in shown)


def test_nothing_is_shown_once_the_asker_has_changed(client):
    """Disabled while the model writes the first step: the step it then
    takes is not shown, and the question ends as it always has."""
    _login(client)
    directory = client.app.state.user_directory
    events = _stream(client, "What is Ada's email?", [SEARCH, EMAIL],
                     during={0: lambda: directory.disable_user("alice")})

    assert [event["type"] for event in events] == ["done"]
    assert events[0]["status"] == 409


def test_a_proposed_change_ends_the_stream_as_the_plain_route_would(client):
    _login(client, role="editor")
    propose = {"step": "propose_action", "action_type": "UpdateCustomerName",
               "parameters": {"customer_id": "cust_001", "new_name": "Ada O."}}
    events = _stream(client, "Rename Ada Okafor to Ada O.", [SEARCH, propose])

    done = events[-1]
    assert done["type"] == "done" and done["status"] == 202
    assert done["body"]["pending_write"]["action_type_name"] == "UpdateCustomerName"


def test_a_plain_request_is_answered_exactly_as_before(client):
    _login(client)
    response = _plain(client, "What is Ada's email?", [SEARCH, EMAIL])

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["answer"].startswith("Ada Okafor's email")


def test_a_refused_read_is_not_shown(client):
    """cust_004 is in the eu region, alice us-west: the read returns None,
    exactly as a NULL would. Showing "Read Name of Customer cust_004" would
    say the agent was refused something -- what uniform denial exists not
    to say -- so each step is shown from what synthesis is given."""
    _login(client)
    name = {"step": "get_field", "object_type": "Customer", "object_id": "cust_004",
            "field_name": "name"}
    events = _stream(client, "What is cust_004 called?", [SEARCH, name])

    shown = [line for event in events[:-1] for line in event.get("lines", [])]
    assert shown, "the search itself is still shown"
    assert not any("cust_004" in line for line in shown)



def test_leaving_partway_ends_the_question_its_own_way(monkeypatch):
    """Found in a browser: stopping by cancelling the question from outside
    ended the run but skipped its `query_cancelled` entry. Leaving now sets
    the question's own cancel events, so it ends as a left question always
    has -- stopped by the loop, and audited by the route.

    Driven on the stream's generator itself: the test client reads a whole
    body before it closes, so it never shows the server a disconnect."""
    import asyncio
    import threading

    import api.routes as routes

    seen = {}

    async def answering(body, request, current_user, progress=None):
        cancel = threading.Event()
        progress.watch(cancel)
        progress._send({"type": "steps", "lines": ["Found 1 Customer"]})
        while not cancel.is_set():
            await asyncio.sleep(0.01)
        seen["ended_by_its_own_event"] = True
        raise routes.HTTPException(status_code=499, detail="Client disconnected")

    monkeypatch.setattr(routes, "_answer_query", answering)

    async def leave_after_the_first_line():
        response = routes._streamed_query(None, None, None)
        lines = response.body_iterator
        first = await lines.__anext__()
        await lines.aclose()   # what a disconnect does to the generator
        for _ in range(100):
            if "ended_by_its_own_event" in seen:
                break
            await asyncio.sleep(0.01)
        return first

    first = asyncio.run(leave_after_the_first_line())

    assert json.loads(first)["type"] == "steps"
    assert seen.get("ended_by_its_own_event"), "the question was not stopped through its own event"


def test_an_event_watched_after_leaving_is_set_at_once():
    import threading

    from api.routes import _QueryProgress

    progress = _QueryProgress(None, None)
    progress.left()
    late = threading.Event()
    progress.watch(late)

    assert late.is_set()


def test_a_model_that_cannot_be_reached_is_the_last_line_not_a_crash(client):
    """No model running (found in a browser, 26 October). The stream's 200
    is already sent, so the 503 the plain route gives cannot be: the
    question's status is the last line. It used to escape the task, be
    raised again in the generator and cut the response, so the screen read
    "Could not reach the server" and the server logged a traceback."""
    import requests

    _login(client)
    with patch("adapters.http_transport.post",
               side_effect=requests.ConnectionError("http://localhost:11434 refused")):
        response = client.post("/api/query", json={"query": "What is Ada's email?"},
                               headers={**_csrf(client), "Accept": "application/x-ndjson"})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    done = events[-1]
    assert done["type"] == "done" and done["status"] == 503
    assert "cannot reach its model" in done["body"]["detail"]
    # THE KIND, NOT THE MESSAGE: no host or port.
    assert "11434" not in json.dumps(events) and "localhost" not in json.dumps(events)
    # And it is what the plain route says.
    plain = _plain_unreachable(client)
    assert plain.status_code == 503 and plain.json()["detail"] == done["body"]["detail"]


def _plain_unreachable(client):
    import requests

    with patch("adapters.http_transport.post", side_effect=requests.ConnectionError("refused")):
        return client.post("/api/query", json={"query": "What is Ada's email?"}, headers=_csrf(client))
