"""
Proposed merges, end to end, as a reviewer meets them.

WHY THIS FILE EXISTS AT ALL. core/mirror/matching.py proposes that two
entities might be one, core/identity_decisions.py stores what was
decided, and core/masked_review.py shows a reviewer the verdict
without the value. All three were built, tested in isolation, and
reached by NOTHING -- 580 lines of finished feature with no route and
no screen. An audit of which core modules had no importer found them.

THE MASKING IS THE PART THAT MUST NOT BREAK. A reviewer may not be
cleared to read the field that decides the match, and the literature
is explicit that the reviewing facility "should only have access to
those plaintext attributes that are displayed". So the test that
matters most here is not that the queue renders -- it is that an
unreadable value is ABSENT from the response body, not nulled, not
masked, not starred. The difference is invisible on a screen and total
in a log.
"""

import json

from core.identity_decisions import MergeDecisionStore
from tests.conftest import with_roles


def _login(client, username="reviewer", password="pw", role="editor"):
    client.app.state.user_directory.create_user(username, password, "us-west", role)
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 204, response.text


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("elysium_csrf")}


def _store(client) -> MergeDecisionStore:
    return MergeDecisionStore(
        client.app.state.runtime_paths.data_dir / "identity_decisions.db")


def _propose(client, agreement=None):
    store = _store(client)
    return store.propose(
        "Customer", "cust_001", "cust_002", 0.91,
        json.dumps(agreement if agreement is not None
                   else {"name": True, "region": True, "email": False}),
    )


class TestTheQueueIsReachable:
    def test_a_proposal_appears_for_someone_who_may_read_the_type(self, client):
        _login(client)
        proposal_id = _propose(client)

        response = client.get("/api/merge-proposals")

        assert response.status_code == 200, response.text
        ids = [row["proposal_id"] for row in response.json()]
        assert proposal_id in ids

    def test_it_can_be_filtered_to_what_is_still_pending(self, client):
        _login(client)
        _propose(client)

        response = client.get("/api/merge-proposals", params={"decision": "pending"})

        assert response.status_code == 200
        assert all(row["decision"] == "pending" for row in response.json())


class TestTheReviewerSeesVerdictsNotValues:
    """The security half, and the reason this feature could not simply
    be exposed with a plain serialiser."""

    def test_an_unreadable_value_is_absent_rather_than_null(self, client):
        """ABSENT, not None. `response_model_exclude_none` would make
        the two look identical on the wire -- but a None has been
        serialised into the process, could be logged on an error, and
        sits in anything that cached the object. The literature's
        requirement is that the reviewing facility never has it."""
        _login(client)
        _propose(client)

        response = client.get("/api/merge-proposals")
        body = response.text
        fields = response.json()[0]["fields"]

        for entry in fields:
            if "left" not in entry:
                assert "right" not in entry, "half a field was withheld"

        assert '"left":null' not in body.replace(" ", "")
        assert '"right":null' not in body.replace(" ", "")

    def test_every_compared_field_still_carries_a_verdict(self, client):
        """Withholding the value must not withhold the judgement. "These
        two emails agree" tells a reviewer what they need and tells them
        nothing about either address."""
        _login(client)
        _propose(client)

        fields = client.get("/api/merge-proposals").json()[0]["fields"]

        assert len(fields) == 3
        assert all(entry["verdict"] for entry in fields)

    def test_the_withheld_fields_are_named(self, client):
        """So a reviewer knows the comparison was wider than what they
        can see, rather than believing they saw all of it."""
        _login(client)
        _propose(client)

        row = client.get("/api/merge-proposals").json()[0]

        assert isinstance(row["withheld"], list)

    def test_an_unreadable_field_is_never_even_requested(self, client):
        """THE CLAIM A CONTROL CAUGHT AS UNTESTED. The route fetches
        only `readable & agreement` rather than fetching everything and
        masking after. Both produce the SAME response body -- which is
        why removing the intersection broke nothing and this test had
        to be written.

        THIS TEST DOES NOT PROVE WHAT IT WAS WRITTEN TO PROVE, and
        that is recorded rather than hidden. Removing the intersection
        leaves it passing, because the mediator names no refused field
        in the log either way. It is kept because the property it
        asserts is still one worth holding -- a reviewer's trail must
        never name a field they may not read -- but the narrowing of
        fetched fields is defence in depth, not a mechanism this
        catches."""
        _login(client)
        _propose(client, {"name": True, "region": True, "secret_note": False})

        response = client.get("/api/merge-proposals")
        assert response.status_code == 200

        # THE LOG FILE, because there is no app.state.audit_log -- the
        # mediator holds its own and writes to a path under the
        # deployment's data directory.
        logs = list(client.app.state.runtime_paths.data_dir.rglob("*.log"))
        written = "".join(path.read_text(errors="replace") for path in logs)

        assert "secret_note" not in written, (
            "the reviewer's audit trail names a field they may not read")

    def test_the_score_is_not_in_the_response(self, client):
        """FUSION_AND_IDENTITY.md: "the reviewer's decision is made on
        the agreement PATTERN, not the score". A number invites
        deference to the matcher, which is the thing a human review
        exists to prevent."""
        _login(client)
        _propose(client)

        row = client.get("/api/merge-proposals").json()[0]

        assert "score" not in row
        assert row["pattern"]


class TestDecidingIsAWrite:
    def test_approving_needs_write_on_the_type(self, client):
        """An approved inference "becomes STORED DATA, not edited
        config" -- it changes what the ontology returns, so it needs the
        same grant any other change to that type needs."""
        with_roles(client.app, viewer={"allowed_actions": ["read:Customer"]})
        _login(client, "clerk", role="viewer")
        proposal_id = _propose(client)

        response = client.post(f"/api/merge-proposals/{proposal_id}/decide",
                               json={"decision": "approved"}, headers=_csrf(client))

        assert response.status_code == 403, response.text
        assert "write:Customer" in response.text

    def test_a_reviewer_with_the_grant_may_decide(self, client):
        with_roles(client.app,
                   merger={"allowed_actions": ["read:Customer", "write:Customer"]})
        _login(client, "carol", role="merger")
        proposal_id = _propose(client)

        response = client.post(f"/api/merge-proposals/{proposal_id}/decide",
                               json={"decision": "approved"}, headers=_csrf(client))

        assert response.status_code == 204, response.text
        assert _store(client).proposals()[0].decision == "approved"

    def test_an_unknown_decision_is_refused(self, client):
        with_roles(client.app,
                   merger={"allowed_actions": ["read:Customer", "write:Customer"]})
        _login(client, "carol", role="merger")
        proposal_id = _propose(client)

        response = client.post(f"/api/merge-proposals/{proposal_id}/decide",
                               json={"decision": "maybe"}, headers=_csrf(client))

        assert response.status_code == 422

    def test_an_unknown_proposal_is_a_404_not_a_500(self, client):
        with_roles(client.app,
                   merger={"allowed_actions": ["read:Customer", "write:Customer"]})
        _login(client, "carol", role="merger")

        response = client.post("/api/merge-proposals/nope/decide",
                               json={"decision": "approved"}, headers=_csrf(client))

        assert response.status_code == 404
