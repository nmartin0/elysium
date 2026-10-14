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
        nothing about either address.

        THIS ASSERTED TRUTHINESS AND THAT IS WHY IT SAW NOTHING. Every
        field carried the verdict "one side missing" for months --
        truthy, uniform, and a fabricated claim about the data. A
        verdict test has to name the verdicts.
        """
        _login(client)
        _propose(client)

        fields = client.get("/api/merge-proposals").json()[0]["fields"]

        assert len(fields) == 3
        assert {entry["field"]: entry["verdict"] for entry in fields} == {
            "name": "agree", "region": "agree", "email": "differ",
        }

    def test_THE_VERDICT_IS_THE_ONE_THE_MATCHER_RECORDED(self, client):
        """THE BUG THIS FILE COULD NOT SEE.

        `_readable_fields` looked up `visible_schema()["object_types"]`,
        a key that function has never produced, so it returned the empty
        set for every caller. Its one consumer fetches
        `readable & agreement` fields, both rows came back `{}`, and
        `masked_review._verdict` tests presence BEFORE agreement -- so
        every field of every proposal read "one side missing" while the
        real verdict sat unread in `agreement`.

        A REVIEWER IS THE WORST AUDIENCE FOR A FABRICATED FACT. They
        are being asked whether two records are the same person, and
        "one side is missing this field" is evidence that points one
        way.

        ASSERTED FROM THE OTHER DIRECTION TOO -- not merely that the
        verdicts are right, but that this specific wrong answer is
        absent -- because the bug produced a uniform, plausible-looking
        result that a positive assertion alone could coexist with if
        only some fields were affected.
        """
        _login(client)
        _propose(client, {"name": True, "region": False, "email": True})

        row = client.get("/api/merge-proposals").json()[0]

        assert row["pattern"] == "name: agree, region: differ, email: agree"
        assert "one side missing" not in row["pattern"]

    def test_a_field_the_reviewer_CAN_read_carries_its_values(self, client):
        """The other half of the same bug. `wanted` was empty, so the
        route fetched nothing and every field looked withheld -- which
        made the masking appear to be working perfectly while it was
        doing nothing at all."""
        _login(client)
        _propose(client)

        fields = {entry["field"]: entry for entry in
                  client.get("/api/merge-proposals").json()[0]["fields"]}

        assert fields["name"]["left"] == "Ada Okafor"
        assert fields["name"]["right"] == "Bram Feldman"

    def test_and_NOTHING_is_withheld_when_everything_is_readable(self, client):
        """`withheld` named every field, every time, which is the
        reading that made the defect look like correct behaviour: a
        reviewer told "you judged this without seeing any of it" has no
        reason to doubt the screen."""
        _login(client)
        _propose(client)

        assert client.get("/api/merge-proposals").json()[0]["withheld"] == []

    def test_A_FIELD_THE_REVIEWER_MAY_NOT_READ_IS_STILL_WITHHELD(self, client):
        """THE SECURITY HALF, AND IT WAS PASSING VACUOUSLY.

        Every masking test in this class ran as `editor`, who can read
        name, region and email -- so with `_readable_fields` broken,
        every field came back withheld and every assertion about
        withholding held for the wrong reason. The masking was never
        exercised at all; what was being tested was a bug that looked
        like it.

        SO THIS USES THE MIDDLE RUNG OF THE GRANT LADDER.
        `customer_service_sees_email_exists` holds
        `discover:Customer.email` and NOT `read:` -- the field IS in
        their visible schema, marked `readable: false`, which is the
        only shape that distinguishes "withheld" from "does not
        exist". A role that could not discover it either would prove
        the wrong thing: email would never be a candidate.
        """
        _login(client, "masked", role="customer_service_sees_email_exists")
        _propose(client)

        row = client.get("/api/merge-proposals").json()[0]
        fields = {entry["field"]: entry for entry in row["fields"]}

        # THE VERDICT SURVIVES THE MASKING, which is the whole design:
        # "these two emails differ" is safe and the addresses are not.
        assert fields["email"]["verdict"] == "differ"
        assert "left" not in fields["email"] and "right" not in fields["email"]
        assert row["withheld"] == ["email"]
        # AND THE READABLE ONES ARE NOT SWEPT UP WITH IT.
        assert fields["name"]["left"] == "Ada Okafor"

    def test_and_the_masked_value_is_nowhere_in_the_body(self, client):
        """ABSENT, not omitted from one view of it. The literature's
        requirement is that the reviewing facility never holds the
        plaintext, so the assertion is against the raw response text
        rather than against the parsed structure."""
        _login(client, "masked2", role="customer_service_sees_email_exists")
        _propose(client)

        body = client.get("/api/merge-proposals").text

        assert "ada.okafor@example.com" not in body
        assert "bram.feldman@example.com" not in body

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


class TestHighConfidence:
    def test_every_proposal_says_whether_it_is_preselected(self, client):
        """WIRED-3: a flag the screen ticks for bulk approval. The
        fixture's Customer declares no inference, so it is False."""
        _login(client)
        _propose(client)

        (proposal,) = client.get("/api/merge-proposals").json()
        assert proposal["high_confidence"] is False
        assert "score" not in proposal


