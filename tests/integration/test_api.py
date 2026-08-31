"""
Integration tests for the api/ layer -- each test gets a GENUINELY
isolated app instance (api.app.create_app(), given its own RuntimePaths
pointing at a fresh temp directory) rather than mutating the one real,
module-level app. Real FastAPI TestClient, real core/auth/
core/user_directory logic, real (but fully disposable) SQLite data.

The earlier design mutated the real app's state in place (swapping
credentials_db_path, patching roles at runtime) -- workable, but it
meant a test COULD (and once did) corrupt deployment/'s real, shipped
demo data. Genuine per-test app isolation makes that structurally
impossible instead of relying on careful cleanup: no in-place role
mutation needed (fixtures/policy.yaml already defines every role these
tests use), no try/finally restoration, no "use a unique value to
avoid cross-test collision" workarounds.

/query is the only route needing the LLM -- mocked there the same way
tests/integration/ already mocks Ollama's HTTP call elsewhere.

Marked @pytest.mark.mocked_llm, NOT @pytest.mark.integration (unlike
tests/integration/'s other two files) -- these exercise the full,
real, wired-together system (FastAPI, AgentLoop, SQLite, sessions) but
never touch a real LLM, so they stay fast enough to run every time.
"integration" is reserved specifically for the two files that need a
real Ollama server. See pytest.ini for both markers' registered
descriptions.
"""

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from core.deployment_loader import RuntimePaths
from core.intermediate_layer.auth import UserRecord

pytestmark = pytest.mark.mocked_llm

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def client(tmp_path: Path):
    data_dir = tmp_path / "data"
    dev_fixtures_dir = data_dir / "dev_fixtures"
    dev_fixtures_dir.mkdir(parents=True)

    db_path = dev_fixtures_dir / "mediator.db"
    conn = sqlite3.connect(db_path)
    conn.executescript((FIXTURES_DIR / "schema.sql").read_text())
    conn.commit()
    conn.close()

    test_paths = RuntimePaths(config_dir=FIXTURES_DIR, data_dir=data_dir, log_dir=tmp_path / "log")
    app = create_app(test_paths)

    return TestClient(app)


def _login(client, username, password):
    return client.post("/login", json={"username": username, "password": password})


