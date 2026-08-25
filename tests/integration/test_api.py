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
from core.intermediate_layer.auth import UserRecord
from core.user_directory import create_user


@pytest.fixture
def client(tmp_path: Path):
    # Real app (real deployment/ config, real mediator) but an
    # ISOLATED credentials database -- swapped onto app.state, which
    # is read at request time, not baked in at import time.
    test_db_path = tmp_path / "credentials.db"
    app_module.app.state.credentials_db_path = test_db_path

    # Mutated IN PLACE, deliberately, not reassigned: config.roles,
    # mediator.roles, and write_mediator.roles are all the SAME dict
    # object at app construction time (confirmed directly -- `config.
    # roles is mediator.roles` is True). Reassigning app.state.config.
    # roles = a_new_dict only updates what config.roles POINTS TO --
    # mediator/write_mediator still hold the ORIGINAL object, unaware
    # of the new one. In-place mutation is visible to all three at
    # once, since they're genuinely the same object in memory.
    roles = app_module.app.state.config.roles
    roles["admin"] = {"allowed_actions": frozenset(["manage:users"])}
    roles.setdefault("customer_service", {"allowed_actions": frozenset()})

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
    roles = app_module.app.state.config.roles
    roles["customer_service"] = {"allowed_actions": [
        "read:Customer", "read:Customer.customer_id", "read:Customer.name",
    ]}
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