class TestDecidingIsAWrite:
    def test_approving_needs_write_on_the_type(self, client):
        """An approved inference "becomes STORED DATA, not edited
        config" -- it changes what the ontology returns, so it needs the
        same grant any other change to that type needs."""
        # A SHIPPED ROLE that reads Customer and may not change it. Not a
        # with_roles() one: the mediator keeps the roles it was built
        # with, and since R61 a reviewer must be able to READ both
        # records -- through the mediator -- before write is asked.
        _login(client, "clerk", role="customer_service")
        proposal_id = _propose(client)

        response = client.post(f"/api/merge-proposals/{proposal_id}/decide",
                               json={"decision": "approved"}, headers=_csrf(client))

        assert response.status_code == 403, response.text
        assert "write:Customer" in response.text

    def test_a_reviewer_with_the_grant_may_decide(self, client):
        # editor reads Customer through the mediator; write is added
        # where the route asks for it.
        with_roles(client.app, editor={"allowed_actions": [
            *client.app.state.generation.config.roles["editor"]["allowed_actions"],
            "write:Customer"]})
        _login(client, "carol", role="editor")
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


class TestAProposalAsTheMatcherWritesIt:
    """R61, found 14 Oct by a checklist sweep. The matcher names rows
    `<source>:<id>` -- `primary:cust_001` -- and every test above stored
    bare ids, so none of them saw what production stores."""

    def _propose_qualified(self, client, left, right, agreement=None):
        return _store(client).propose(
            "Customer", left, right, 0.91,
            json.dumps(agreement or {"name": True, "region": True}))

    def test_the_values_of_a_readable_pair_are_shown(self, client):
        """Before: every readable field read "one side missing", because
        `primary:cust_001` was read as if it were an entity id."""
        _login(client)
        self._propose_qualified(client, "primary:cust_001", "primary:cust_002")

        (row,) = client.get("/api/merge-proposals").json()
        name = next(entry for entry in row["fields"] if entry["field"] == "name")

        assert (name["left"], name["right"]) == ("Ada Okafor", "Bram Feldman")
        assert name["verdict"] == "agree"

    def test_a_pair_with_a_side_this_reviewer_cannot_see_is_not_shown(self, client):
        """cust_003 is us-east; the reviewer is us-west. Before, the
        proposal was listed -- its id, and whether its fields agreed with
        a record the reviewer CAN see."""
        _login(client)
        self._propose_qualified(client, "primary:cust_001", "primary:cust_003")

        assert client.get("/api/merge-proposals").json() == []

    def test_nor_may_they_decide_it(self, client):
        _login(client)
        proposal_id = self._propose_qualified(client, "primary:cust_001", "primary:cust_003")
        with_roles(client.app, editor={"allowed_actions": [
            "read:Customer", "read:Customer.name", "write:Customer"]})

        response = client.post(f"/api/merge-proposals/{proposal_id}/decide",
                               json={"decision": "approved"}, headers=_csrf(client))

        assert response.status_code == 404


class TestWhatProducedIt:
    """R62: the proposal says which matcher and settings produced it."""

    def test_the_provenance_recorded_is_returned(self, client):
        _login(client)
        _store(client).propose("Customer", "cust_001", "cust_002", 0.91, "{}",
                               provenance=json.dumps({"matcher": "splink", "version": "4.0.17"}))

        (row,) = client.get("/api/merge-proposals").json()

        assert row["provenance"] == {"matcher": "splink", "version": "4.0.17"}

    def test_a_proposal_from_before_it_was_recorded_has_none(self, client):
        _login(client)
        _propose(client)

        (row,) = client.get("/api/merge-proposals").json()

        assert "provenance" not in row
