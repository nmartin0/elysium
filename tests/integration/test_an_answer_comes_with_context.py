"""An answer comes with how it was reached, where it leads, and what to
ask next -- over HTTP, with the model scripted through the same patch as
test_api, so the whole route runs against the fixture data."""

import json
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.mocked_llm


def _login(client, role="customer_service"):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", role)
    response = client.post("/api/login", json={"username": "alice", "password": "correct-pw"})
    assert response.status_code == 204, response.text


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("elysium_csrf")}


def _scripted(*steps):
    """Takes these steps in order, then finishes, then answers."""
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs.get("json") or {})
        index = len(calls) - 1
        if index < len(steps):
            content = json.dumps(steps[index])
        elif index == len(steps):
            content = json.dumps({"step": "finish"})
        else:
            content = "Ada Okafor is one customer."
        response = MagicMock()
        response.json.return_value = {"message": {"content": content}}
        response.raise_for_status.return_value = None
        return response
    return fake_post


def _ask(client, question, *steps):
    with patch("adapters.http_transport.post", side_effect=_scripted(*steps)):
        return client.post("/api/query", headers=_csrf(client), json={"query": question})


def test_the_question_is_read_back_as_what_was_done(client):
    _login(client)
    response = _ask(client, "Who is Ada Okafor?",
                    {"step": "search_object", "object_type": "Customer", "filter": {"name": "Ada Okafor"}})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["read_back"][0] == "Found 1 Customer whose Name is Ada Okafor"


def test_it_leads_to_the_object_it_was_about(client):
    _login(client)
    body = _ask(client, "Who is Ada Okafor?",
                {"step": "search_object", "object_type": "Customer", "filter": {"name": "Ada Okafor"}}).json()

    assert {"kind": "object", "object_type": "Customer", "object_id": "cust_001",
            "label": "Ada Okafor"}.items() <= body["doors"][0].items()


def test_and_suggests_whole_questions_about_it(client):
    _login(client)
    body = _ask(client, "Who is Ada Okafor?",
                {"step": "search_object", "object_type": "Customer", "filter": {"name": "Ada Okafor"}}).json()

    assert body["follow_ons"], "a named customer with links should suggest something"
    assert all("Ada Okafor" in question and question.endswith("?") for question in body["follow_ons"])


def test_a_field_the_asker_may_not_read_is_never_read_back(client):
    """customer_service_no_email cannot read email. The agent's schema
    omits it, so the model cannot ask -- and if it did, the refusal is
    None, which filter_real_data strips before anything here sees it."""
    _login(client, role="customer_service_no_email")
    response = _ask(client, "What is Ada's email?",
                    {"step": "search_object", "object_type": "Customer", "filter": {"name": "Ada Okafor"}},
                    {"step": "get_field", "object_type": "Customer", "object_id": "cust_001",
                     "field_name": "email"})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["read_back"], "the search itself should still be read back"
    assert not any("Email" in sentence or "email" in sentence for sentence in body.get("read_back", []))


def test_a_DENIED_read_is_never_read_back(client):
    """cust_004 is in the eu region; alice is us-west, so MAC refuses the
    read and it returns None -- exactly what a NULL returns. Reading it
    back as "Read Name of Customer cust_004" would say the agent was
    refused something, which uniform denial exists not to say. The
    route must build from filter_real_data, not from everything."""
    _login(client)
    response = _ask(client, "What is cust_004 called?",
                    {"step": "get_field", "object_type": "Customer", "object_id": "cust_004",
                     "field_name": "name"})
    assert response.status_code == 200, response.text
    body = response.json()

    assert not any("cust_004" in sentence for sentence in body["read_back"])
    assert not any(door.get("object_id") == "cust_004" for door in body["doors"])
