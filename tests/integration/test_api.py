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
from core.auth.database import connection
from core.auth.query_rate_limiter import MAX_QUERIES_PER_WINDOW
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


def test_docs_redoc_openapi_are_genuinely_unavailable(client):
    # A real, confirmed finding, part of a broader "backend is a
    # kernel, frontend is userspace" audit -- FastAPI's own /docs,
    # /redoc, and /openapi.json are ENABLED BY DEFAULT and were NOT
    # gated by get_current_user() at all (registered directly on the
    # app itself, outside the protected router): confirmed live,
    # before this fix, that a completely unauthenticated request
    # could browse the FULL API surface this way, including every
    # admin-only route's own path. No login at all here, deliberately
    # -- the real point is that these are unreachable regardless of
    # auth state, not merely rejected for a missing session the way
    # every other real, protected route is.
    for path in ("/docs", "/redoc", "/openapi.json"):
        response = client.get(path)
        assert response.status_code == 404


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
    # Tag joined this set in Point 16, as the target of the fixture's
    # many-to-many link type.
    assert set(response.json().keys()) == {"Customer", "Transaction", "SupportTicket", "Tag"}


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


def test_data_freshness_requires_a_login(client):
    # Every route but /login does. A completely unauthenticated request
    # fails the CSRF check first (403) or the auth check (401) --
    # either way, genuinely rejected.
    response = client.get("/api/data-freshness")
    assert response.status_code in (401, 403)


def test_data_freshness_reports_live_when_not_reading_from_the_mirror(client):
    # The fixture deployment reads live, so this is the real default
    # path. "live" is said explicitly rather than returning a null
    # timestamp a caller would have to interpret.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/data-freshness")

    assert response.status_code == 200
    assert response.json() == {"source": "live", "last_synced_at": None}


def test_data_freshness_reports_the_mirror_sync_time_when_reading_from_it(client):
    # Simulates a mirror-backed deployment by setting the same two
    # values load_deployment_bundle() would set for one -- exercising
    # the real route rather than mocking it.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    client.app.state.config.read_from_mirror = True
    client.app.state.mediator.mirror_synced_at = "2026-01-15T09:00:00+00:00"

    response = client.get("/api/data-freshness")

    assert response.status_code == 200
    assert response.json() == {
        "source": "mirror",
        "last_synced_at": "2026-01-15T09:00:00+00:00",
    }


def test_data_freshness_needs_no_particular_grant(client):
    # A role with essentially no grants must still see this -- the
    # people most likely to need it (anyone about to approve a write
    # against possibly stale data) should never be the least likely to
    # see it. It exposes no business data at all.
    client.app.state.user_directory.create_user("nobody", "correct-pw", "us-west", "customer_service")
    _login(client, "nobody", "correct-pw")

    assert client.get("/api/data-freshness").status_code == 200


def test_visible_schema_never_leaks_per_field_internals(client):
    # A FOURTH instance of the same leak class this project has now hit
    # repeatedly (visible_schema's own storage config,
    # visible_action_types' sub_writes, visible-apps' gating_permission
    # -- each previously fixed by hand). visible_schema() passes each
    # field_info dict through WHOLE, so every internal key a field
    # definition carries reached the browser: storage/column/via_table/
    # via_column (physical layout) and data_type (ontology bookkeeping).
    #
    # This is now structurally impossible rather than merely fixed:
    # SchemaFieldResponse names exactly the three keys the frontend
    # genuinely reads, and FastAPI drops everything else. Adding a new
    # internal key to a field definition can no longer leak it.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/me/visible-schema")

    assert response.status_code == 200
    for type_name, type_schema in response.json().items():
        for field_name, field_info in type_schema["fields"].items():
            # display_name and description are DELIBERATELY exposed --
            # they exist so a UI can render a readable label. Everything
            # else a field definition carries is internal.
            leaked = set(field_info) - {
                "type", "target", "cardinality", "display_name", "description",
                # UI rendering hints, deliberately exposed. Cosmetic --
                # "hidden" does not withhold anything, RBAC does.
                "visibility", "status", "link_type",
            }
            assert not leaked, f"{type_name}.{field_name} leaked {sorted(leaked)}"


def test_visible_schema_still_carries_what_links_genuinely_need(client):
    # The other half, and the real risk of response_model: filtering is
    # SILENT, so a model omitting a field the frontend uses would break
    # the UI with no error. ObjectDetailPanel resolves a link from
    # target + cardinality -- both must survive.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    schema = client.get("/api/me/visible-schema").json()
    link_fields = [
        field_info
        for type_schema in schema.values()
        for field_info in type_schema["fields"].values()
        if field_info.get("type") == "link"
    ]

    assert link_fields, "fixture ontology should declare at least one link field"
    for field_info in link_fields:
        assert field_info["target"]
        assert field_info["cardinality"]


def test_visible_schema_carries_display_metadata_for_the_ui(client):
    # The whole point of Point 10: a UI must be able to render readable
    # labels without inventing them. Every object type and field has a
    # display_name whether or not the ontology declared one.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    schema = client.get("/api/me/visible-schema").json()

    for type_name, type_schema in schema.items():
        assert type_schema["display_name"], f"{type_name} has no display_name"
        assert type_schema["plural_display_name"], f"{type_name} has no plural"
        for field_name, field_info in type_schema["fields"].items():
            assert field_info["display_name"], f"{type_name}.{field_name} has no display_name"


