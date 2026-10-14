"""
A question that stopped for an approval is answered once it is approved
(WIRED-2 / AL-12, decided by the owner 14 Oct: the asker is notified).

Before: the agent proposed a write, /query answered 202, and the
question was never answered -- AgentLoop.resume existed and nothing
called it. Now the paused question is kept with the write, finished in
the background when the write is approved, and the answer arrives as
the asker's own notification. A declined write ends the question with a
notice saying so.

The model is scripted through the same HTTP patch test_api uses, so the
whole route path runs: /query, the confirm route, the background resume,
synthesis, the notification store, and /notifications.
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.mocked_llm

PROPOSE = {"step": "propose_action", "action_type": "UpdateCustomerName",
           "parameters": {"customer_id": "cust_002", "new_name": "Bram F. Feldman"}}


def _login(client, username, password, role):
    client.app.state.user_directory.create_user(username, password, "us-west", role)
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 204, response.text


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("elysium_csrf")}


def _model(steps):
    """Each agent call takes the next scripted step; anything after the
    script is synthesis, which answers in prose."""
    calls = {"n": 0}

    def fake_post(*args, **kwargs):
        response = MagicMock()
        if calls["n"] < len(steps):
            content = json.dumps(steps[calls["n"]])
        else:
            content = "Bram's name is now Bram F. Feldman."
        response.json.return_value = {"message": {"content": content}}
        response.raise_for_status.return_value = None
        calls["n"] += 1
        return response
    return fake_post


def _answers(client, wait=10.0):
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        found = [n for n in client.get("/api/notifications").json()["notifications"]
                 if n["kind"] == "query_answer"]
        if found:
            return found
        time.sleep(0.1)
    return []


def _ask_and_decide(client, approved):
    _login(client, "alice", "correct-pw", "editor")
    with patch("adapters.http_transport.post",
               side_effect=_model([PROPOSE, {"step": "finish"}])):
        asked = client.post("/api/query", json={"query": "rename Bram, then tell me his name"},
                            headers=_csrf(client))
        assert asked.status_code == 202, asked.text
        write_id = asked.json()["pending_write"]["id"]
        decided = client.post(f"/api/writes/{write_id}/confirm", json={"approved": approved},
                              headers=_csrf(client))
        assert decided.status_code == 200, decided.text
        return _answers(client)


def test_after_approval_the_asker_is_sent_the_answer(client):
    (answer,) = _ask_and_decide(client, approved=True)

    assert answer["summary"] == "Answer to: rename Bram, then tell me his name"
    assert answer["detail"] == "Bram's name is now Bram F. Feldman."


def test_a_declined_write_says_so_instead(client):
    (notice,) = _ask_and_decide(client, approved=False)

    assert notice["summary"].startswith("The change your question proposed was declined")


def test_the_question_is_finished_once(client):
    """take() removes it: a second decision path finds nothing."""
    _ask_and_decide(client, approved=True)
    from core.paused_queries import PausedQueryStore

    store = PausedQueryStore(client.app.state.runtime_paths.data_dir / "paused_queries.db")
    with store._connection() as conn:
        assert conn.execute("SELECT count(*) FROM paused_queries").fetchone()[0] == 0