def test_query_refuses_if_permissions_changed_during_processing(client):
    # Simulates a role revoked WHILE a query was running -- deterministic,
    # not a real timing-dependent race: mocks the re-verification's own
    # lookup (api.routes.get_user_record) to return a DIFFERENT record
    # than what actually authenticated the request, proving the
    # comparison logic itself refuses to return data in that case,
    # rather than relying on a flaky real race condition to occur.
    db_path = app_module.app.state.credentials_db_path
    roles = app_module.app.state.config.roles
    create_user(db_path, roles, "alice", "correct-pw", "us-west", "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    def fake_post(*args, **kwargs):
        response = MagicMock()
        response.json.return_value = {"message": {"content": json.dumps({"step": "finish"})}}
        response.raise_for_status.return_value = None
        return response

    # A DIFFERENT record (role changed from customer_service to None)
    # than what the request actually authenticated with.
    changed_record = UserRecord(user_id="alice", security_value="us-west", role_name=None)

    with patch("adapters.ollama_adapter.requests.post", side_effect=fake_post), \
         patch("api.routes.get_user_record", return_value=changed_record):
        response = client.post("/query", json={"query": "test"}, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 409
    assert "answer" not in response.json()


def _propose_write(client, token):
    # Helper: a real query that proposes a real write against the real
    # deployment schema (Customer.name on cust_001), returns the 202
    # response.
    def fake_post(*args, **kwargs):
        response = MagicMock()
        response.json.return_value = {"message": {"content": json.dumps({
            "step": "propose_write", "object_type": "Customer", "object_id": "cust_001",
            "action": "update", "changes": {"name": "Updated Name"},
        })}}
        response.raise_for_status.return_value = None
        return response

    with patch("adapters.ollama_adapter.requests.post", side_effect=fake_post):
        return client.post("/query", json={"query": "update the name"}, headers={"Authorization": f"Bearer {token}"})


def test_query_proposing_a_write_returns_202_with_a_reference(client):
    db_path = app_module.app.state.credentials_db_path
    roles = app_module.app.state.config.roles
    roles["editor"] = {"allowed_actions": [
        "read:Customer", "read:Customer.customer_id", "write:Customer.name",
    ]}
    create_user(db_path, roles, "alice", "correct-pw", "us-west", "editor")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = _propose_write(client, token)

    assert response.status_code == 202
    body = response.json()
    assert "id" in body["pending_write"]
    assert body["pending_write"]["changes"] == {"name": "Updated Name"}


def test_confirming_an_approved_write_actually_changes_the_database(client):
    # cust_001's name is REAL, shared, git-tracked demo data (deployment/
    # var/lib/dev_fixtures/mediator.db) -- unlike credentials.db, it is
    # NOT isolated per test. This test genuinely mutates it, so it
    # restores the original value afterward regardless of outcome,
    # rather than leaving the shipped demo data permanently corrupted
    # for every future test run.
    adapter = app_module.app.state.mediator._adapter_for("Customer")
    type_config = app_module.app.state.mediator._type_schema("Customer")
    original_name = adapter.get_raw_field("Customer", "cust_001", "name", type_config)

    try:
        db_path = app_module.app.state.credentials_db_path
        roles = app_module.app.state.config.roles
        roles["editor"] = {"allowed_actions": [
            "read:Customer", "read:Customer.customer_id", "read:Customer.name", "write:Customer.name",
        ]}
        create_user(db_path, roles, "alice", "correct-pw", "us-west", "editor")
        token = _login(client, "alice", "correct-pw").json()["token"]

        write_id = _propose_write(client, token).json()["pending_write"]["id"]

        confirm_response = client.post(
            f"/writes/{write_id}/confirm", json={"approved": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert confirm_response.status_code == 200
        assert confirm_response.json()["status"] == "written"

        # Real proof the database actually changed -- a direct adapter
        # read, not just trusting the confirm endpoint's own claim.
        actual_value = adapter.get_raw_field("Customer", "cust_001", "name", type_config)
        assert actual_value == "Updated Name"
    finally:
        adapter.write_fields("Customer", "cust_001", {"name": original_name}, {}, type_config)


def _propose_write_with_value(client, token, new_name):
    def fake_post(*args, **kwargs):
        response = MagicMock()
        response.json.return_value = {"message": {"content": json.dumps({
            "step": "propose_write", "object_type": "Customer", "object_id": "cust_001",
            "action": "update", "changes": {"name": new_name},
        })}}
        response.raise_for_status.return_value = None
        return response

    with patch("adapters.ollama_adapter.requests.post", side_effect=fake_post):
        return client.post("/query", json={"query": "update the name"}, headers={"Authorization": f"Bearer {token}"})


def test_confirming_a_rejected_write_does_not_change_the_database(client):
    db_path = app_module.app.state.credentials_db_path
    roles = app_module.app.state.config.roles
    roles["editor"] = {"allowed_actions": [
        "read:Customer", "read:Customer.customer_id", "write:Customer.name",
    ]}
    create_user(db_path, roles, "alice", "correct-pw", "us-west", "editor")
    token = _login(client, "alice", "correct-pw").json()["token"]

    # A value UNIQUE to this test -- deployment/var/lib/dev_fixtures/
    # mediator.db is a genuinely shared file across the whole test
    # session (unlike credentials.db, which IS isolated per test), so
    # reusing another test's target value here could pass or fail
    # depending on execution order, for the wrong reason.
    write_id = _propose_write_with_value(client, token, "Should Never Apply").json()["pending_write"]["id"]

    confirm_response = client.post(
        f"/writes/{write_id}/confirm", json={"approved": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "rejected"

    real_type_config = app_module.app.state.mediator._type_schema("Customer")
    adapter = app_module.app.state.mediator._adapter_for("Customer")
    actual_value = adapter.get_raw_field("Customer", "cust_001", "name", real_type_config)
    assert actual_value != "Should Never Apply"


def test_confirm_with_wrong_user_and_unknown_id_are_identical(client):
    db_path = app_module.app.state.credentials_db_path
    roles = app_module.app.state.config.roles
    roles["editor"] = {"allowed_actions": [
        "read:Customer", "read:Customer.customer_id", "write:Customer.name",
    ]}
    roles.setdefault("customer_service", {"allowed_actions": []})
    create_user(db_path, roles, "alice", "correct-pw", "us-west", "editor")
    create_user(db_path, roles, "eve", "correct-pw", "us-west", "customer_service")
    alice_token = _login(client, "alice", "correct-pw").json()["token"]
    eve_token = _login(client, "eve", "correct-pw").json()["token"]

    write_id = _propose_write(client, alice_token).json()["pending_write"]["id"]

    wrong_user_response = client.post(
        f"/writes/{write_id}/confirm", json={"approved": True},
        headers={"Authorization": f"Bearer {eve_token}"},
    )
    unknown_id_response = client.post(
        "/writes/totally-fake-id/confirm", json={"approved": True},
        headers={"Authorization": f"Bearer {eve_token}"},
    )

    assert wrong_user_response.status_code == unknown_id_response.status_code == 404
    assert wrong_user_response.json() == unknown_id_response.json()
