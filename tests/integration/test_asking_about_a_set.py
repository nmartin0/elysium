"""
Asking about the set on screen (DEV_UI 5.4).

Browse sends the set itself with the question -- its type, conditions
and text search -- and the agent receives the question with the set
said in words after it. The model is scripted through the same HTTP
patch as test_api, so the whole route runs.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.mocked_llm


def _login(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    response = client.post("/api/login", json={"username": "alice", "password": "correct-pw"})
    assert response.status_code == 204, response.text


def _recording_model():
    """Finishes at once, then answers; keeps every message it was sent."""
    seen = []

    def fake_post(*args, **kwargs):
        body = kwargs.get("json") or {}
        seen.append(json.dumps(body))
        response = MagicMock()
        content = json.dumps({"step": "finish"}) if len(seen) == 1 else "An answer."
        response.json.return_value = {"message": {"content": content}}
        response.raise_for_status.return_value = None
        return response
    return fake_post, seen


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("elysium_csrf")}


def test_the_agent_is_told_which_set_was_on_screen(client):
    _login(client)
    fake_post, seen = _recording_model()
    with patch("adapters.http_transport.post", side_effect=fake_post):
        response = client.post("/api/query", headers=_csrf(client), json={
            "query": "Which is largest?",
            "about": {"object_type": "Transaction",
                      "conditions": [{"field": "category", "operator": "in",
                                      "value": ["refund", "hardware"]}],
                      "text": ""}})

    assert response.status_code == 200, response.text
    assert "Which is largest?" in seen[0]
    assert "This question is about the Transaction objects whose Category is one of " \
           "refund, hardware." in seen[0]


def test_without_a_set_the_question_is_untouched(client):
    """THE CONTROL: Query's own questions say nothing about a set."""
    _login(client)
    fake_post, seen = _recording_model()
    with patch("adapters.http_transport.post", side_effect=fake_post):
        client.post("/api/query", headers=_csrf(client), json={"query": "Which is largest?"})

    assert "This question is about" not in seen[0]


def test_a_set_on_a_field_the_asker_cannot_read_is_refused_before_the_model(client):
    """Uniform denial, and no model call spent on it."""
    _login(client)
    fake_post, seen = _recording_model()
    with patch("adapters.http_transport.post", side_effect=fake_post):
        response = client.post("/api/query", headers=_csrf(client), json={
            "query": "Which?", "about": {"object_type": "Transaction", "conditions": [
                {"field": "no_such_field", "operator": "equals", "value": 1}]}})

    assert response.status_code == 400
    assert "Unknown set" in response.text
    assert seen == []


def test_a_model_that_cannot_be_reached_is_a_503_that_names_no_host(client):
    """Found in a browser: the panel read "Request failed (500)" with no
    model running. The adapter's own message names the model's host and
    port, which no caller is shown."""
    import requests

    _login(client)
    with patch("adapters.http_transport.post",
               side_effect=requests.ConnectionError("localhost:11434 refused")):
        response = client.post("/api/query", headers=_csrf(client), json={
            "query": "Which?", "about": {"object_type": "Transaction"}})

    assert response.status_code == 503, response.text
    assert "cannot reach its model" in response.json()["detail"]
    assert "11434" not in response.text and "localhost" not in response.text
