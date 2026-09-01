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

    # ALL THREE silos data_silos.yaml actually declares -- not just
    # primary_sql. Was only ever mediator.db before this file's own
    # get_object_detail_route tests needed a REAL Customer.risk_score
    # (an MDO field, backed by risk_sql) to genuinely exist: a real
    # gap this test fixture had, not something to work around in the
    # test itself by avoiding a field a real customer_service user can
    # actually see. Cheap to build (a handful of rows each) -- no
    # meaningful cost to every OTHER test in this file gaining two
    # small databases they don't happen to touch.
    for db_name, schema_name in [
        ("mediator.db", "schema.sql"),
        ("support.db", "support_schema.sql"),
        ("risk.db", "risk_schema.sql"),
    ]:
        conn = sqlite3.connect(dev_fixtures_dir / db_name)
        conn.executescript((FIXTURES_DIR / schema_name).read_text())
        conn.commit()
        conn.close()

    test_paths = RuntimePaths(config_dir=FIXTURES_DIR, data_dir=data_dir, log_dir=tmp_path / "log")
    app = create_app(test_paths)

    return TestClient(app)


def _login(client, username, password):
    return client.post("/api/login", json={"username": username, "password": password})


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
    response = client.post("/api/query", json={"query": "test"})
    assert response.status_code == 401


def test_search_objects_without_token_is_rejected(client):
    response = client.get("/api/objects/Customer/search", params={"q": "ada"})
    assert response.status_code == 401


def test_my_visible_schema_without_token_is_rejected(client):
    response = client.get("/api/me/visible-schema")
    assert response.status_code == 401


