"""
Integration tests for the api/ layer -- real FastAPI TestClient, real
core/auth/core/user_directory logic against an isolated temp credentials
database (swapped onto app.state at runtime; nothing about api/app.py
itself needs to change to make this possible). /query is the only
route needing the LLM -- mocked there the same way tests/integration/
already mocks Ollama's HTTP call elsewhere in this project.

NOT marked @pytest.mark.integration (unlike tests/integration/'s other
files) -- these don't need real Ollama running, only the mocked /query
case does, and that's isolated to its own test.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import api.app as app_module
from core.user_directory import create_user


@pytest.fixture
def client(tmp_path: Path):
    # Real app (real deployment/ config, real mediator) but an
    # ISOLATED credentials database -- swapped onto app.state, which
    # is read at request time, not baked in at import time.
    test_db_path = tmp_path / "credentials.db"
    app_module.app.state.credentials_db_path = test_db_path

    # A fresh, isolated roles dict for this test -- includes an
    # "admin" role with manage:users, which the real deployment's
    # policy.yaml doesn't necessarily grant to anyone.
    roles = dict(app_module.app.state.config.roles)
    roles["admin"] = {"allowed_actions": frozenset(["manage:users"])}
    roles.setdefault("customer_service", {"allowed_actions": frozenset()})
    app_module.app.state.config.roles = roles

    return TestClient(app_module.app)


def _login(client, username, password):
    return client.post("/login", json={"username": username, "password": password})


def test_login_wrong_password_and_nonexistent_username_are_identical(client):
    db_path = app_module.app.state.credentials_db_path
    roles = app_module.app.state.config.roles
    create_user(db_path, roles, "alice", "correct-pw", None, "customer_service")

    wrong_pw = _login(client, "alice", "wrong-pw")
    nonexistent = _login(client, "totally_fake_user", "anything")

    assert wrong_pw.status_code == nonexistent.status_code == 401
    assert wrong_pw.json() == nonexistent.json()


def test_login_success_returns_a_real_token(client):
    db_path = app_module.app.state.credentials_db_path
    roles = app_module.app.state.config.roles
    create_user(db_path, roles, "alice", "correct-pw", None, "customer_service")

    response = _login(client, "alice", "correct-pw")
    assert response.status_code == 200
    assert len(response.json()["token"]) > 20


def test_query_without_token_is_rejected(client):
    response = client.post("/query", json={"query": "test"})
    assert response.status_code == 401


def test_create_user_without_manage_users_grant_is_rejected(client):
    db_path = app_module.app.state.credentials_db_path
    roles = app_module.app.state.config.roles
    create_user(db_path, roles, "alice", "correct-pw", None, "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.post(
        "/users", json={"username": "bob", "password": "pw", "role_name": "customer_service"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_create_user_with_manage_users_grant_succeeds_and_new_user_can_log_in(client):
    db_path = app_module.app.state.credentials_db_path
    roles = app_module.app.state.config.roles
    create_user(db_path, roles, "admin_user", "adminpass", None, "admin")
    token = _login(client, "admin_user", "adminpass").json()["token"]

    create_response = client.post(
        "/users",
        json={"username": "newperson", "password": "newpass123", "mac_value": "us-west", "role_name": "customer_service"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_response.status_code == 201

    login_response = _login(client, "newperson", "newpass123")
    assert login_response.status_code == 200


def test_logout_invalidates_the_token(client):
    db_path = app_module.app.state.credentials_db_path
    roles = app_module.app.state.config.roles
    create_user(db_path, roles, "alice", "correct-pw", None, "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    logout_response = client.post("/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_response.status_code == 204

    reuse_response = client.post("/query", json={"query": "test"}, headers={"Authorization": f"Bearer {token}"})
    assert reuse_response.status_code == 401


def test_query_end_to_end_with_mocked_llm(client):
    db_path = app_module.app.state.credentials_db_path
    roles = dict(app_module.app.state.config.roles)
    roles["customer_service"] = {"allowed_actions": [
        "read:Customer", "read:Customer.customer_id", "read:Customer.name",
    ]}
    app_module.app.state.config.roles = roles
    create_user(db_path, roles, "alice", "correct-pw", "us-west", "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    # Real data must actually be gathered for synthesis to call the LLM
    # at all -- an empty gather short-circuits to a canned message
    # (real, correct existing behavior, not something to route around).
    scripted_steps = [
        {"step": "search_object", "object_type": "Customer", "filter": {"customer_id": "cust_001"}},
        {"step": "get_field", "object_type": "Customer", "object_id": "cust_001", "field_name": "name"},
        {"step": "finish"},
    ]
    call_count = {"n": 0}

    def fake_post(*args, **kwargs):
        response = MagicMock()
        idx = min(call_count["n"], len(scripted_steps) - 1)
        if call_count["n"] < len(scripted_steps):
            response.json.return_value = {"message": {"content": json.dumps(scripted_steps[idx])}}
        else:
            response.json.return_value = {"message": {"content": "Here is your answer."}}
        response.raise_for_status.return_value = None
        call_count["n"] += 1
        return response

    with patch("adapters.ollama_adapter.requests.post", side_effect=fake_post):
        response = client.post("/query", json={"query": "test"}, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["answer"] == "Here is your answer."