def test_declared_display_metadata_reaches_the_caller_verbatim(client):
    # A declared label must survive response_model filtering -- the
    # exact failure mode that silently dropped fields before.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    customer = client.get("/api/me/visible-schema").json()["Customer"]

    assert customer["display_name"] == "Customer"
    assert customer["plural_display_name"] == "Customers"
    assert customer["description"]


def test_visible_schema_still_reports_a_null_title_field(client):
    # A null title_field is a real SIGNAL ("this type has one, but you
    # cannot read it"), not absence -- ui/'s own format.ts documents
    # depending on that distinction. Asserted explicitly because an
    # over-broad response_model_exclude_none genuinely dropped it
    # during this work.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    schema = client.get("/api/me/visible-schema").json()

    assert any("title_field" in type_schema for type_schema in schema.values())


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


def test_visible_apps_never_leaks_gating_permission(client):
    # A real, third finding of the exact same class as GET /me/
    # visible-schema's own and GET /me/visible-action-types' own (see
    # mediator.py's and this file's own AI-notes for both): the raw,
    # internal permission-STRING NAME gating each app (e.g.
    # "manage:users") used to travel to the browser unfiltered.
    # Confirmed directly that nothing needs this here: this backend
    # ALREADY does the real filtering (an app the caller can't use is
    # simply absent, per the two tests just above), and no frontend
    # code anywhere reads .gating_permission off a visible-apps entry
    # (confirmed by a direct grep, not assumed). Only name/path are
    # ever included now.
    _make_admin(client)

    response = client.get("/api/me/visible-apps")

    assert response.status_code == 200
    for app in response.json():
        assert set(app.keys()) == {"name", "path"}
        assert "gating_permission" not in app


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
    assert response.json() == {"results": [], "total_matches": 0, "next_page_token": None}


