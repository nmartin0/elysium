"""POST /api/help -- the help assistant (core/agent/help_assistant.py).

THE MODEL IS A RECORDER here: what matters is what the assistant is
TOLD, because everything it is told it may repeat. Every assertion is
about the prompt that reached the model -- the caller's own screens,
types and grants, and nothing else.
"""

import dataclasses

from core.llm.interface import LLMUnavailable


class _Recorder:
    def __init__(self, reply="Use Browse.", fail=None):
        self.reply, self.fail, self.calls = reply, fail, []

    def chat(self, system_prompt, user_message, json_mode=False, temperature=None, *,
             deadline=None, usage=None):
        self.calls.append((system_prompt, user_message))
        if self.fail:
            raise self.fail
        return self.reply


def _with_model(client, model):
    app = client.app
    app.state.generation = dataclasses.replace(app.state.generation, synthesis_client=model)
    return model


def _login(client, username, role, region="us-west"):
    client.app.state.user_directory.create_user(username, "pw", region, role)
    response = client.post("/api/login", json={"username": username, "password": "pw"})
    assert response.status_code == 204, response.text


def _ask(client, question, screen=None):
    return client.post("/api/help", json={"question": question, "screen": screen},
                       headers={"X-CSRF-Token": client.cookies.get("elysium_csrf")})


def test_it_answers(client):
    model = _with_model(client, _Recorder("Open Browse and choose Customer."))
    _login(client, "asker", "customer_service")

    response = _ask(client, "How do I find a customer?", screen="Browse")

    assert response.status_code == 200
    assert response.json() == {"answer": "Open Browse and choose Customer."}
    assert model.calls[0][1] == "How do I find a customer?"
    assert "THE USER IS ON: Browse" in model.calls[0][0]


def test_it_is_told_only_what_the_caller_may_know(client):
    """The accountant reads Account and nothing else, and cannot open
    Admin. Neither Customer nor Admin may reach the prompt."""
    model = _with_model(client, _Recorder())
    _login(client, "counter", "accountant")

    _ask(client, "What can I see?")

    prompt = model.calls[0][0]
    assert "- Account:" in prompt
    assert "Customer" not in prompt
    assert "- Admin:" not in prompt


def test_it_is_never_given_a_value(client):
    """Names and types only: a help answer must not become a second
    read path. Ada's email is in the data this caller CAN read."""
    model = _with_model(client, _Recorder())
    _login(client, "valueless", "customer_service")

    _ask(client, "What is Ada's email?")

    assert "ada.okafor@example.com" not in model.calls[0][0]
    assert "Email (text)" in model.calls[0][0]


def test_a_field_known_but_unreadable_says_so(client):
    model = _with_model(client, _Recorder())
    _login(client, "peeker", "customer_service_sees_email_exists")

    _ask(client, "Why can't I see email?")

    assert "Email (text, value hidden)" in model.calls[0][0]


def test_a_screen_the_caller_cannot_open_is_not_named_as_theirs(client):
    """`screen` comes from the browser; one the caller cannot open is
    dropped rather than repeated to the model."""
    model = _with_model(client, _Recorder())
    _login(client, "nav", "customer_service")

    _ask(client, "help", screen="Admin")

    assert "THE USER IS ON" not in model.calls[0][0]


def test_an_empty_question_is_refused(client):
    _with_model(client, _Recorder())
    _login(client, "blank", "customer_service")

    assert _ask(client, "   ").status_code == 400


def test_an_unreachable_model_is_a_503_that_says_so(client):
    _with_model(client, _Recorder(fail=LLMUnavailable(
        "Could not reach the model at http://localhost:11434/api/chat")))
    _login(client, "offline", "customer_service")

    response = _ask(client, "How do I export?")

    assert response.status_code == 503
    assert "cannot reach its model" in response.json()["detail"]
    # NAMES, NEVER CONTENTS: the model's address is configuration.
    assert "11434" not in response.text


def test_it_needs_a_session(client):
    assert client.post("/api/help", json={"question": "hi"}).status_code in (401, 403)