def test_login_wrong_password_and_nonexistent_username_are_identical(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")

    wrong_pw = _login(client, "alice", "wrong-pw")
    nonexistent = _login(client, "totally_fake_user", "anything")

    assert wrong_pw.status_code == nonexistent.status_code == 401
    assert wrong_pw.json() == nonexistent.json()


def test_login_success_returns_a_real_token(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")

    response = _login(client, "alice", "correct-pw")
    assert response.status_code == 200
    assert len(response.json()["token"]) > 20


def test_query_without_token_is_rejected(client):
    response = client.post("/query", json={"query": "test"})
    assert response.status_code == 401


def test_create_user_without_manage_users_grant_is_rejected(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.post(
        "/users", json={"username": "bob", "password": "pw", "role_name": "customer_service"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_create_user_with_manage_users_grant_succeeds_and_new_user_can_log_in(client):
    client.app.state.user_directory.create_user("admin_user", "adminpass", None, "admin")
    token = _login(client, "admin_user", "adminpass").json()["token"]

    create_response = client.post(
        "/users",
        json={"username": "newperson", "password": "newpass123",
              "mac_value": "us-west", "role_name": "customer_service"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_response.status_code == 201

    login_response = _login(client, "newperson", "newpass123")
    assert login_response.status_code == 200


def test_logout_invalidates_the_token(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    logout_response = client.post("/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_response.status_code == 204

    reuse_response = client.post("/query", json={"query": "test"}, headers={"Authorization": f"Bearer {token}"})
    assert reuse_response.status_code == 401


def test_query_end_to_end_with_mocked_llm(client):
    # fixtures/policy.yaml's customer_service role already includes
    # read:Customer.name -- no runtime role patching needed.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
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
    # lookup (UserDirectory.get_user_record) to return a DIFFERENT record
    # than what actually authenticated the request, proving the
    # comparison logic itself refuses to return data in that case,
    # rather than relying on a flaky real race condition to occur.
    #
    # get_user_record() is now called TWICE per request -- once by
    # get_current_user() (authentication, BEFORE the route handler even
    # runs) and once by the route's own re-verification check -- both
    # through the SAME UserDirectory instance/method. A plain
    # return_value mock would make BOTH calls see the changed record,
    # including authentication itself, which would silently defeat this
    # test (the re-verification would then compare the changed record
    # against ITSELF, never catching a real mismatch). side_effect with
    # two distinct values makes the first call (auth) see the REAL
    # record and only the second (re-verification) see the changed one.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    def fake_post(*args, **kwargs):
        response = MagicMock()
        response.json.return_value = {"message": {"content": json.dumps({"step": "finish"})}}
        response.raise_for_status.return_value = None
        return response

    real_record = UserRecord(user_id="alice", security_value="us-west", role_name="customer_service")
    # A DIFFERENT record (role changed from customer_service to None)
    # than what the request actually authenticated with.
    changed_record = UserRecord(user_id="alice", security_value="us-west", role_name=None)

    with patch("adapters.ollama_adapter.requests.post", side_effect=fake_post), \
         patch("core.user_directory.UserDirectory.get_user_record", side_effect=[real_record, changed_record]):
        response = client.post("/query", json={"query": "test"}, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 409
    assert "answer" not in response.json()


def _propose_action(client, token, new_name="Updated Name"):
    # Helper: a real query that proposes a real named-action invocation
    # against the fixture's own Customer schema (cust_001), returns the
    # 202 response. Uses the same UpdateCustomerName action editor's
    # own execute: grant covers -- see policy.yaml's own comment.
    # No separate "object_id" field -- customer_id is just another
    # entry in "parameters" now, matching Palantir Foundry's own action
    # parameter model directly (see WriteMediator.propose_action()'s
    # own docstring).
    def fake_post(*args, **kwargs):
        response = MagicMock()
        response.json.return_value = {"message": {"content": json.dumps({
            "step": "propose_action", "action_type": "UpdateCustomerName",
            "parameters": {"customer_id": "cust_001", "new_name": new_name},
        })}}
        response.raise_for_status.return_value = None
        return response

    with patch("adapters.ollama_adapter.requests.post", side_effect=fake_post):
        return client.post("/query", json={"query": "update the name"}, headers={"Authorization": f"Bearer {token}"})


def test_query_proposing_an_action_returns_202_with_a_reference(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = _propose_action(client, token)

    assert response.status_code == 202
    body = response.json()
    assert "id" in body["pending_write"]
    assert body["pending_write"]["changes"] == {"name": "Updated Name"}


def test_confirming_an_approved_action_actually_changes_the_database(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    token = _login(client, "alice", "correct-pw").json()["token"]

    write_id = _propose_action(client, token).json()["pending_write"]["id"]

    confirm_response = client.post(
        f"/writes/{write_id}/confirm", json={"approved": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "written"

    # Real proof the database actually changed -- a direct adapter
    # read, not just trusting the confirm endpoint's own claim. This
    # fixture's OWN, disposable database -- nothing to restore afterward.
    adapter = client.app.state.mediator._adapter_for("Customer")
    type_config = client.app.state.mediator._type_schema("Customer")
    actual_value = adapter.get_raw_field("Customer", "cust_001", "name", type_config)
    assert actual_value == "Updated Name"


def test_confirming_a_rejected_action_does_not_change_the_database(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    token = _login(client, "alice", "correct-pw").json()["token"]

    write_id = _propose_action(client, token).json()["pending_write"]["id"]

    confirm_response = client.post(
        f"/writes/{write_id}/confirm", json={"approved": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "rejected"

    adapter = client.app.state.mediator._adapter_for("Customer")
    type_config = client.app.state.mediator._type_schema("Customer")
    actual_value = adapter.get_raw_field("Customer", "cust_001", "name", type_config)
    assert actual_value == "Ada Okafor"  # the fixture's real, unchanged seed value


def test_confirm_with_wrong_user_and_unknown_id_are_identical(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    client.app.state.user_directory.create_user("eve", "correct-pw", "us-west", "customer_service")
    alice_token = _login(client, "alice", "correct-pw").json()["token"]
    eve_token = _login(client, "eve", "correct-pw").json()["token"]

    write_id = _propose_action(client, alice_token).json()["pending_write"]["id"]

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


def _make_admin(client):
    client.app.state.config.roles["admin"] = {"allowed_actions": frozenset(["manage:users"])}
    client.app.state.user_directory.create_user("admin_user", "adminpass", None, "admin")
    return _login(client, "admin_user", "adminpass").json()["token"]


def test_list_users_requires_manage_users(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    alice_token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.get("/users", headers={"Authorization": f"Bearer {alice_token}"})
    assert response.status_code == 403


def test_list_users_returns_non_sensitive_metadata_only(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    admin_token = _make_admin(client)

    response = client.get("/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    body = response.json()
    usernames = {entry["username"] for entry in body}
    assert {"alice", "admin_user"} <= usernames

    alice_entry = next(entry for entry in body if entry["username"] == "alice")
    assert alice_entry["role_name"] == "customer_service"
    assert alice_entry["mac_value"] == "us-west"
    assert alice_entry["disabled"] is False
    assert "password" not in alice_entry and "password_hash" not in alice_entry


def test_logout_all_revokes_every_session_for_the_caller(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    token1 = _login(client, "alice", "correct-pw").json()["token"]
    token2 = _login(client, "alice", "correct-pw").json()["token"]

    response = client.post("/logout-all", headers={"Authorization": f"Bearer {token1}"})
    assert response.status_code == 204

    for token in (token1, token2):
        result = client.post("/query", json={"query": "test"}, headers={"Authorization": f"Bearer {token}"})
        assert result.status_code == 401


def test_admin_logout_all_for_a_target_user_requires_manage_users(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    alice_token = _login(client, "alice", "correct-pw").json()["token"]

    # alice herself has no manage:users grant.
    response = client.post("/users/alice/logout-all", headers={"Authorization": f"Bearer {alice_token}"})
    assert response.status_code == 403


def test_admin_logout_all_for_a_target_user_works(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    alice_token = _login(client, "alice", "correct-pw").json()["token"]
    admin_token = _make_admin(client)

    response = client.post("/users/alice/logout-all", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 204

    result = client.post("/query", json={"query": "test"}, headers={"Authorization": f"Bearer {alice_token}"})
    assert result.status_code == 401


def test_visible_schema_debug_view_shows_what_the_target_user_can_see(client):
    client.app.state.config.roles["customer_service"] = {"allowed_actions": [
        "read:Customer", "read:Customer.customer_id", "read:Customer.name",
    ]}
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    admin_token = _make_admin(client)

    response = client.get("/users/alice/visible-schema", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    body = response.json()
    assert "Customer" in body
    assert set(body["Customer"]["fields"].keys()) == {"name"}  # customer_id is the id_field, not a "fields" entry


def test_visible_schema_debug_view_requires_manage_users(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    alice_token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.get("/users/alice/visible-schema", headers={"Authorization": f"Bearer {alice_token}"})
    assert response.status_code == 403


def test_visible_schema_debug_view_for_unknown_user_is_404(client):
    admin_token = _make_admin(client)
    response = client.get("/users/totally_fake_user/visible-schema", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 404


def test_disable_user_blocks_new_logins_and_kills_existing_sessions(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    alice_token = _login(client, "alice", "correct-pw").json()["token"]
    admin_token = _make_admin(client)

    response = client.post("/users/alice/disable", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 204

    # Existing session immediately rejected -- not just future logins.
    existing_session_result = client.post(
        "/query", json={"query": "test"}, headers={"Authorization": f"Bearer {alice_token}"}
    )
    assert existing_session_result.status_code == 401

    # New login attempt also blocked, same generic message as a wrong password.
    login_attempt = _login(client, "alice", "correct-pw")
    assert login_attempt.status_code == 401
    assert login_attempt.json()["detail"] == "Invalid username or password"


def test_disable_nonexistent_user_is_404(client):
    admin_token = _make_admin(client)
    response = client.post("/users/totally_fake_user/disable", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 404


def test_enable_reverses_disable(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    admin_token = _make_admin(client)

    client.post("/users/alice/disable", headers={"Authorization": f"Bearer {admin_token}"})
    client.post("/users/alice/enable", headers={"Authorization": f"Bearer {admin_token}"})

    login_attempt = _login(client, "alice", "correct-pw")
    assert login_attempt.status_code == 200


def test_delete_user_removes_credential_and_kills_sessions(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    alice_token = _login(client, "alice", "correct-pw").json()["token"]
    admin_token = _make_admin(client)

    response = client.delete("/users/alice", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 204

    existing_session_result = client.post(
        "/query", json={"query": "test"}, headers={"Authorization": f"Bearer {alice_token}"}
    )
    assert existing_session_result.status_code == 401

    login_attempt = _login(client, "alice", "correct-pw")
    assert login_attempt.status_code == 401


def test_delete_nonexistent_user_is_404(client):
    admin_token = _make_admin(client)
    response = client.delete("/users/totally_fake_user", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 404