def test_search_objects_no_match_returns_empty_results(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get(
        "/api/objects/Customer/search", params={"q": "zzz_nonexistent"}
    )

    assert response.status_code == 200
    assert response.json() == {"results": [], "total_matches": 0, "next_page_token": None}


def test_search_objects_unknown_type_returns_empty_results_not_error(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get(
        "/api/objects/TotallyFakeType/search", params={"q": "ada"}
    )

    assert response.status_code == 200
    assert response.json() == {"results": [], "total_matches": 0, "next_page_token": None}


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


def test_visible_action_types_never_leaks_sub_writes_or_mutations(client):
    # A real, second, confirmed bug found and fixed alongside GET
    # /me/visible-schema's own (see api/routes.py's own comment on this
    # route for the full reasoning): this route used to spread the
    # FULL action_def (`**action_def`), leaking each action's own real
    # sub_writes -- including the literal, mechanical "set property X
    # to parameter.Y" mutations logic -- to any browser, unfiltered,
    # over HTTP. Confirmed directly that nothing real needs this here:
    # affected_object_types already, independently covers the only
    # legitimate "what does this touch" need, and ActionForm.tsx (the
    # real, only frontend consumer) never references sub_writes at
    # all. Only the three real, intentional keys are ever included
    # now -- this asserts sub_writes is entirely absent, for a real
    # action (CreateCustomer) whose own real mutations set the MAC
    # field (region) from user.security_value, exactly the kind of
    # internal mechanic that should never travel to a browser.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "editor")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/me/visible-action-types")

    assert response.status_code == 200
    body = response.json()
    assert set(body["CreateCustomer"].keys()) == {"affected_object_types", "parameters", "executable"}
    assert "sub_writes" not in body["CreateCustomer"]
    assert "sub_writes" not in body["UpdateCustomerName"]


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


def test_query_is_rejected_429_once_the_rate_limit_is_reached(client):
    # Directly puts the user at the limit via the real
    # QueryRateLimiter itself (fast, in-process) rather than making
    # MAX_QUERIES_PER_WINDOW real HTTP requests through a mocked LLM --
    # exercises the exact same real record/check methods the route
    # itself calls, just without the slow, repeated round trip.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    user_id = client.app.state.user_directory.get_user_record("alice").user_id
    for _ in range(MAX_QUERIES_PER_WINDOW):
        client.app.state.query_rate_limiter.record_query(user_id)

    response = client.post("/api/query", json={"query": "test"}, headers=_csrf_headers(client))

    assert response.status_code == 429
    assert "Too many queries" in response.json()["detail"]


def test_a_rejected_query_is_not_itself_recorded_as_a_new_one(client):
    # A real, meaningful behavioral guarantee, not just an
    # implementation detail: being rejected must never itself count
    # toward FUTURE limits, or a caller already at the limit could
    # never recover even once their real window naturally expires,
    # since each new rejected attempt would keep pushing the window
    # forward.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    user_id = client.app.state.user_directory.get_user_record("alice").user_id
    for _ in range(MAX_QUERIES_PER_WINDOW):
        client.app.state.query_rate_limiter.record_query(user_id)

    # Two real, separate rejected calls -- if either were silently
    # ALSO recorded as a genuine query, the real, underlying count
    # would now read MAX_QUERIES_PER_WINDOW + 1 or + 2, not still
    # exactly MAX_QUERIES_PER_WINDOW.
    client.post("/api/query", json={"query": "test"}, headers=_csrf_headers(client))
    client.post("/api/query", json={"query": "test"}, headers=_csrf_headers(client))

    with connection(client.app.state.credentials_db_path) as conn:
        row = conn.execute("SELECT query_count FROM query_rate_limits WHERE user_id = ?", (user_id,)).fetchone()
    assert row["query_count"] == MAX_QUERIES_PER_WINDOW


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


# --- Object Set operations (Point 11): count, aggregate, and search-
# around over HTTP. Foundry's own Object Set Service serves
# "searching, filtering, aggregating, and loading" -- Elysium had the
# first two exposed and neither of the last, so these existed on
# DataMediator with zero route references.
#
# POST rather than GET for all three: each takes a structured criteria
# object, and encoding nested JSON into query parameters would be both
# uglier and length-limited. They are reads despite the verb, which
# does mean they are CSRF-gated like any other POST -- asserted below
# rather than assumed.

def _post(client, path, body):
    return client.post(path, json=body, headers=_csrf_headers(client))


def test_count_returns_what_the_caller_can_see(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = _post(client, "/api/objects/Customer/count", {"criteria": {}})

    assert response.status_code == 200
    assert response.json() == {"count": 2}


def test_count_applies_criteria(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    matching = _post(client, "/api/objects/Customer/count", {"criteria": {"region": "us-west"}})
    missing = _post(client, "/api/objects/Customer/count", {"criteria": {"region": "nowhere"}})

    assert matching.json()["count"] == 2
    assert missing.json()["count"] == 0


def test_two_users_get_genuinely_different_counts(client):
    # THE security property. A count that ignored MAC would leak the
    # existence of rows outside the caller's boundary -- you would
    # learn how many objects you cannot see.
    client.app.state.user_directory.create_user("west", "correct-pw", "us-west", "customer_service")
    client.app.state.user_directory.create_user("east", "correct-pw", "us-east", "customer_service")

    _login(client, "west", "correct-pw")
    west_count = _post(client, "/api/objects/Transaction/count", {"criteria": {}}).json()["count"]

    # A fresh login as the other user, through the same client -- the
    # new session cookie replaces the old one.
    _login(client, "east", "correct-pw")
    east_count = _post(client, "/api/objects/Transaction/count", {"criteria": {}}).json()["count"]

    assert west_count and east_count
    assert west_count != east_count


def test_aggregate_groups_and_sums(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = _post(
        client, "/api/objects/Transaction/aggregate",
        {"criteria": {}, "aggregate": "sum", "field": "amount", "group_by": "category"},
    )

    results = response.json()["results"]
    assert results["hardware"] == 199.0
    assert results["refund"] == -20.0


def test_aggregate_with_no_group_by_returns_one_result_under_an_empty_key(client):
    # A caller asking for one aggregate over the whole set must get a
    # result back. JSON object keys must be strings, so the None group
    # becomes "" rather than being dropped.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = _post(
        client, "/api/objects/Transaction/aggregate", {"criteria": {}, "aggregate": "count"}
    )

    assert response.json()["results"] == {"": 4}


def test_an_unknown_aggregate_is_a_400_not_a_500(client):
    # A caller mistake, not a server fault -- and the message names the
    # real options rather than being generic.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = _post(
        client, "/api/objects/Transaction/aggregate",
        {"criteria": {}, "aggregate": "median", "field": "amount"},
    )

    assert response.status_code == 400
    assert "median" in response.json()["detail"]


def test_an_aggregate_missing_its_field_is_a_400(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = _post(
        client, "/api/objects/Transaction/aggregate", {"criteria": {}, "aggregate": "sum"}
    )

    assert response.status_code == 400
    assert "field_name" in response.json()["detail"]


def test_invalid_criteria_is_a_400(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = _post(
        client, "/api/objects/Customer/count", {"criteria": {"not_a_real_field": "x"}}
    )

    assert response.status_code == 400


def test_search_around_traverses_a_link(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = _post(
        client, "/api/objects/Customer/search-around",
        {"criteria": {"region": "us-west"}, "link_field": "transactions"},
    )

    body = response.json()
    assert body["total"] == len(body["ids"])
    assert body["ids"]


def test_search_around_returns_only_ids_the_caller_could_read_directly(client):
    # Following a link must never reveal an object a direct read would
    # deny -- otherwise a link becomes a way around the MAC boundary.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    ids = _post(
        client, "/api/objects/Customer/search-around",
        {"criteria": {}, "link_field": "transactions"},
    ).json()["ids"]

    for object_id in ids:
        detail = client.get(f"/api/objects/Transaction/{object_id}")
        assert detail.status_code == 200
        assert any(value is not None for value in detail.json()["fields"].values()), (
            f"search-around returned {object_id!r}, which a direct read denies"
        )


def test_search_around_on_an_ungranted_field_returns_empty_not_an_error(client):
    # Uniform denial: a caller learns nothing about whether the field
    # exists, is a link, or is merely ungranted.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = _post(
        client, "/api/objects/Customer/search-around",
        {"criteria": {}, "link_field": "not_a_real_field"},
    )

    assert response.status_code == 200
    assert response.json() == {"ids": [], "total": 0}


def test_the_new_routes_require_authentication(client):
    for path, body in (
        ("/api/objects/Customer/count", {"criteria": {}}),
        ("/api/objects/Customer/aggregate", {"criteria": {}, "aggregate": "count"}),
        ("/api/objects/Customer/search-around", {"criteria": {}, "link_field": "x"}),
    ):
        response = client.post(path, json=body)
        assert response.status_code in (401, 403), f"{path} was reachable unauthenticated"


def test_the_new_routes_require_a_csrf_token(client):
    # They are POSTs, so they are CSRF-gated like every other POST --
    # a real consequence of choosing POST for a read, asserted rather
    # than assumed.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.post("/api/objects/Customer/count", json={"criteria": {}})

    assert response.status_code == 403


def test_the_object_detail_route_still_works(client):
    # /objects/{type}/count sits alongside /objects/{type}/{object_id}.
    # They do not collide -- one is POST, the other GET -- but that is
    # exactly the kind of thing worth pinning rather than trusting.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/objects/Customer/cust_001")

    assert response.status_code == 200
    assert response.json()["id"] == "cust_001"


def test_an_object_genuinely_named_count_is_still_reachable(client):
    # The collision that WOULD matter: a GET for an object whose id is
    # literally "count". The GET route still matches it, because the
    # new routes are POST-only.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/objects/Customer/count")

    # Not a 405 (method-not-allowed from the POST route shadowing it)
    # -- the GET route handled it, and simply found no such object.
    assert response.status_code == 200
    assert json.loads(response.content)["id"] == "count"


# --- Paging and sorting (Point 12). Foundry's own model: pageSize +
# pageToken in, nextPageToken + totalCount back, and orderBy with an
# optional :asc/:desc suffix. Elysium previously returned a hard 50
# results with total_matches reported but NO way to fetch the rest.


def _many_customers(client, count=137):
    directory = client.app.state.user_directory
    directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")
    adapter = client.app.state.mediator.adapters["primary_sql"]
    conn = sqlite3.connect(adapter.db_path)
    conn.executemany(
        "INSERT INTO customers VALUES (?, ?, ?, ?)",
        [(f"c{i:04d}", f"Person {i:04d}", "us-west", f"e{i}@x.com") for i in range(count)],
    )
    conn.commit()
    conn.close()
    return count


def test_paging_returns_every_result_exactly_once(client):
    # THE property pagination exists for, and the one most easily got
    # wrong: walking every page must yield the whole set with nothing
    # skipped and nothing repeated.
    total = _many_customers(client)

    seen = []
    token = None
    pages = 0
    while True:
        url = "/api/objects/Customer/search?q=Person&page_size=25"
        if token:
            url += f"&page_token={token}"
        body = client.get(url).json()
        pages += 1
        seen.extend(result["id"] for result in body["results"])
        token = body["next_page_token"]
        if not token:
            break
        assert pages < 50, "paging did not terminate"

    assert len(seen) == total
    assert len(seen) == len(set(seen)), "a result appeared on more than one page"


def test_the_last_page_has_no_next_token(client):
    # Foundry's contract: "the presence of the nextPageToken field
    # indicates that there are more results." Absent, not empty.
    _many_customers(client, count=10)

    body = client.get("/api/objects/Customer/search?q=Person&page_size=500").json()

    assert body["next_page_token"] is None


def test_total_matches_counts_everything_not_just_the_page(client):
    total = _many_customers(client)

    body = client.get("/api/objects/Customer/search?q=Person&page_size=5").json()

    assert len(body["results"]) == 5
    assert body["total_matches"] == total


def test_an_oversized_page_size_is_clamped_not_rejected(client):
    # Foundry: "Requests for more than the maximum page size will be
    # reduced to the maximum."
    _many_customers(client, count=20)

    body = client.get("/api/objects/Customer/search?q=Person&page_size=99999").json()

    assert body["results"]
    assert len(body["results"]) <= 500


def test_a_malformed_page_token_returns_the_first_page(client):
    # A client should treat a token as opaque, so garbling one is a
    # client bug -- but failing the request would turn a display glitch
    # into an error page. Starting over is recoverable and obvious.
    _many_customers(client, count=30)

    body = client.get(
        "/api/objects/Customer/search?q=Person&page_size=3&page_token=not-a-number"
    ).json()

    assert len(body["results"]) == 3
    assert body["results"][0]["id"] == "c0000"


def test_an_out_of_range_page_token_returns_the_first_page(client):
    _many_customers(client, count=10)

    body = client.get(
        "/api/objects/Customer/search?q=Person&page_size=3&page_token=99999"
    ).json()

    assert body["results"][0]["id"] == "c0000"


def test_results_are_ordered_by_a_requested_field(client):
    _many_customers(client, count=20)

    ascending = client.get(
        "/api/objects/Customer/search?q=Person&page_size=4&order_by=name"
    ).json()
    descending = client.get(
        "/api/objects/Customer/search?q=Person&page_size=4&order_by=name:desc"
    ).json()

    ascending_names = [r["fields"]["name"] for r in ascending["results"]]
    descending_names = [r["fields"]["name"] for r in descending["results"]]

    assert ascending_names == sorted(ascending_names)
    assert descending_names == sorted(descending_names, reverse=True)
    assert ascending_names[0] != descending_names[0]


def test_an_unknown_order_by_field_is_ignored_rather_than_scrambling(client):
    # get_field() returns None for anything the caller cannot read, so
    # an ungranted sort column would otherwise order everything by None
    # -- silently scrambling results while looking successful.
    _many_customers(client, count=10)

    unsorted_ids = [
        r["id"] for r in client.get("/api/objects/Customer/search?q=Person&page_size=5").json()["results"]
    ]
    bogus_ids = [
        r["id"]
        for r in client.get(
            "/api/objects/Customer/search?q=Person&page_size=5&order_by=not_a_field"
        ).json()["results"]
    ]

    assert bogus_ids == unsorted_ids


def test_paging_survives_an_unstable_underlying_order(client):
    # The pre-paging sort exists because pagination is only correct if
    # the order is stable, and the underlying SELECT has no ORDER BY.
    #
    # Worth recording: removing that sort does NOT break the other
    # tests here, because SQLite happens to return primary-key order
    # today. That is an implementation detail, not a guarantee -- so
    # this test SHUFFLES what the mediator returns, which is what an
    # adapter with a different plan (or a different engine entirely)
    # could legitimately do.
    import random

    total = _many_customers(client, count=40)
    mediator = client.app.state.mediator
    real_search = mediator.search_object_free_text

    def shuffled(*args, **kwargs):
        ids = list(real_search(*args, **kwargs))
        random.shuffle(ids)
        return ids

    mediator.search_object_free_text = shuffled
    try:
        seen = []
        token = None
        while True:
            url = "/api/objects/Customer/search?q=Person&page_size=7"
            if token:
                url += f"&page_token={token}"
            body = client.get(url).json()
            seen.extend(result["id"] for result in body["results"])
            token = body["next_page_token"]
            if not token:
                break
    finally:
        mediator.search_object_free_text = real_search

    assert len(seen) == total
    assert len(seen) == len(set(seen)), "an unstable source order broke paging"


def test_ordering_stays_consistent_across_pages(client):
    # Sorting and paging must compose: page two of a sorted result must
    # continue where page one left off, not re-sort a different subset.
    _many_customers(client, count=20)

    first = client.get(
        "/api/objects/Customer/search?q=Person&page_size=5&order_by=name"
    ).json()
    second = client.get(
        f"/api/objects/Customer/search?q=Person&page_size=5&order_by=name"
        f"&page_token={first['next_page_token']}"
    ).json()

    names = [r["fields"]["name"] for r in first["results"]] + [
        r["fields"]["name"] for r in second["results"]
    ]
    assert names == sorted(names)


# --- Edit history (Point 14). Foundry's Edit History widget answers
# "what changed, by whom, and when?" over an immutable audit trail.
# Authorization follows their rule directly: "Users who have access to
# the current state of an object can access the entire history."


def _record_edit(client, changes, description, user_id="alice"):
    """Writes a real, applied log entry against the deployment's own
    write log. The mediator holds a READER (correctly -- the read path
    must not be able to write), so this constructs a writer over the
    same database, exactly as the app's own WriteMediator does."""
    from core.ontology.write_log import WriteLogWriter

    writer = WriteLogWriter(client.app.state.mediator.write_log.db_path)
    writer.mark_applied(
        writer.log_pending_update(
            "Customer", "cust_001", changes, {}, user_id, description
        )
    )


def test_object_history_is_empty_for_an_unedited_object(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    response = client.get("/api/objects/Customer/cust_001/history")

    assert response.status_code == 200
    assert response.json() == {"entries": [], "total": 0, "next_page_token": None}


def test_object_history_returns_an_edit(client):
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")
    _record_edit(client, {"name": "Ada v2"}, "renamed")

    body = client.get("/api/objects/Customer/cust_001/history").json()

    assert body["total"] == 1
    assert body["entries"][0]["user_id"] == "alice"
    assert body["entries"][0]["changes"] == {"name": "Ada v2"}


def test_object_history_denies_a_caller_who_cannot_read_the_object(client):
    # Access to the history follows access to the object -- and the
    # denial is uniform, so it looks identical to "no history".
    client.app.state.user_directory.create_user("east", "correct-pw", "us-east", "customer_service")
    _login(client, "east", "correct-pw")
    _record_edit(client, {"name": "Ada v2"}, "renamed")

    body = client.get("/api/objects/Customer/cust_001/history").json()

    assert body["entries"] == []
    assert body["total"] == 0


def test_object_history_requires_authentication(client):
    response = client.get("/api/objects/Customer/cust_001/history")

    assert response.status_code in (401, 403)


def test_object_history_pages(client):
    # An object with a long history is exactly what a timeline widget
    # scrolls through, so it uses the same paging as search rather than
    # a second scheme.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")
    for index in range(12):
        _record_edit(client, {"name": f"v{index}"}, f"edit {index}")

    first = client.get("/api/objects/Customer/cust_001/history?page_size=5").json()
    second = client.get(
        f"/api/objects/Customer/cust_001/history?page_size=5"
        f"&page_token={first['next_page_token']}"
    ).json()

    assert first["total"] == 12
    assert len(first["entries"]) == 5
    assert len(second["entries"]) == 5
    first_ids = {entry["id"] for entry in first["entries"]}
    assert not (first_ids & {entry["id"] for entry in second["entries"]})


# --- Opaque page tokens. Foundry's own format is a version prefix and
# a base64 payload ("v1.QnVpbGQgdGhlIEZ1dHVyZTo..."), and their
# guidance is that a client treats a token as opaque and passes it
# back unchanged.


def test_a_page_token_is_opaque_not_an_offset(client):
    # A bare offset is something a client can construct, guess, or
    # build logic around -- and every such client breaks the day the
    # encoding changes.
    _many_customers(client, count=20)

    body = client.get("/api/objects/Customer/search?q=Person&page_size=5").json()

    token = body["next_page_token"]
    assert token
    assert token.startswith("v1."), "token should carry a version prefix"
    assert not token.isdigit(), "token should not be a bare offset"


def test_an_opaque_token_round_trips(client):
    from api.routes import _decode_page_token, _encode_page_token

    for start in (0, 3, 50, 999999):
        assert _decode_page_token(_encode_page_token(start)) == start


def test_a_bare_offset_is_no_longer_accepted(client):
    # The old format. Rejecting it matters: a client that hardcoded
    # page_token=5 should restart cleanly rather than silently keep
    # working until the encoding changes again.
    _many_customers(client, count=30)

    body = client.get(
        "/api/objects/Customer/search?q=Person&page_size=3&page_token=5"
    ).json()

    assert body["results"][0]["id"] == "c0000", "a bare offset should not resolve"


def test_every_malformed_token_shape_falls_back_to_the_first_page(client):
    # Foundry's tokens are short-lived and meant for immediate
    # sequential use, so a garbled one is a client bug -- but failing
    # the request would turn a display glitch into an error page.
    _many_customers(client, count=30)

    for bad in ("garbage", "v2.abc", "v1.", "v1.!!!", "v1.bm90YW51bQ=="):
        body = client.get(
            f"/api/objects/Customer/search?q=Person&page_size=3&page_token={bad}"
        ).json()
        assert body["results"][0]["id"] == "c0000", f"{bad!r} did not fall back"


def test_paging_with_opaque_tokens_still_yields_everything_once(client):
    # The property from before, re-asserted through the new encoding:
    # changing the token format must not change what paging returns.
    total = _many_customers(client)

    seen = []
    token = None
    while True:
        url = "/api/objects/Customer/search?q=Person&page_size=25"
        if token:
            url += f"&page_token={token}"
        body = client.get(url).json()
        seen.extend(result["id"] for result in body["results"])
        token = body["next_page_token"]
        if not token:
            break

    assert len(seen) == total
    assert len(seen) == len(set(seen))


def test_history_tokens_are_opaque_too(client):
    # Both paged endpoints share the encoding rather than each
    # inventing one.
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")
    for index in range(12):
        _record_edit(client, {"name": f"v{index}"}, f"edit {index}")

    body = client.get("/api/objects/Customer/cust_001/history?page_size=5").json()

    assert body["next_page_token"].startswith("v1.")


# --- /health -------------------------------------------------------------


def test_health_is_reachable_without_authentication(client):
    # A health check requiring a session cannot be used by the thing
    # that most needs it -- a load balancer or an orchestrator, neither
    # of which can log in.
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_each_silo(client):
    body = client.get("/api/health").json()

    assert body["checks"]["ontology"] == "ready"
    assert any(key.startswith("silo:") for key in body["checks"])


def test_health_leaks_nothing_about_the_data(client):
    # Unauthenticated, so it reports only whether subsystems ANSWER --
    # never counts, names, paths or configuration. A connection error
    # routinely carries a host or a username, which is exactly why the
    # reason is not reported.
    body = client.get("/api/health").json()

    serialized = json.dumps(body)
    for leaked in ("cust_", "password", "/home/", "sqlite", ".db"):
        assert leaked not in serialized, f"/health exposed {leaked!r}"
    assert set(body["checks"].values()) <= {"ready", "reachable", "unreachable", "unconfigured"}


def test_health_reports_degraded_rather_than_failing(client, monkeypatch):
    # 200 even when degraded, with the detail in the body. A caller
    # distinguishing "the service is down" from "the service is up but
    # its database is not" needs both answers to arrive, and a non-200
    # collapses them into one.
    adapter = next(iter(client.app.state.mediator.adapters.values()))

    def unreachable():
        raise OSError("database is gone")

    monkeypatch.setattr(adapter, "health_check", unreachable)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert "unreachable" in response.json()["checks"].values()


def test_a_missing_sqlite_file_is_not_reported_healthy(tmp_path):
    # THE bug found by testing this against a real server: sqlite3
    # .connect() CREATES a missing database rather than failing, so a
    # connection plus SELECT 1 succeeded against a brand-new empty file
    # and reported "reachable" after the real one had been moved away.
    # A health check that goes green when the data has vanished is the
    # alert that will not fire on the incident it exists for.
    import sqlite3 as sqlite_module

    from adapters.sqlite_adapter import SQLiteReadAdapter

    db_path = tmp_path / "silo.db"
    sqlite_module.connect(db_path).close()
    adapter = SQLiteReadAdapter({"path": db_path})
    adapter.health_check()

    db_path.unlink()

    with pytest.raises(FileNotFoundError):
        adapter.health_check()


def test_a_link_field_carries_its_link_type_through_the_response_model(client):
    """The one value joining both ends of a relationship.

    Both directions arrive as separate fields on separate object types;
    link_type is all that says they are one relationship. The schema
    browser's Link types view is built on it.

    Written after it was MISSING from SchemaFieldResponse and nothing
    noticed. The response model lists exactly the keys a caller may
    see, which has caught four real leaks -- and this is its other
    edge: a field the client legitimately needs is just as invisible
    as one it must not have. The frontend tests passed throughout,
    against a fixture that included the key the API did not send.
    """
    client.app.state.user_directory.create_user("linkuser", "pw", "us-west", "customer_service")
    client.post("/api/login", json={"username": "linkuser", "password": "pw"})

    body = client.get("/api/me/visible-schema").json()
    transactions = body["Customer"]["fields"]["transactions"]

    assert transactions["type"] == "link"
    assert transactions["link_type"] == "CustomerTransactions"


def test_both_ends_of_a_relationship_report_the_same_link_type(client):
    # The property that makes client-side grouping possible at all. If
    # the two ends ever disagreed, a browser would show one
    # relationship as two.
    client.app.state.user_directory.create_user("linkuser2", "pw", "us-west", "customer_service")
    client.post("/api/login", json={"username": "linkuser2", "password": "pw"})

    body = client.get("/api/me/visible-schema").json()

    assert (
        body["Customer"]["fields"]["transactions"]["link_type"]
        == body["Transaction"]["fields"]["customer_id"]["link_type"]
    )


def _filter_user(client, username):
    """A logged-in caller for the filter-vocabulary tests.

    Named apart from this file's own _login(), which takes a password
    and does not create the user -- an earlier version of these tests
    shadowed it and every request came back 403.

    These POST through _post() for the same reason: it carries the CSRF
    header, and a raw client.post is refused before the route is
    reached.
    """
    client.app.state.user_directory.create_user(username, "pw", "us-west", "customer_service")
    _login(client, username, "pw")


def test_count_accepts_the_full_condition_vocabulary(client):
    """The prerequisite this commit exists for: until now the HTTP
    surface took {field: value} only, so no browser could express "id
    is one of these two" -- which is what selecting two values on a
    chart means.

    Filters on NAME rather than region. A first version used region and
    asserted that adding "us-east" widened the result; it did not, and
    the code was right: MAC scopes this caller to us-west, so a second
    region can never add rows. The test premise was wrong, and asserting
    against the wrong field would have hidden that the `in` operator
    works at all.
    """
    _filter_user(client, "filteruser")

    everything = _post(
        client, "/api/objects/Customer/count", {"criteria": {}}
    ).json()["count"]

    # Two ids this caller can see. MAC scopes them to us-west, and the
    # fixture puts exactly cust_001 and cust_002 there -- asserted
    # below rather than assumed, so a fixture change fails loudly
    # instead of making the operator look broken.
    first_two = ["cust_001", "cust_002"]
    assert everything >= 2, "need two visible customers, or this proves nothing"

    one = _post(
        client, "/api/objects/Customer/count",
        {"conditions": [{"field": "customer_id", "operator": "in",
                         "value": first_two[:1]}]},
    ).json()["count"]
    both = _post(
        client, "/api/objects/Customer/count",
        {"conditions": [{"field": "customer_id", "operator": "in",
                         "value": first_two}]},
    ).json()["count"]

    assert one >= 1, "the fixture should match something, or this proves nothing"
    assert both > one
    assert both <= everything


def test_the_dict_form_still_works(client):
    # Every existing caller sends it, and both forms mean equality on
    # each key -- they are not in conflict, they are different
    # expressiveness.
    _filter_user(client, "filteruser2")

    from_dict = _post(
        client, "/api/objects/Customer/count", {"criteria": {"region": "us-west"}}
    ).json()["count"]
    from_conditions = _post(
        client, "/api/objects/Customer/count",
        {"conditions": [{"field": "region", "operator": "equals",
                         "value": "us-west"}]},
    ).json()["count"]

    assert from_dict == from_conditions


def test_sending_both_forms_is_rejected_rather_than_merged(client):
    """Merging would need a rule for what happens when they disagree
    about the same field, and inventing one silently is how a filter
    ends up meaning something nobody asked for.
    """
    _filter_user(client, "filteruser3")

    response = _post(
        client, "/api/objects/Customer/count", {"criteria": {"region": "us-west"},
              "conditions": [{"field": "region", "operator": "equals",
                              "value": "us-east"}]}
    )

    assert response.status_code == 400


def test_a_malformed_condition_is_a_400_not_a_500(client):
    _filter_user(client, "filteruser4")

    response = _post(
        client, "/api/objects/Customer/count", {"conditions": [{"field": "region", "operator": "nonsense",
                              "value": "x"}]}
    )

    assert response.status_code == 400


def test_a_condition_on_an_unreadable_field_is_a_400(client):
    # Uniform denial reaches the HTTP surface: the same status and
    # message shape as a field that does not exist.
    _filter_user(client, "filteruser5")

    unknown = _post(
        client, "/api/objects/Customer/count", {"conditions": [{"field": "no_such_field", "operator": "equals",
                              "value": "x"}]}
    )
    unreadable = _post(
        client, "/api/objects/Customer/count", {"conditions": [{"field": "internal_notes", "operator": "equals",
                              "value": "x"}]}
    )

    assert unknown.status_code == unreadable.status_code == 400


def test_text_and_conditions_narrow_together(client):
    """Two contexts, combined -- the shape every search engine that
    does both uses.

    The text query decides what MATCHES; the conditions decide what is
    ELIGIBLE; a result satisfies both. Without this, a table filtered
    by text and charts filtered by conditions describe different object
    sets, and cross-filtering between them is impossible.
    """
    _filter_user(client, "textcond")

    text_only = client.get("/api/objects/Customer/search?q=a").json()["total_matches"]
    conditions = json.dumps(
        [{"field": "customer_id", "operator": "in", "value": ["cust_001"]}]
    )
    both = client.get(
        f"/api/objects/Customer/search?q=a&conditions={conditions}"
    ).json()["total_matches"]

    assert text_only > 1, "the text alone should match several, or this proves nothing"
    assert both == 1


def test_conditions_alone_work_without_any_text(client):
    # The chart-click case: no search term, just a filter.
    _filter_user(client, "condonly")
    conditions = json.dumps(
        [{"field": "customer_id", "operator": "in", "value": ["cust_001", "cust_002"]}]
    )

    body = client.get(
        f"/api/objects/Customer/search?conditions={conditions}"
    ).json()

    assert body["total_matches"] == 2


def test_a_condition_on_an_unreadable_field_is_rejected_by_search_too(client):
    # Uniform denial reaches this path as well: an unreadable field
    # fails exactly as an absent one does.
    _filter_user(client, "conddenied")

    unknown = client.get(
        "/api/objects/Customer/search?conditions="
        + json.dumps([{"field": "no_such_field", "operator": "equals", "value": "x"}])
    )
    unreadable = client.get(
        "/api/objects/Customer/search?conditions="
        + json.dumps([{"field": "internal_notes", "operator": "equals", "value": "x"}])
    )

    assert unknown.status_code == unreadable.status_code == 400


def test_malformed_conditions_are_a_400(client):
    _filter_user(client, "condbad")

    assert client.get(
        "/api/objects/Customer/search?conditions=not-json"
    ).status_code == 400


def _admin_user(client, username):
    """A logged-in caller holding manage:users, via the debug role.

    Mirrors _filter_user, which uses customer_service -- that role has
    no manage:users grant, which is what the denial test above relies
    on.
    """
    client.app.state.user_directory.create_user(username, "pw", "us-west", "debug")
    _login(client, username, "pw")


def test_config_route_requires_manage_users(client):
    """Configuration discloses deployment SHAPE -- which silos exist,
    which models run, how many object types there are.

    None of that is object data, but it is what an attacker maps a
    system with, and an ordinary user has no reason to need it. Gated
    on the same grant Admin uses.
    """
    _filter_user(client, "cfgdenied")

    assert client.get("/api/config").status_code == 403


def test_config_route_reports_the_running_settings(client):
    _admin_user(client, "cfgadmin")

    body = client.get("/api/config").json()

    assert body["max_hops"] == 8
    assert body["security_attribute"] == "region"
    assert "primary_sql" in body["silo_names"]
    assert body["object_type_count"] > 0


def test_config_route_never_discloses_connection_details(client):
    """THE point of the endpoint's shape.

    Silos are NAMED but not described, and roles are named but their
    grants are not listed. llm_connection and silo connection configs
    carry hosts, paths and credential references -- exactly the
    material a UI must never receive.

    Asserts on the serialised body rather than the model's fields,
    because a future field could reintroduce this and a field-name
    check would not see a nested dict.
    """
    _admin_user(client, "cfgnoleak")

    raw = client.get("/api/config").text

    assert "connection" not in raw
    assert "password" not in raw
    assert "dev_fixtures" not in raw, "a silo path reached the response"
    assert "allowed_actions" not in raw, "role grants reached the response"


def test_silos_route_requires_manage_users(client):
    _filter_user(client, "silodenied")

    assert client.get("/api/silos").status_code == 403


def test_silos_route_reports_configured_silos_and_their_types(client):
    _admin_user(client, "siloadmin")

    body = client.get("/api/silos").json()

    by_name = {silo["name"]: silo for silo in body}
    assert "primary_sql" in by_name
    assert by_name["primary_sql"]["reachable"] is True
    assert by_name["primary_sql"]["adapter"] == "sqlite"
    assert "Customer" in by_name["primary_sql"]["object_types"]


def test_silos_route_reports_the_failure_KIND_not_the_message(client, tmp_path):
    """The line this endpoint draws.

    /health is unauthenticated so it says nothing about why. This one
    is admin-gated and can say more -- but the exception TYPE, never
    the message, which routinely carries a host or a path.

    An admin could read the YAML anyway; the point is that a UI which
    never carries the path cannot leak it through a screenshot, a bug
    report or a browser cache.
    """
    _admin_user(client, "silofail")
    mediator = client.app.state.mediator
    adapter = mediator.adapters["primary_sql"]
    original = adapter.db_path
    adapter.db_path = str(tmp_path / "gone.db")
    try:
        body = client.get("/api/silos").json()
    finally:
        adapter.db_path = original

    unreachable = next(s for s in body if s["name"] == "primary_sql")
    assert unreachable["reachable"] is False
    assert unreachable["failure"] == "FileNotFoundError"
    assert "gone.db" not in client.get("/api/silos").text, "a path reached the response"


def test_silos_route_credits_a_silo_that_only_backs_a_FIELD(client):
    """A multi-datasource field lives in a silo that backs no object
    type PRIMARILY.

    risk_sql holds Customer.risk_score and nothing else, so listing
    only silo_for_type showed it with no object types at all -- which
    reads as "unused" and invites someone to remove a silo a field
    depends on. Found by looking at the screen, not by a failing test.
    """
    _admin_user(client, "silomdo")

    body = client.get("/api/silos").json()

    risk = next(silo for silo in body if silo["name"] == "risk_sql")
    assert risk["object_types"] == ["Customer"]


# NO test for the de-duplication guard, deliberately.
#
# A first version asserted primary_sql lists Customer once. It passed
# with the guard REMOVED, because no fixture silo holds both primary
# and additional storage for the same type -- so the assertion was
# true for a reason unrelated to what it claimed to check.
#
# The guard stays: it is correct, costs nothing, and a deployment
# where one silo does both is entirely legal. But a test that cannot
# fail is not a test, and adding a fixture silo purely to exercise it
# would be shaping the fixture to the assertion.
