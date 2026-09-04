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
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # TestClient's own base URL is plain http://testserver, not https --
    # a real, found gap this test suite ran into directly: a Secure-
    # flagged cookie (core/auth/auth_cookies.py's own default, matching
    # a real production deployment) is genuinely never TRANSMITTED back
    # by httpx's own cookie jar over a non-HTTPS connection, even
    # though it IS still stored client-side -- exactly matching a real
    # browser's own behavior, confirmed directly by isolating the
    # exact mechanism before assuming this was the cause. Every real
    # test in this file needs the same local-dev-style override a real
    # developer's own machine would set, for the same reason.
    monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")

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


def _csrf_headers(client):
    # The X-CSRF-Token header matching the CLIENT's own, CURRENTLY
    # active session -- the common case, where only one user is ever
    # logged in through this client at a time (TestClient's own
    # cookie jar already carries the session automatically; this is
    # the one piece it does NOT attach for us, since only real,
    # same-origin JS is meant to know to do that -- see api/
    # csrf_middleware.py's own docstring).
    return {"X-CSRF-Token": client.cookies.get("elysium_csrf")}


def _capture_session(client):
    # Captures the client's CURRENT session (both cookies) as an
    # explicit, standalone dict -- independent of whatever the SAME
    # client's own, single, shared cookie jar holds LATER (e.g. after
    # a DIFFERENT user subsequently logs in through it too). Needed
    # only by the small number of tests that genuinely act as more
    # than one session at once (two different users, or two sessions
    # for the same user); call this immediately after a successful
    # _login(), before anything else overwrites the jar.
    return {
        "elysium_session": client.cookies.get("elysium_session"),
        "elysium_csrf": client.cookies.get("elysium_csrf"),
    }


def _csrf_header_for(session):
    # Pairs with a _capture_session() dict -- always call
    # _use_session(client, session) BEFORE the request too, or the
    # CSRF check would correctly, but unhelpfully, reject a mismatched
    # pairing (the client's own cookie jar would still hold some
    # OTHER session's cookies otherwise).
    return {"X-CSRF-Token": session["elysium_csrf"]}


def _use_session(client, session):
    # Mutates the CLIENT's own cookie jar to match a captured session
    # -- the current, correct way to control which session a
    # subsequent request uses. Replaces an earlier version of this
    # file that passed cookies={...} directly as a PER-REQUEST kwarg
    # to client.post()/client.get() -- a real DeprecationWarning
    # (TestClient's own httpx2 client: "Setting per-request cookies=
    # is being deprecated, because the expected behaviour on cookie
    # persistence is ambiguous") this project's own test suite was
    # genuinely producing, not a hypothetical one. Confirmed directly
    # (not assumed) that httpx2's own Cookies.set() correctly
    # overwrites an existing cookie of the same name and leaves any
    # others untouched, which is exactly what switching between
    # captured sessions within one test needs.
    client.cookies.set("elysium_session", session["elysium_session"])
    client.cookies.set("elysium_csrf", session["elysium_csrf"])


