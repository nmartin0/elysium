"""An expired session is refused at the HTTP boundary (001's F-33).

WHAT THE AUDIT FOUND, AND WHAT MEASURING IT CONFIRMED. F-33 reported
that two critical auth controls were each defended by exactly ONE
test. The ownership half was since resolved by the approvals work --
may_claim is caught by eight tests at two layers. Session expiry was
not, and a mutation run over BOTH tiers proved it:

    disable the expiry check entirely
      -> tests/unit/test_session_store.py::test_expired_session_
         returns_none      1 failed
      -> 2,845 other unit tests                    passed
      -> 442 integration tests                     passed

So a change that made every expired session valid forever broke ONE
assertion in the whole repository, and the tier that goes over real
HTTP -- through get_current_user, which is what actually decides
whether a request proceeds -- noticed nothing at all.

ONE TEST IS ONE ACCIDENT AWAY FROM NO TEST. A rename, a skip, a
fixture change, and the control is gone with nothing to say so. That
is the whole of F-33's argument and it is a good one.

WHY THIS TEST IS AT A DIFFERENT LAYER RATHER THAN BESIDE THE FIRST.
A second unit test on SessionStore would double the count and change
nothing structural: both would die to the same refactor of the same
method. The gap the mutation actually exposed is that nothing checks
the WIRE -- that validate_session()'s None reaches the caller as a
401. AGENTS.md records that exact shape: the component is right, the
wire is not, and the suite is green.

THE SESSION IS EXPIRED IN THE DATABASE, not by patching
SESSION_LIFETIME. The unit test already patches the constant, so
patching it here would re-test the same thing through a longer route.
Ageing the row exercises the real comparison against a real stored
value -- which is what a session left open overnight actually is.
"""

import sqlite3
from datetime import UTC, datetime, timedelta

from tests.integration.test_api import _login

PW = "a-long-and-unremarkable-passphrase"


def _age_every_session(client, when: datetime) -> int:
    """Rewrites expires_at directly. Returns the rows changed, because
    a test that expired nothing would pass for the wrong reason."""
    db = client.app.state.session_store._db_path
    with sqlite3.connect(db) as conn:
        cursor = conn.execute("UPDATE sessions SET expires_at = ?", (when.isoformat(),))
        conn.commit()
        return cursor.rowcount


def test_a_session_that_has_expired_is_refused(client):
    client.app.state.user_directory.create_user("eve", PW, "us-west", "debug")
    _login(client, "eve", PW)

    # THE POSITIVE CASE FIRST, so a 401 below cannot be explained by
    # the login having failed or the cookie never being set.
    assert client.get("/api/me").status_code == 200

    aged = _age_every_session(client, datetime.now(UTC) - timedelta(minutes=1))
    assert aged == 1, "no session row was expired; the test would prove nothing"

    assert client.get("/api/me").status_code == 401


def test_the_refusal_is_the_same_uniform_401_as_no_session_at_all(client):
    """EXPIRED AND ABSENT MUST BE INDISTINGUISHABLE. session_store's
    own docstring says both return None on the same uniform-denial
    principle; this is that principle held at the boundary, where a
    caller could otherwise learn that their token was real but old."""
    client.app.state.user_directory.create_user("frank", PW, "us-west", "debug")
    _login(client, "frank", PW)
    _age_every_session(client, datetime.now(UTC) - timedelta(minutes=1))

    expired = client.get("/api/me")

    client.cookies.clear()
    absent = client.get("/api/me")

    assert expired.status_code == absent.status_code == 401
    assert expired.json() == absent.json()


def test_a_live_session_still_works(client):
    """THE OPPOSITE DIRECTION. Without this, a change that refused
    every session -- expired or not -- would satisfy both tests above
    while breaking the product entirely."""
    client.app.state.user_directory.create_user("grace", PW, "us-west", "debug")
    _login(client, "grace", PW)

    _age_every_session(client, datetime.now(UTC) + timedelta(hours=1))

    assert client.get("/api/me").status_code == 200
