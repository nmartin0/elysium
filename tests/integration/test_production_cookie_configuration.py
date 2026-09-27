"""The PRODUCTION cookie configuration works end to end.

THE BLIND SPOT THIS CLOSES. `tests/integration/conftest.py` sets
`ELYSIUM_COOKIE_SECURE=false` for every test, and for a good reason it
states: httpx's cookie jar stores a Secure cookie but never transmits
it over a non-HTTPS connection, and `TestClient`'s default base URL is
`http://testserver`. So no test anywhere ran the configuration a real
deployment actually uses.

WHAT THAT COST, MEASURED. While preparing SEC-17 -- the `__Host-`
cookie prefix -- I applied half of it: the session cookie's NAME became
conditional while `api/routes.py` still read the old constant. In
production that means logout stops invalidating the session
server-side. The suite reported **208 passed**, because it only ever
exercised the unprefixed, non-secure path. A green suite and a broken
logout is the shape this project keeps finding, and the reason SEC-17
is filed as one atomic change rather than committed in halves.

THE FIX IS THE BASE URL, not the flag. `TestClient` takes one, so an
`https://` client sends a Secure cookie exactly as a browser would.
Nothing about the ASGI app changes; only the scheme httpx believes it
is talking over.

WHY LOGOUT IS THE ASSERTION THAT MATTERS. Login and an authenticated
read would pass even with a mismatched cookie name, because the name
is only read in two places and `get_current_user` is not one of the
ones that would be missed. Logout's SERVER-SIDE invalidation is what
breaks, and the only way to see it is to reuse the token afterwards
and find it still works.
"""

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_api import _csrf_headers, _login

PASSWORD = "a-long-and-unremarkable-passphrase"


@pytest.fixture
def secure_client(client, monkeypatch):
    """The same app, spoken to as a browser over HTTPS would.

    Reuses the ordinary `client` fixture for all of its deployment
    setup and then re-points at it: the env var goes back to its
    PRODUCTION default, and the base URL becomes https so httpx will
    transmit the Secure cookie it would otherwise only store.
    """
    monkeypatch.delenv("ELYSIUM_COOKIE_SECURE", raising=False)
    with TestClient(client.app, base_url="https://testserver") as secure:
        yield secure


def test_the_secure_cookie_is_actually_sent_back(secure_client):
    """The premise of every test below. If httpx refused to transmit
    it, the rest would fail for a reason that has nothing to do with
    what they check."""
    secure_client.app.state.user_directory.create_user(
        "alice", PASSWORD, "us-west", "debug")
    _login(secure_client, "alice", PASSWORD)

    assert secure_client.get("/api/me").status_code == 200


def test_the_session_cookie_is_flagged_for_production(secure_client):
    secure_client.app.state.user_directory.create_user(
        "bob", PASSWORD, "us-west", "debug")

    response = secure_client.post(
        "/api/login", json={"username": "bob", "password": PASSWORD})

    session = [h for h in response.headers.get_list("set-cookie") if "session" in h]
    assert session, "no session cookie was set"
    assert "Secure" in session[0]
    assert "HttpOnly" in session[0]
    assert "SameSite=strict" in session[0].lower().replace("samesite=strict", "SameSite=strict")


def test_logout_invalidates_the_session_SERVER_SIDE(secure_client):
    """THE ONE THAT CATCHES A HALF-LANDED SEC-17.

    If the name written by `set_session_cookie` stops matching the name
    `api/routes.py` reads at logout, `invalidate_session` is never
    called. The cookies are still cleared, so the browser looks logged
    out and every other test still passes -- but the token remains
    valid, and anyone holding it keeps the session.

    So this keeps the token, logs out, puts it back, and checks it is
    dead.
    """
    secure_client.app.state.user_directory.create_user(
        "carol", PASSWORD, "us-west", "debug")
    _login(secure_client, "carol", PASSWORD)
    cookies = dict(secure_client.cookies)
    assert secure_client.get("/api/me").status_code == 200

    secure_client.post("/api/logout", headers=_csrf_headers(secure_client))

    # Put the old cookies back, exactly as a stolen token would be.
    for name, value in cookies.items():
        secure_client.cookies.set(name, value)

    assert secure_client.get("/api/me").status_code == 401, (
        "the session survived logout -- invalidate_session was not called, which "
        "is what a mismatched cookie name looks like from outside"
    )