def test_login_wrong_password_and_nonexistent_username_are_identical(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")

    wrong_pw = _login(client, "alice", "wrong-pw")
    nonexistent = _login(client, "totally_fake_user", "anything")

    assert wrong_pw.status_code == nonexistent.status_code == 401
    assert wrong_pw.json() == nonexistent.json()


def test_login_success_sets_real_session_and_csrf_cookies(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")

    response = _login(client, "alice", "correct-pw")
    assert response.status_code == 204
    # No token in the JSON body at all -- see core/auth/auth_cookies.py's
    # own docstring for why returning it there too would defeat the
    # entire point of moving to an httponly cookie.
    assert response.content == b""
    assert len(client.cookies.get("elysium_session")) > 20
    assert len(client.cookies.get("elysium_csrf")) > 20
    # Genuinely different, independently-random values -- the CSRF
    # token is deliberately not derived from the session token itself.
    assert client.cookies.get("elysium_session") != client.cookies.get("elysium_csrf")


def test_login_locked_out_after_max_failed_attempts(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")

    for _ in range(5):
        _login(client, "alice", "wrong-pw")

    # The CORRECT password, on the very next attempt -- still rejected,
    # since the account is now locked out regardless of whether this
    # specific attempt's own password was right.
    response = _login(client, "alice", "correct-pw")
    assert response.status_code == 401


def test_login_lockout_response_is_identical_to_a_normal_wrong_password(client):
    # The real, uniform-denial property this whole mechanism was built
    # to preserve, not just to add rate limiting for its own sake --
    # confirmed directly, not assumed: a locked-out response and a
    # normal wrong-password response must be byte-for-byte identical.
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    for _ in range(5):
        _login(client, "alice", "wrong-pw")

    locked_out = _login(client, "alice", "correct-pw")
    normal_wrong_password = _login(client, "bob-not-locked-out", "wrong-pw")

    assert locked_out.status_code == normal_wrong_password.status_code == 401
    assert locked_out.json() == normal_wrong_password.json()


def test_login_lockout_applies_to_a_nonexistent_username_too(client):
    # Preserves the existing, already-established non-enumeration
    # property -- a made-up username locks out the exact same way a
    # real one does, so noticing which usernames get throttled can
    # never itself reveal which ones are real.
    for _ in range(5):
        _login(client, "totally_fake_user", "anything")

    response = _login(client, "totally_fake_user", "anything")
    assert response.status_code == 401


def test_login_success_clears_prior_failures(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")

    for _ in range(3):  # fewer than the 5-attempt threshold
        _login(client, "alice", "wrong-pw")

    success = _login(client, "alice", "correct-pw")
    assert success.status_code == 204

    # The counter was cleared by that success -- three MORE wrong
    # attempts now should not lock the account out, since they start
    # counting from zero again, not continuing from 3+3=6.
    for _ in range(3):
        _login(client, "alice", "wrong-pw")
    still_works = _login(client, "alice", "correct-pw")
    assert still_works.status_code == 204


def test_login_lockout_is_per_username_not_global(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    client.app.state.user_directory.create_user("bob", "correct-pw", None, "customer_service")

    for _ in range(5):
        _login(client, "alice", "wrong-pw")

    alice_response = _login(client, "alice", "correct-pw")
    bob_response = _login(client, "bob", "correct-pw")

    assert alice_response.status_code == 401
    assert bob_response.status_code == 204


def test_login_always_runs_real_password_verification_even_when_already_locked_out(client):
    # THE actual timing-safety property, verified structurally rather
    # than by measuring flaky wall-clock timing: a locked-out account
    # must still trigger a REAL call to verify_credential() (the slow,
    # real argon2id check), not a short-circuit that skips it -- see
    # login_attempt_tracker.py's own module docstring for the full
    # reasoning (a locked-out account returning measurably faster than
    # a real wrong-password check would itself leak that the account
    # exists and has recent activity against it).
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    for _ in range(5):
        _login(client, "alice", "wrong-pw")

    real_verify = client.app.state.credential_store.verify_credential
    with patch.object(client.app.state.credential_store, "verify_credential", wraps=real_verify) as spy:
        _login(client, "alice", "correct-pw")
        assert spy.called


def test_security_headers_are_present_on_every_response(client):
    # A real, found gap: this app previously set none of these at all.
    # Checked on TWO genuinely different response shapes -- a real
    # login (200) and a rejected one (401) -- confirming the
    # middleware applies universally, not just to one specific route
    # or one specific status code.
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    success = _login(client, "alice", "correct-pw")
    failure = _login(client, "alice", "wrong-pw")

    for response in (success, failure):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "same-origin"
        # Verified directly (grepped the real source for inline
        # style={{}} props, external <script>/<link> tags, and any
        # CDN/external CSS reference -- all zero) that this app is
        # genuinely, fully self-contained before writing a policy this
        # strict -- see api/app.py's own comment for the full check.
        assert response.headers["content-security-policy"] == (
            "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )


def test_query_without_token_is_rejected(client):
    # A completely unauthenticated request (no cookies at all) now
    # fails the CSRF check FIRST -- 403, not 401 -- since csrf_protect
    # runs as global middleware, before get_current_user() (a route-
    # level dependency) ever gets a chance to run. Still genuinely
    # rejected either way; this is a real, correct consequence of the
    # CSRF migration, not a regression.
    response = client.post("/api/query", json={"query": "test"})
    assert response.status_code == 403


def test_search_objects_without_token_is_rejected(client):
    response = client.get("/api/objects/Customer/search", params={"q": "ada"})
    assert response.status_code == 401


def test_my_visible_schema_without_token_is_rejected(client):
    response = client.get("/api/me/visible-schema")
    assert response.status_code == 401


def test_my_visible_schema_returns_the_callers_own_view(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/me/visible-schema")

    assert response.status_code == 200
    # confirmed directly against a real mediator.visible_schema() call
    # for the customer_service role, not assumed.
    assert set(response.json().keys()) == {"Customer", "Transaction", "SupportTicket"}


def test_my_profile_without_token_is_rejected(client):
    response = client.get("/api/me")
    assert response.status_code == 401


def test_my_profile_returns_the_callers_own_username_role_and_mac_value(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/me")

    assert response.status_code == 200
    assert response.json() == {"username": "alice", "role_name": "customer_service", "mac_value": "us-west"}


def test_my_profile_differs_by_which_user_is_logged_in(client):
    # The same real check test_my_visible_schema_differs_by_role_not_a_
    # static_response applies to this sibling route too -- a genuinely
    # caller-specific response, not a value that happens to look right
    # for whichever user a test logs in as first.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    client.app.state.user_directory.create_user("bob", "correct-pw", "us-east", "customer_service")

    _login(client, "alice", "correct-pw")
    alice_profile = client.get("/api/me").json()

    client.post("/api/logout")
    _login(client, "bob", "correct-pw")
    bob_profile = client.get("/api/me").json()

    assert alice_profile["username"] == "alice"
    assert alice_profile["mac_value"] == "us-west"
    assert bob_profile["username"] == "bob"
    assert bob_profile["mac_value"] == "us-east"


def test_me_routes_set_cache_control_no_store(client):
    # A real, deliberate security property, not incidental -- every
    # /me/* route returns data specific to whichever session's cookie
    # is actually presented, and must never be persisted by a shared
    # browser profile or an intermediate cache and later handed back
    # to a different person on the same machine (confirmed as the
    # real, standard recommendation for this class of response before
    # adopting it, not assumed). Checked directly against the real,
    # final response headers for every one of the four real /me/*
    # routes, not just the one this change was originally about.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    for path in ("/api/me", "/api/me/visible-apps", "/api/me/visible-schema", "/api/me/visible-action-types"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store", f"{path} is missing Cache-Control: no-store"


def test_visible_apps_hides_admin_without_manage_users(client):
    # editor (fixtures/policy.yaml) holds no manage:users grant --
    # Admin must be genuinely absent from the response, not merely
    # something the frontend is trusted to hide.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/me/visible-apps")

    assert response.status_code == 200
    names = {app["name"] for app in response.json()}
    assert {"Query", "Browse"}.issubset(names)
    assert "Admin" not in names


def test_visible_apps_shows_admin_with_manage_users(client):
    _make_admin(client)

    response = client.get("/api/me/visible-apps")

    assert response.status_code == 200
    names = {app["name"] for app in response.json()}
    assert "Admin" in names


def test_my_visible_schema_differs_by_role_not_a_static_response(client):
    # customer_service_no_email (user_dave's real role in fixtures/
    # policy.yaml) withholds read:Customer.email specifically -- proves
    # this route genuinely reflects the CALLER's own grants, not a
    # cached or role-blind response.
    client.app.state.user_directory.create_user("dave", "correct-pw", "us-west", "customer_service_no_email")
    _login(client, "dave", "correct-pw")

    response = client.get("/api/me/visible-schema")

    assert response.status_code == 200
    assert "email" not in response.json()["Customer"]["fields"]


def test_my_visible_schema_shows_title_field_when_granted(client):
    # customer_service holds read:Customer.name, and Customer's own
    # title_field IS "name" (fixtures/ontology_schema.yaml) -- must be
    # surfaced. customer_service_no_email (previous test) withholds a
    # DIFFERENT field (email), not name -- together these two tests
    # prove title_field's own visibility genuinely tracks its OWN
    # field's grant, not some unrelated field's.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/me/visible-schema")

    assert response.status_code == 200
    assert response.json()["Customer"]["title_field"] == "name"


def test_my_visible_schema_withholds_title_field_when_not_granted(client):
    # customer_service_link_only holds read:Customer and read:Customer.
    # customer_id (the id_field) but NO read:Customer.name at all --
    # title_field must come back None, matching id_field's own,
    # already-established RBAC-gating pattern exactly (declaring a
    # field AS the title never makes its own value visible on its own).
    client.app.state.user_directory.create_user("carol", "correct-pw", "us-west", "customer_service_link_only")
    _login(client, "carol", "correct-pw")

    response = client.get("/api/me/visible-schema")

    assert response.status_code == 200
    assert response.json()["Customer"]["title_field"] is None


def test_search_objects_finds_a_partial_match_with_real_field_values(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get(
        "/api/objects/Customer/search", params={"q": "ada"}
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
    _login(client, "alice", "correct-pw")

    response = client.get(
        "/api/objects/Customer/search", params={"q": ""}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_matches"] == 2
    assert {result["id"] for result in body["results"]} == {"cust_001", "cust_002"}


def test_search_objects_no_query_param_at_all_also_browses_all(client):
    # q is genuinely optional -- omitting it entirely (not just passing
    # an empty string) must behave identically.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/objects/Customer/search")

    assert response.status_code == 200
    assert response.json()["total_matches"] == 2


def test_search_objects_blocks_cross_region_mac(client):
    # THE real security proof, not just a functional one: "ada" would
    # textually match cust_001's own real name regardless of who asks
    # -- bob (us-east) must still get nothing back, since cust_001 is
    # us-west, matching test_query's own established MAC-boundary
    # testing pattern elsewhere in this file.
    client.app.state.user_directory.create_user("bob", "correct-pw", "us-east", "customer_service")
    _login(client, "bob", "correct-pw")

    response = client.get(
        "/api/objects/Customer/search", params={"q": "ada"}
    )

    assert response.status_code == 200
    assert response.json() == {"results": [], "total_matches": 0}


def test_search_objects_no_match_returns_empty_results(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get(
        "/api/objects/Customer/search", params={"q": "zzz_nonexistent"}
    )

    assert response.status_code == 200
    assert response.json() == {"results": [], "total_matches": 0}


def test_search_objects_unknown_type_returns_empty_results_not_error(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get(
        "/api/objects/TotallyFakeType/search", params={"q": "ada"}
    )

    assert response.status_code == 200
    assert response.json() == {"results": [], "total_matches": 0}


def test_object_detail_without_token_is_rejected(client):
    response = client.get("/api/objects/Customer/cust_001")
    assert response.status_code == 401


def test_object_detail_returns_every_visible_field_including_a_link(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/objects/Customer/cust_001")

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
    _login(client, "alice", "correct-pw")

    response = client.get("/api/objects/Customer/cust_does_not_exist")

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
    _login(client, "bob", "correct-pw")

    denied = client.get("/api/objects/Customer/cust_003")
    nonexistent = client.get("/api/objects/Customer/cust_does_not_exist")

    assert denied.status_code == nonexistent.status_code == 200
    assert all(value is None for value in denied.json()["fields"].values())
    assert set(denied.json()["fields"].keys()) == set(nonexistent.json()["fields"].keys())


def test_object_detail_unknown_type_returns_200_with_empty_fields(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/objects/TotallyFakeType/whatever")

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
    _login(client, "alice", "correct-pw")

    response = client.get(
        "/api/objects/Customer/search", params={"q": "ada"}
    )

    assert response.status_code == 200
    assert "results" in response.json()
    assert "total_matches" in response.json()


def test_visible_action_types_without_token_is_rejected(client):
    response = client.get("/api/me/visible-action-types")
    assert response.status_code == 401


def test_visible_action_types_returns_the_callers_own_view(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/me/visible-action-types")

    assert response.status_code == 200
    body = response.json()
    # editor's real, confirmed grants (fixtures/policy.yaml) --
    # UpdateCustomerName and CreateCustomer, NOT TransferFunds.
    assert set(body.keys()) == {"UpdateCustomerName", "CreateCustomer"}
    assert body["UpdateCustomerName"]["parameters"]["customer_id"]["type"] == "object_reference"


def test_visible_action_types_differs_by_role_not_a_static_response(client):
    client.app.state.user_directory.create_user("bob", "correct-pw", "us-west", "customer_service")
    _login(client, "bob", "correct-pw")

    response = client.get("/api/me/visible-action-types")

    assert response.status_code == 200
    # customer_service has NO execute: grants at all (fixtures/
    # policy.yaml) -- proves this route genuinely reflects the
    # CALLER's own grants, not a cached or role-blind response.
    assert response.json() == {}


def test_propose_action_without_token_is_rejected(client):
    # Same reasoning as test_query_without_token_is_rejected above --
    # CSRF middleware rejects a cookie-less request before auth ever
    # runs.
    response = client.post("/api/actions/UpdateCustomerName", json={"parameters": {}})
    assert response.status_code == 403


def test_propose_action_succeeds_and_returns_a_real_pending_write(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    _login(client, "alice", "correct-pw")

    response = client.post(
        "/api/actions/UpdateCustomerName",
        json={"parameters": {"customer_id": "cust_001", "new_name": "Ada Lovelace"}},
        headers=_csrf_headers(client),
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
    _login(client, "alice", "correct-pw")

    propose_response = client.post(
        "/api/actions/UpdateCustomerName",
        json={"parameters": {"customer_id": "cust_002", "new_name": "Bram F. Feldman"}},
        headers=_csrf_headers(client),
    )
    write_id = propose_response.json()["pending_write"]["id"]

    confirm_response = client.post(
        f"/api/writes/{write_id}/confirm", json={"approved": True}, headers=_csrf_headers(client)
    )
    assert confirm_response.status_code == 200

    detail_response = client.get("/api/objects/Customer/cust_002")
    assert detail_response.json()["fields"]["name"] == "Bram F. Feldman"


def test_propose_action_rejected_leaves_the_database_unchanged(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    _login(client, "alice", "correct-pw")

    propose_response = client.post(
        "/api/actions/UpdateCustomerName",
        json={"parameters": {"customer_id": "cust_001", "new_name": "Someone Else"}},
        headers=_csrf_headers(client),
    )
    write_id = propose_response.json()["pending_write"]["id"]

    client.post(
        f"/api/writes/{write_id}/confirm", json={"approved": False}, headers=_csrf_headers(client)
    )

    detail_response = client.get("/api/objects/Customer/cust_001")
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
    _login(client, "alice", "correct-pw")

    unknown = client.post(
        "/api/actions/TotallyFakeAction", json={"parameters": {}}, headers=_csrf_headers(client)
    )
    unauthorized = client.post(
        "/api/actions/TransferFunds",
        json={"parameters": {
            "from_account_id": "acc_checking", "to_account_id": "acc_savings",
            "new_from_balance": 1, "new_to_balance": 1,
        }},
        headers=_csrf_headers(client),
    )

    assert unknown.status_code == unauthorized.status_code == 400
    assert unknown.json() == unauthorized.json()


def test_propose_action_missing_required_parameter_returns_the_same_generic_error(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    _login(client, "alice", "correct-pw")

    response = client.post(
        "/api/actions/UpdateCustomerName",
        json={"parameters": {"customer_id": "cust_001"}},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "That action could not be proposed. Check the action name and parameters, "
        "and that you're authorized to perform it."
    )


def test_propose_action_cross_region_mac_denial_returns_the_same_generic_error(client):
    # cust_003 is us-east; alice (editor) is us-west.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    _login(client, "alice", "correct-pw")

    response = client.post(
        "/api/actions/UpdateCustomerName",
        json={"parameters": {"customer_id": "cust_003", "new_name": "X"}},
        headers=_csrf_headers(client),
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
    _login(client, "carol", "correct-pw")

    response = client.get("/api/me/visible-action-types")

    assert response.status_code == 200
    assert set(response.json().keys()) == {"UpdateCustomerName", "CreateCustomer", "TransferFunds"}


def test_visible_action_types_executable_flag_is_false_with_no_execute_grants(client):
    # process_auditor sees the whole catalog (previous test) but holds
    # NO execute: grants at all -- every entry's own "executable" flag
    # must be false, matching what the frontend needs to decide
    # whether to render a button for it at all (see ObjectDetailPanel.
    # jsx's own comment).
    client.app.state.user_directory.create_user("carol", "correct-pw", "us-west", "process_auditor")
    _login(client, "carol", "correct-pw")

    response = client.get("/api/me/visible-action-types")

    body = response.json()
    assert all(action_def["executable"] is False for action_def in body.values())


def test_visible_action_types_executable_flag_differentiates_within_one_response(client):
    # THE real proof of per-action differentiation, not just an all-
    # or-nothing role: senior_auditor holds discover:action_types
    # (sees all three) AND execute:UpdateCustomerName specifically
    # (can genuinely invoke only that one) -- confirms "executable"
    # is computed PER action, not a single, role-wide flag.
    client.app.state.user_directory.create_user("dana", "correct-pw", "us-west", "senior_auditor")
    _login(client, "dana", "correct-pw")

    response = client.get("/api/me/visible-action-types")

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
    _login(client, "alice", "correct-pw")

    response = client.get("/api/me/visible-action-types")

    body = response.json()
    assert set(body.keys()) == {"UpdateCustomerName", "CreateCustomer"}
    assert all(action_def["executable"] is True for action_def in body.values())


def test_propose_action_unknown_action_shows_the_real_message_for_a_discover_holder(client):
    client.app.state.user_directory.create_user("carol", "correct-pw", "us-west", "process_auditor")
    _login(client, "carol", "correct-pw")

    response = client.post(
        "/api/actions/TotallyFakeAction", json={"parameters": {}}, headers=_csrf_headers(client)
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown action_type: 'TotallyFakeAction'"


def test_propose_action_real_but_unauthorized_shows_403_for_a_discover_holder(client):
    # process_auditor can SEE TransferFunds (previous test) but holds
    # no execute: grant for it at all -- the real, unchanged
    # authorization gate still refuses it, now with a real, specific
    # 403 rather than the generic 400 every other role gets.
    client.app.state.user_directory.create_user("carol", "correct-pw", "us-west", "process_auditor")
    _login(client, "carol", "correct-pw")

    response = client.post(
        "/api/actions/TransferFunds",
        json={"parameters": {
            "from_account_id": "acc_checking", "to_account_id": "acc_savings",
            "new_from_balance": 1, "new_to_balance": 1,
        }},
        headers=_csrf_headers(client),
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
    _login(client, "carol", "correct-pw")

    unknown = client.post(
        "/api/actions/TotallyFakeAction", json={"parameters": {}}, headers=_csrf_headers(client)
    )
    unauthorized = client.post(
        "/api/actions/TransferFunds",
        json={"parameters": {
            "from_account_id": "acc_checking", "to_account_id": "acc_savings",
            "new_from_balance": 1, "new_to_balance": 1,
        }},
        headers=_csrf_headers(client),
    )

    assert unknown.status_code != unauthorized.status_code
    assert unknown.json() != unauthorized.json()


def test_create_user_without_manage_users_grant_is_rejected(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.post(
        "/api/users", json={"username": "bob", "password": "pw", "role_name": "customer_service"},
        headers=_csrf_headers(client),
    )
    assert response.status_code == 403


def test_create_user_with_manage_users_grant_succeeds_and_new_user_can_log_in(client):
    client.app.state.user_directory.create_user("admin_user", "adminpass", None, "admin")
    _login(client, "admin_user", "adminpass")

    create_response = client.post(
        "/api/users",
        json={"username": "newperson", "password": "newpass123",
              "mac_value": "us-west", "role_name": "customer_service"},
        headers=_csrf_headers(client),
    )
    assert create_response.status_code == 201

    login_response = _login(client, "newperson", "newpass123")
    assert login_response.status_code == 204


def test_logout_invalidates_the_token(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")

    logout_response = client.post("/api/logout", headers=_csrf_headers(client))
    assert logout_response.status_code == 204

    # Both cookies are genuinely GONE now (logout clears them) -- a
    # reused request fails the CSRF check first, same reasoning as
    # test_query_without_token_is_rejected above, not a real
    # Authorization header to omit anymore.
    reuse_response = client.post("/api/query", json={"query": "test"})
    assert reuse_response.status_code == 403


def test_query_end_to_end_with_mocked_llm(client):
    # fixtures/policy.yaml's customer_service role already includes
    # read:Customer.name -- no runtime role patching needed.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

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
        response = client.post("/api/query", json={"query": "test"}, headers=_csrf_headers(client))

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
    _login(client, "alice", "correct-pw")

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
        response = client.post("/api/query", json={"query": "test"}, headers=_csrf_headers(client))

    assert response.status_code == 409
    assert "answer" not in response.json()


def _propose_action(client, session=None, new_name="Updated Name"):
    # Helper: a real query that proposes a real named-action invocation
    # against the fixture's own Customer schema (cust_001), returns the
    # 202 response. Uses the same UpdateCustomerName action editor's
    # own execute: grant covers -- see policy.yaml's own comment.
    # No separate "object_id" field -- customer_id is just another
    # entry in "parameters" now, matching Palantir Foundry's own action
    # parameter model directly (see WriteMediator.propose_action()'s
    # own docstring).
    #
    # session=None (the common case): acts as the client's own,
    # CURRENTLY logged-in user, via its implicit cookie jar. Pass a
    # real _capture_session(client) dict instead when a caller needs
    # to act as a SPECIFIC, earlier-captured session -- see that
    # helper's own comment for why this is occasionally necessary.
    def fake_post(*args, **kwargs):
        response = MagicMock()
        response.json.return_value = {"message": {"content": json.dumps({
            "step": "propose_action", "action_type": "UpdateCustomerName",
            "parameters": {"customer_id": "cust_001", "new_name": new_name},
        })}}
        response.raise_for_status.return_value = None
        return response

    if session:
        _use_session(client, session)
    headers = _csrf_header_for(session) if session else _csrf_headers(client)

    with patch("adapters.ollama_adapter.requests.post", side_effect=fake_post):
        return client.post("/api/query", json={"query": "update the name"}, headers=headers)


def test_query_proposing_an_action_returns_202_with_a_reference(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    _login(client, "alice", "correct-pw")

    response = _propose_action(client)

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
    _login(client, "alice", "correct-pw")

    write_id = _propose_action(client).json()["pending_write"]["id"]

    confirm_response = client.post(
        f"/api/writes/{write_id}/confirm", json={"approved": True},
        headers=_csrf_headers(client),
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
    _login(client, "alice", "correct-pw")

    write_id = _propose_action(client).json()["pending_write"]["id"]

    confirm_response = client.post(
        f"/api/writes/{write_id}/confirm", json={"approved": False},
        headers=_csrf_headers(client),
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
    _login(client, "alice", "correct-pw")
    alice_session = _capture_session(client)
    _login(client, "eve", "correct-pw")
    eve_session = _capture_session(client)

    write_id = _propose_action(client, alice_session).json()["pending_write"]["id"]

    _use_session(client, eve_session)
    wrong_user_response = client.post(
        f"/api/writes/{write_id}/confirm", json={"approved": True},
        headers=_csrf_header_for(eve_session),
    )
    unknown_id_response = client.post(
        "/api/writes/totally-fake-id/confirm", json={"approved": True},
        headers=_csrf_header_for(eve_session),
    )

    assert wrong_user_response.status_code == unknown_id_response.status_code == 404
    assert wrong_user_response.json() == unknown_id_response.json()


def _make_admin(client):
    # Logs in as a real admin through the client's own, normal cookie
    # jar (the common case for most callers -- nothing further needed
    # afterward). ALSO returns a _capture_session() dict, for the
    # small number of callers that need to act as this admin AND
    # another, separate user within the same test -- see that
    # helper's own comment.
    client.app.state.config.roles["admin"] = {"allowed_actions": frozenset(["manage:users", "manage:locks"])}
    client.app.state.user_directory.create_user("admin_user", "adminpass", None, "admin")
    _login(client, "admin_user", "adminpass")
    return _capture_session(client)


def test_list_users_requires_manage_users(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/users")
    assert response.status_code == 403


def test_list_users_returns_non_sensitive_metadata_only(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _make_admin(client)

    response = client.get("/api/users")
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
    _login(client, "alice", "correct-pw")
    session1 = _capture_session(client)
    _login(client, "alice", "correct-pw")
    session2 = _capture_session(client)

    _use_session(client, session1)
    response = client.post("/api/logout-all", headers=_csrf_header_for(session1))
    assert response.status_code == 204

    for session in (session1, session2):
        _use_session(client, session)
        result = client.post(
            "/api/query", json={"query": "test"},
            headers=_csrf_header_for(session),
        )
        assert result.status_code == 401


def test_admin_logout_all_for_a_target_user_requires_manage_users(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")

    # alice herself has no manage:users grant.
    response = client.post("/api/users/alice/logout-all", headers=_csrf_headers(client))
    assert response.status_code == 403


def test_admin_logout_all_for_a_target_user_works(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")
    alice_session = _capture_session(client)
    admin_session = _make_admin(client)

    _use_session(client, admin_session)
    response = client.post("/api/users/alice/logout-all", headers=_csrf_header_for(admin_session))
    assert response.status_code == 204

    _use_session(client, alice_session)
    result = client.post(
        "/api/query", json={"query": "test"},
        headers=_csrf_header_for(alice_session),
    )
    assert result.status_code == 401


def test_visible_schema_debug_view_shows_what_the_target_user_can_see(client):
    client.app.state.config.roles["customer_service"] = {"allowed_actions": [
        "read:Customer", "read:Customer.customer_id", "read:Customer.name",
    ]}
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _make_admin(client)

    response = client.get("/api/users/alice/visible-schema")
    assert response.status_code == 200
    body = response.json()
    assert "Customer" in body
    assert set(body["Customer"]["fields"].keys()) == {"name"}  # customer_id is the id_field, not a "fields" entry


def test_visible_schema_debug_view_requires_manage_users(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/users/alice/visible-schema")
    assert response.status_code == 403


def test_visible_schema_debug_view_for_unknown_user_is_404(client):
    _make_admin(client)
    response = client.get(
        "/api/users/totally_fake_user/visible-schema"
    )
    assert response.status_code == 404


def test_disable_user_blocks_new_logins_and_kills_existing_sessions(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")
    alice_session = _capture_session(client)
    admin_session = _make_admin(client)

    _use_session(client, admin_session)
    response = client.post("/api/users/alice/disable", headers=_csrf_header_for(admin_session))
    assert response.status_code == 204

    # Existing session immediately rejected -- not just future logins.
    _use_session(client, alice_session)
    existing_session_result = client.post(
        "/api/query", json={"query": "test"},
        headers=_csrf_header_for(alice_session),
    )
    assert existing_session_result.status_code == 401

    # New login attempt also blocked, same generic message as a wrong password.
    login_attempt = _login(client, "alice", "correct-pw")
    assert login_attempt.status_code == 401
    assert login_attempt.json()["detail"] == "Invalid username or password"


def test_disable_nonexistent_user_is_404(client):
    _make_admin(client)
    response = client.post("/api/users/totally_fake_user/disable", headers=_csrf_headers(client))
    assert response.status_code == 404


def test_enable_reverses_disable(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _make_admin(client)

    client.post("/api/users/alice/disable", headers=_csrf_headers(client))
    client.post("/api/users/alice/enable", headers=_csrf_headers(client))

    login_attempt = _login(client, "alice", "correct-pw")
    assert login_attempt.status_code == 204


def test_delete_user_removes_credential_and_kills_sessions(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")
    alice_session = _capture_session(client)
    admin_session = _make_admin(client)

    _use_session(client, admin_session)
    response = client.delete("/api/users/alice", headers=_csrf_header_for(admin_session))
    assert response.status_code == 204

    _use_session(client, alice_session)
    existing_session_result = client.post(
        "/api/query", json={"query": "test"},
        headers=_csrf_header_for(alice_session),
    )
    assert existing_session_result.status_code == 401

    login_attempt = _login(client, "alice", "correct-pw")
    assert login_attempt.status_code == 401


def test_delete_nonexistent_user_is_404(client):
    _make_admin(client)
    response = client.delete("/api/users/totally_fake_user", headers=_csrf_headers(client))
    assert response.status_code == 404


# --- Generic locking (api/routes.py's own /locks/{resource_name}/*
# routes, core/lock_store.py's own LockStore). Deep, direct-unit-test
# coverage of LockStore's own logic already lives in tests/unit/
# test_lock_store.py -- these are the real, HTTP-layer, end-to-end
# counterparts: request/response shapes, status codes, CSRF, and the
# one genuine permission gate (force-release).

def test_acquire_lock_returns_token_and_expiry(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.post("/api/locks/config/acquire", headers=_csrf_headers(client))

    assert response.status_code == 200
    body = response.json()
    assert "token" in body and body["token"]
    assert "expires_at" in body


def test_acquire_lock_already_held_by_another_user_returns_409_with_holder_info(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    client.app.state.user_directory.create_user("bob", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")
    client.post("/api/locks/config/acquire", headers=_csrf_headers(client))

    _login(client, "bob", "correct-pw")
    response = client.post("/api/locks/config/acquire", headers=_csrf_headers(client))

    assert response.status_code == 409
    assert response.json()["detail"]["lock"]["held_by"] == "alice"


def test_acquire_lock_requires_a_valid_csrf_token(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.post("/api/locks/config/acquire")

    assert response.status_code == 403


def test_refresh_lock_extends_the_lease(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")
    token = client.post("/api/locks/config/acquire", headers=_csrf_headers(client)).json()["token"]

    response = client.post(
        "/api/locks/config/refresh", json={"token": token}, headers=_csrf_headers(client)
    )

    assert response.status_code == 200
    assert "expires_at" in response.json()


def test_refresh_lock_with_wrong_token_returns_409(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")
    client.post("/api/locks/config/acquire", headers=_csrf_headers(client))

    response = client.post(
        "/api/locks/config/refresh", json={"token": "totally-wrong-token"}, headers=_csrf_headers(client)
    )

    assert response.status_code == 409


def test_release_lock_by_holder_succeeds(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")
    token = client.post("/api/locks/config/acquire", headers=_csrf_headers(client)).json()["token"]

    response = client.post(
        "/api/locks/config/release", json={"token": token}, headers=_csrf_headers(client)
    )

    assert response.status_code == 204
    assert client.get("/api/locks/config", headers=_csrf_headers(client)).json() == {"locked": False}


def test_release_lock_by_a_different_user_returns_404(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    client.app.state.user_directory.create_user("bob", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")
    token = client.post("/api/locks/config/acquire", headers=_csrf_headers(client)).json()["token"]

    _login(client, "bob", "correct-pw")
    response = client.post(
        "/api/locks/config/release", json={"token": token}, headers=_csrf_headers(client)
    )

    assert response.status_code == 404


def test_force_release_lock_requires_manage_locks(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")
    client.post("/api/locks/config/acquire", headers=_csrf_headers(client))

    # alice herself is NOT the holder of manage:locks -- a plain
    # customer_service role, same fixture shape as every other
    # RBAC-gated-route test in this file.
    response = client.post("/api/locks/config/force-release", headers=_csrf_headers(client))

    assert response.status_code == 403


def test_force_release_lock_by_manage_locks_holder_succeeds_even_though_they_never_held_it(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")
    client.post("/api/locks/config/acquire", headers=_csrf_headers(client))

    _make_admin(client)
    response = client.post("/api/locks/config/force-release", headers=_csrf_headers(client))

    assert response.status_code == 204
    assert client.get("/api/locks/config", headers=_csrf_headers(client)).json() == {"locked": False}


def test_lock_status_route_reflects_real_state(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")

    assert client.get("/api/locks/config", headers=_csrf_headers(client)).json() == {"locked": False}

    client.post("/api/locks/config/acquire", headers=_csrf_headers(client))
    status = client.get("/api/locks/config", headers=_csrf_headers(client)).json()

    assert status["locked"] is True
    assert status["held_by"] == "alice"