def test_my_visible_schema_returns_the_callers_own_view(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.get("/api/me/visible-schema", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    # confirmed directly against a real mediator.visible_schema() call
    # for the customer_service role, not assumed.
    assert set(response.json().keys()) == {"Customer", "Transaction", "SupportTicket"}


def test_my_visible_schema_differs_by_role_not_a_static_response(client):
    # customer_service_no_email (user_dave's real role in fixtures/
    # policy.yaml) withholds read:Customer.email specifically -- proves
    # this route genuinely reflects the CALLER's own grants, not a
    # cached or role-blind response.
    client.app.state.user_directory.create_user("dave", "correct-pw", "us-west", "customer_service_no_email")
    token = _login(client, "dave", "correct-pw").json()["token"]

    response = client.get("/api/me/visible-schema", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert "email" not in response.json()["Customer"]["fields"]


def test_search_objects_finds_a_partial_match_with_real_field_values(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.get(
        "/api/objects/Customer/search", params={"q": "ada"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_matches"] == 1
    assert body["results"] == [
        {"id": "cust_001", "fields": {"region": "us-west", "name": "Ada Okafor", "email": "ada.okafor@example.com"}}
    ]


def test_search_objects_empty_query_returns_every_visible_result(client):
    # alice is us-west -- TWO real seeded customers share that region
    # (cust_001, cust_002), confirmed directly against fixtures/
    # schema.sql's own real data, not assumed. cust_003/cust_004 (us-
    # east/eu) must NOT appear.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.get(
        "/api/objects/Customer/search", params={"q": ""}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_matches"] == 2
    assert {result["id"] for result in body["results"]} == {"cust_001", "cust_002"}


def test_search_objects_no_query_param_at_all_also_browses_all(client):
    # q is genuinely optional -- omitting it entirely (not just passing
    # an empty string) must behave identically.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.get("/api/objects/Customer/search", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["total_matches"] == 2


def test_search_objects_blocks_cross_region_mac(client):
    # THE real security proof, not just a functional one: "ada" would
    # textually match cust_001's own real name regardless of who asks
    # -- bob (us-east) must still get nothing back, since cust_001 is
    # us-west, matching test_query's own established MAC-boundary
    # testing pattern elsewhere in this file.
    client.app.state.user_directory.create_user("bob", "correct-pw", "us-east", "customer_service")
    token = _login(client, "bob", "correct-pw").json()["token"]

    response = client.get(
        "/api/objects/Customer/search", params={"q": "ada"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json() == {"results": [], "total_matches": 0}


def test_search_objects_no_match_returns_empty_results(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.get(
        "/api/objects/Customer/search", params={"q": "zzz_nonexistent"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json() == {"results": [], "total_matches": 0}


def test_search_objects_unknown_type_returns_empty_results_not_error(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.get(
        "/api/objects/TotallyFakeType/search", params={"q": "ada"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json() == {"results": [], "total_matches": 0}


def test_object_detail_without_token_is_rejected(client):
    response = client.get("/api/objects/Customer/cust_001")
    assert response.status_code == 401


def test_object_detail_returns_every_visible_field_including_a_link(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.get("/api/objects/Customer/cust_001", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "cust_001"
    assert body["fields"]["region"] == "us-west"
    assert body["fields"]["name"] == "Ada Okafor"
    assert body["fields"]["email"] == "ada.okafor@example.com"
    # "transactions" is a real link field (cardinality many) -- proves
    # get_object() resolves it to the actual linked ids, not just plain
    # data fields.
    assert set(body["fields"]["transactions"]) == {1, 2}


def test_object_detail_nonexistent_id_returns_200_with_every_field_null(client):
    # Deliberate, not a bug -- see api/routes.py's own docstring for
    # the full reasoning: a nonexistent id within a KNOWN, visible type
    # must be indistinguishable from a real, MAC-denied one.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.get("/api/objects/Customer/cust_does_not_exist", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "cust_does_not_exist"
    assert all(value is None for value in body["fields"].values())


def test_object_detail_cross_region_mac_denial_is_identical_to_nonexistent(client):
    # THE real security proof: cust_003 is a REAL, us-east customer --
    # bob (us-west) must see the EXACT same shape (every field null) as
    # a genuinely nonexistent id, not a different response that would
    # let him distinguish "exists but denied" from "doesn't exist."
    client.app.state.user_directory.create_user("bob", "correct-pw", "us-west", "customer_service")
    token = _login(client, "bob", "correct-pw").json()["token"]

    denied = client.get("/api/objects/Customer/cust_003", headers={"Authorization": f"Bearer {token}"})
    nonexistent = client.get("/api/objects/Customer/cust_does_not_exist", headers={"Authorization": f"Bearer {token}"})

    assert denied.status_code == nonexistent.status_code == 200
    assert all(value is None for value in denied.json()["fields"].values())
    assert set(denied.json()["fields"].keys()) == set(nonexistent.json()["fields"].keys())


def test_object_detail_unknown_type_returns_200_with_empty_fields(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.get("/api/objects/TotallyFakeType/whatever", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"id": "whatever", "fields": {}}


def test_object_detail_and_search_routes_do_not_collide(client):
    # A real, deliberately-verified concern: /objects/{type}/search and
    # /objects/{type}/{object_id} share the same prefix. Confirms
    # Starlette's own route-matching genuinely prioritizes the literal
    # "search" path segment (registered first in api/routes.py) over
    # treating "search" as a literal object_id -- verified directly,
    # not assumed from registration order alone.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.get(
        "/api/objects/Customer/search", params={"q": "ada"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert "results" in response.json()
    assert "total_matches" in response.json()


def test_visible_action_types_without_token_is_rejected(client):
    response = client.get("/api/me/visible-action-types")
    assert response.status_code == 401


def test_visible_action_types_returns_the_callers_own_view(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.get("/api/me/visible-action-types", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    # editor's real, confirmed grants (fixtures/policy.yaml) --
    # UpdateCustomerName and CreateCustomer, NOT TransferFunds.
    assert set(body.keys()) == {"UpdateCustomerName", "CreateCustomer"}
    assert body["UpdateCustomerName"]["parameters"]["customer_id"]["type"] == "object_reference"


def test_visible_action_types_differs_by_role_not_a_static_response(client):
    client.app.state.user_directory.create_user("bob", "correct-pw", "us-west", "customer_service")
    token = _login(client, "bob", "correct-pw").json()["token"]

    response = client.get("/api/me/visible-action-types", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    # customer_service has NO execute: grants at all (fixtures/
    # policy.yaml) -- proves this route genuinely reflects the
    # CALLER's own grants, not a cached or role-blind response.
    assert response.json() == {}


def test_propose_action_without_token_is_rejected(client):
    response = client.post("/api/actions/UpdateCustomerName", json={"parameters": {}})
    assert response.status_code == 401


def test_propose_action_succeeds_and_returns_a_real_pending_write(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.post(
        "/api/actions/UpdateCustomerName",
        json={"parameters": {"customer_id": "cust_001", "new_name": "Ada Lovelace"}},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 202
    body = response.json()["pending_write"]
    assert body["action_type_name"] == "UpdateCustomerName"
    assert body["sub_writes"] == [
        {
            "object_type": "Customer", "object_id": "cust_001",
            "changes": {"name": "Ada Lovelace"}, "expected_current_values": {"name": "Ada Okafor"},
        }
    ]


def test_propose_action_then_confirm_actually_changes_the_database(client):
    # THE real, full, end-to-end proof: propose via THIS new, direct
    # path (no LLM involved at all), confirm via the EXISTING /writes/
    # {id}/confirm endpoint (unchanged, shared with the model-
    # initiated path), then verify the real change through a
    # COMPLETELY SEPARATE, independent read (GET /objects/.../...),
    # not just trusting the confirm response's own claim.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    token = _login(client, "alice", "correct-pw").json()["token"]

    propose_response = client.post(
        "/api/actions/UpdateCustomerName",
        json={"parameters": {"customer_id": "cust_002", "new_name": "Bram F. Feldman"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    write_id = propose_response.json()["pending_write"]["id"]

    confirm_response = client.post(
        f"/api/writes/{write_id}/confirm", json={"approved": True}, headers={"Authorization": f"Bearer {token}"}
    )
    assert confirm_response.status_code == 200

    detail_response = client.get("/api/objects/Customer/cust_002", headers={"Authorization": f"Bearer {token}"})
    assert detail_response.json()["fields"]["name"] == "Bram F. Feldman"


def test_propose_action_rejected_leaves_the_database_unchanged(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    token = _login(client, "alice", "correct-pw").json()["token"]

    propose_response = client.post(
        "/api/actions/UpdateCustomerName",
        json={"parameters": {"customer_id": "cust_001", "new_name": "Someone Else"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    write_id = propose_response.json()["pending_write"]["id"]

    client.post(
        f"/api/writes/{write_id}/confirm", json={"approved": False}, headers={"Authorization": f"Bearer {token}"}
    )

    detail_response = client.get("/api/objects/Customer/cust_001", headers={"Authorization": f"Bearer {token}"})
    assert detail_response.json()["fields"]["name"] == "Ada Okafor"


def test_propose_action_unknown_action_and_real_but_unauthorized_action_are_identical(client):
    # THE real security proof for the normalized-error design, decided
    # explicitly with the user (see propose_action_route's own
    # docstring for the full reasoning): a genuinely nonexistent
    # action and a REAL action this user simply isn't authorized for
    # (TransferFunds -- editor has no execute: grant for it) must
    # produce the EXACT SAME response, not just "both look like
    # errors" -- byte-for-byte identical status and message.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    token = _login(client, "alice", "correct-pw").json()["token"]

    unknown = client.post(
        "/api/actions/TotallyFakeAction", json={"parameters": {}}, headers={"Authorization": f"Bearer {token}"}
    )
    unauthorized = client.post(
        "/api/actions/TransferFunds",
        json={"parameters": {
            "from_account_id": "acc_checking", "to_account_id": "acc_savings",
            "new_from_balance": 1, "new_to_balance": 1,
        }},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert unknown.status_code == unauthorized.status_code == 400
    assert unknown.json() == unauthorized.json()


def test_propose_action_missing_required_parameter_returns_the_same_generic_error(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.post(
        "/api/actions/UpdateCustomerName",
        json={"parameters": {"customer_id": "cust_001"}},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "That action could not be proposed. Check the action name and parameters, "
        "and that you're authorized to perform it."
    )


def test_propose_action_cross_region_mac_denial_returns_the_same_generic_error(client):
    # cust_003 is us-east; alice (editor) is us-west.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.post(
        "/api/actions/UpdateCustomerName",
        json={"parameters": {"customer_id": "cust_003", "new_name": "X"}},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "That action could not be proposed. Check the action name and parameters, "
        "and that you're authorized to perform it."
    )


def test_visible_action_types_with_discover_grant_shows_the_whole_catalog(client):
    # process_auditor holds discover:action_types and DELIBERATELY no
    # execute: grant at all -- proves discovery is genuinely
    # independent of any execute: grant, not built from executable
    # actions plus a few extras.
    client.app.state.user_directory.create_user("carol", "correct-pw", "us-west", "process_auditor")
    token = _login(client, "carol", "correct-pw").json()["token"]

    response = client.get("/api/me/visible-action-types", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert set(response.json().keys()) == {"UpdateCustomerName", "CreateCustomer", "TransferFunds"}


def test_visible_action_types_executable_flag_is_false_with_no_execute_grants(client):
    # process_auditor sees the whole catalog (previous test) but holds
    # NO execute: grants at all -- every entry's own "executable" flag
    # must be false, matching what the frontend needs to decide
    # whether to render a button for it at all (see ObjectDetailPanel.
    # jsx's own comment).
    client.app.state.user_directory.create_user("carol", "correct-pw", "us-west", "process_auditor")
    token = _login(client, "carol", "correct-pw").json()["token"]

    response = client.get("/api/me/visible-action-types", headers={"Authorization": f"Bearer {token}"})

    body = response.json()
    assert all(action_def["executable"] is False for action_def in body.values())


def test_visible_action_types_executable_flag_differentiates_within_one_response(client):
    # THE real proof of per-action differentiation, not just an all-
    # or-nothing role: senior_auditor holds discover:action_types
    # (sees all three) AND execute:UpdateCustomerName specifically
    # (can genuinely invoke only that one) -- confirms "executable"
    # is computed PER action, not a single, role-wide flag.
    client.app.state.user_directory.create_user("dana", "correct-pw", "us-west", "senior_auditor")
    token = _login(client, "dana", "correct-pw").json()["token"]

    response = client.get("/api/me/visible-action-types", headers={"Authorization": f"Bearer {token}"})

    body = response.json()
    assert set(body.keys()) == {"UpdateCustomerName", "CreateCustomer", "TransferFunds"}
    assert body["UpdateCustomerName"]["executable"] is True
    assert body["CreateCustomer"]["executable"] is False
    assert body["TransferFunds"]["executable"] is False


def test_visible_action_types_executable_flag_is_always_true_without_discover_grant(client):
    # editor holds NO discover:action_types -- every entry it sees is
    # already execute:-filtered by visible_action_types() itself, so
    # "executable" is always true here, if redundant -- confirms the
    # flag doesn't accidentally introduce a NEW denial for the
    # existing, unchanged, non-discover: path.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.get("/api/me/visible-action-types", headers={"Authorization": f"Bearer {token}"})

    body = response.json()
    assert set(body.keys()) == {"UpdateCustomerName", "CreateCustomer"}
    assert all(action_def["executable"] is True for action_def in body.values())


def test_propose_action_unknown_action_shows_the_real_message_for_a_discover_holder(client):
    client.app.state.user_directory.create_user("carol", "correct-pw", "us-west", "process_auditor")
    token = _login(client, "carol", "correct-pw").json()["token"]

    response = client.post(
        "/api/actions/TotallyFakeAction", json={"parameters": {}}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown action_type: 'TotallyFakeAction'"


def test_propose_action_real_but_unauthorized_shows_403_for_a_discover_holder(client):
    # process_auditor can SEE TransferFunds (previous test) but holds
    # no execute: grant for it at all -- the real, unchanged
    # authorization gate still refuses it, now with a real, specific
    # 403 rather than the generic 400 every other role gets.
    client.app.state.user_directory.create_user("carol", "correct-pw", "us-west", "process_auditor")
    token = _login(client, "carol", "correct-pw").json()["token"]

    response = client.post(
        "/api/actions/TransferFunds",
        json={"parameters": {
            "from_account_id": "acc_checking", "to_account_id": "acc_savings",
            "new_from_balance": 1, "new_to_balance": 1,
        }},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "'carol' is not authorized for: 'execute:TransferFunds'"


def test_propose_action_unknown_vs_unauthorized_are_no_longer_identical_for_a_discover_holder(client):
    # The direct inverse of test_propose_action_unknown_action_and_
    # real_but_unauthorized_action_are_identical above -- for a
    # discover:-holding role specifically, these two cases are now
    # DELIBERATELY distinguishable (different status code, different
    # message), since that role already sees the full catalog and
    # "unknown vs denied" is no longer a real leak for them.
    client.app.state.user_directory.create_user("carol", "correct-pw", "us-west", "process_auditor")
    token = _login(client, "carol", "correct-pw").json()["token"]

    unknown = client.post(
        "/api/actions/TotallyFakeAction", json={"parameters": {}}, headers={"Authorization": f"Bearer {token}"}
    )
    unauthorized = client.post(
        "/api/actions/TransferFunds",
        json={"parameters": {
            "from_account_id": "acc_checking", "to_account_id": "acc_savings",
            "new_from_balance": 1, "new_to_balance": 1,
        }},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert unknown.status_code != unauthorized.status_code
    assert unknown.json() != unauthorized.json()


def test_create_user_without_manage_users_grant_is_rejected(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.post(
        "/api/users", json={"username": "bob", "password": "pw", "role_name": "customer_service"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_create_user_with_manage_users_grant_succeeds_and_new_user_can_log_in(client):
    client.app.state.user_directory.create_user("admin_user", "adminpass", None, "admin")
    token = _login(client, "admin_user", "adminpass").json()["token"]

    create_response = client.post(
        "/api/users",
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

    logout_response = client.post("/api/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_response.status_code == 204

    reuse_response = client.post("/api/query", json={"query": "test"}, headers={"Authorization": f"Bearer {token}"})
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
        response = client.post("/api/query", json={"query": "test"}, headers={"Authorization": f"Bearer {token}"})

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
        response = client.post("/api/query", json={"query": "test"}, headers={"Authorization": f"Bearer {token}"})

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
        return client.post(
            "/api/query", json={"query": "update the name"}, headers={"Authorization": f"Bearer {token}"}
        )


def test_query_proposing_an_action_returns_202_with_a_reference(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    token = _login(client, "alice", "correct-pw").json()["token"]

    response = _propose_action(client, token)

    assert response.status_code == 202
    body = response.json()
    assert "id" in body["pending_write"]
    assert body["pending_write"]["action_type_name"] == "UpdateCustomerName"
    assert body["pending_write"]["sub_writes"] == [
        {
            "object_type": "Customer", "object_id": "cust_001", "changes": {"name": "Updated Name"},
            "expected_current_values": {"name": "Ada Okafor"},
        }
    ]


def test_confirming_an_approved_action_actually_changes_the_database(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    token = _login(client, "alice", "correct-pw").json()["token"]

    write_id = _propose_action(client, token).json()["pending_write"]["id"]

    confirm_response = client.post(
        f"/api/writes/{write_id}/confirm", json={"approved": True},
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
        f"/api/writes/{write_id}/confirm", json={"approved": False},
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
        f"/api/writes/{write_id}/confirm", json={"approved": True},
        headers={"Authorization": f"Bearer {eve_token}"},
    )
    unknown_id_response = client.post(
        "/api/writes/totally-fake-id/confirm", json={"approved": True},
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

    response = client.get("/api/users", headers={"Authorization": f"Bearer {alice_token}"})
    assert response.status_code == 403


def test_list_users_returns_non_sensitive_metadata_only(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    admin_token = _make_admin(client)

    response = client.get("/api/users", headers={"Authorization": f"Bearer {admin_token}"})
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

    response = client.post("/api/logout-all", headers={"Authorization": f"Bearer {token1}"})
    assert response.status_code == 204

    for token in (token1, token2):
        result = client.post("/api/query", json={"query": "test"}, headers={"Authorization": f"Bearer {token}"})
        assert result.status_code == 401


def test_admin_logout_all_for_a_target_user_requires_manage_users(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    alice_token = _login(client, "alice", "correct-pw").json()["token"]

    # alice herself has no manage:users grant.
    response = client.post("/api/users/alice/logout-all", headers={"Authorization": f"Bearer {alice_token}"})
    assert response.status_code == 403


def test_admin_logout_all_for_a_target_user_works(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    alice_token = _login(client, "alice", "correct-pw").json()["token"]
    admin_token = _make_admin(client)

    response = client.post("/api/users/alice/logout-all", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 204

    result = client.post("/api/query", json={"query": "test"}, headers={"Authorization": f"Bearer {alice_token}"})
    assert result.status_code == 401


def test_visible_schema_debug_view_shows_what_the_target_user_can_see(client):
    client.app.state.config.roles["customer_service"] = {"allowed_actions": [
        "read:Customer", "read:Customer.customer_id", "read:Customer.name",
    ]}
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    admin_token = _make_admin(client)

    response = client.get("/api/users/alice/visible-schema", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    body = response.json()
    assert "Customer" in body
    assert set(body["Customer"]["fields"].keys()) == {"name"}  # customer_id is the id_field, not a "fields" entry


def test_visible_schema_debug_view_requires_manage_users(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    alice_token = _login(client, "alice", "correct-pw").json()["token"]

    response = client.get("/api/users/alice/visible-schema", headers={"Authorization": f"Bearer {alice_token}"})
    assert response.status_code == 403


def test_visible_schema_debug_view_for_unknown_user_is_404(client):
    admin_token = _make_admin(client)
    response = client.get(
        "/api/users/totally_fake_user/visible-schema", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 404


def test_disable_user_blocks_new_logins_and_kills_existing_sessions(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    alice_token = _login(client, "alice", "correct-pw").json()["token"]
    admin_token = _make_admin(client)

    response = client.post("/api/users/alice/disable", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 204

    # Existing session immediately rejected -- not just future logins.
    existing_session_result = client.post(
        "/api/query", json={"query": "test"}, headers={"Authorization": f"Bearer {alice_token}"}
    )
    assert existing_session_result.status_code == 401

    # New login attempt also blocked, same generic message as a wrong password.
    login_attempt = _login(client, "alice", "correct-pw")
    assert login_attempt.status_code == 401
    assert login_attempt.json()["detail"] == "Invalid username or password"


def test_disable_nonexistent_user_is_404(client):
    admin_token = _make_admin(client)
    response = client.post("/api/users/totally_fake_user/disable", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 404


def test_enable_reverses_disable(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    admin_token = _make_admin(client)

    client.post("/api/users/alice/disable", headers={"Authorization": f"Bearer {admin_token}"})
    client.post("/api/users/alice/enable", headers={"Authorization": f"Bearer {admin_token}"})

    login_attempt = _login(client, "alice", "correct-pw")
    assert login_attempt.status_code == 200


def test_delete_user_removes_credential_and_kills_sessions(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    alice_token = _login(client, "alice", "correct-pw").json()["token"]
    admin_token = _make_admin(client)

    response = client.delete("/api/users/alice", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 204

    existing_session_result = client.post(
        "/api/query", json={"query": "test"}, headers={"Authorization": f"Bearer {alice_token}"}
    )
    assert existing_session_result.status_code == 401

    login_attempt = _login(client, "alice", "correct-pw")
    assert login_attempt.status_code == 401


def test_delete_nonexistent_user_is_404(client):
    admin_token = _make_admin(client)
    response = client.delete("/api/users/totally_fake_user", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 404
