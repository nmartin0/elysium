"""
The approvals inbox, end to end, as a reviewer meets it.

WHY A SEPARATE FILE. The pieces are tested apart -- the store's
reservation, the route's filtering, the panel's rendering -- and each
passed while the whole was broken. A refused approval destroyed the
proposal; the inbox was cacheable; a missing table returned a 500.
Every one of those was found by USING the product, not by a unit test.

These exercise the sequences a person actually performs, through the
real HTTP surface, with nothing stubbed.
"""


from tests.conftest import with_roles


def _login(client, username, password="pw", role="editor"):
    client.app.state.user_directory.create_user(username, password, "us-west", role)
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 204, response.text


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("elysium_csrf")}


def _propose(client, new_name="Ada L."):
    response = client.post(
        "/api/actions/UpdateCustomerName",
        json={"parameters": {"customer_id": "cust_001", "new_name": new_name}},
        headers=_csrf(client),
    )
    assert response.status_code == 202, response.text
    return response.json()["pending_write"]["id"]


def _inbox(client):
    response = client.get("/api/writes/awaiting")
    assert response.status_code == 200, response.text
    return response.json()


class TestTheOrdinarySequence:
    def test_propose_then_see_it_then_approve_it(self, client):
        _login(client, "alice")
        write_id = _propose(client)

        assert [entry["write_id"] for entry in _inbox(client)] == [write_id]

        confirmed = client.post(
            f"/api/writes/{write_id}/confirm", json={"approved": True},
            headers=_csrf(client),
        )

        assert confirmed.status_code == 200
        assert _inbox(client) == []

    def test_the_approval_actually_changes_the_data(self, client):
        # THE LINK NOTHING CHECKED for a long time. An inbox that
        # cleared a row without writing anything would pass every other
        # test here.
        _login(client, "alice")
        before = client.get("/api/objects/Customer/cust_001").json()["fields"]["name"]
        write_id = _propose(client, new_name="Grace Hopper")

        client.post(f"/api/writes/{write_id}/confirm", json={"approved": True},
                    headers=_csrf(client))

        after = client.get("/api/objects/Customer/cust_001").json()["fields"]["name"]
        assert after == "Grace Hopper"
        assert after != before

    def test_rejecting_clears_it_without_changing_anything(self, client):
        _login(client, "alice")
        before = client.get("/api/objects/Customer/cust_001").json()["fields"]["name"]
        write_id = _propose(client, new_name="Never Applied")

        rejected = client.post(
            f"/api/writes/{write_id}/confirm", json={"approved": False},
            headers=_csrf(client),
        )

        assert rejected.status_code == 200
        assert _inbox(client) == []
        assert client.get("/api/objects/Customer/cust_001").json()["fields"]["name"] == before


class TestTheQueue:
    def test_several_proposals_all_appear(self, client):
        _login(client, "alice")
        ids = [_propose(client, f"Name {n}") for n in range(3)]

        assert sorted(entry["write_id"] for entry in _inbox(client)) == sorted(ids)

    def test_approving_one_leaves_the_others(self, client):
        # A reviewer works through a queue. Consuming more than they
        # decided on would silently discard somebody's proposal.
        _login(client, "alice")
        ids = [_propose(client, f"Name {n}") for n in range(3)]

        client.post(f"/api/writes/{ids[1]}/confirm", json={"approved": True},
                    headers=_csrf(client))

        remaining = {entry["write_id"] for entry in _inbox(client)}
        assert remaining == {ids[0], ids[2]}

    def test_the_oldest_proposal_is_listed_first(self, client):
        # A reviewer works a queue, and the write closest to expiring is
        # the one whose decision is about to be taken away from them.
        _login(client, "alice")
        ids = [_propose(client, f"Name {n}") for n in range(3)]

        assert [entry["write_id"] for entry in _inbox(client)] == ids


class TestWhatEachPersonSees:
    def test_a_colleague_sees_a_write_they_may_decide_on(self, client):
        _login(client, "alice")
        write_id = _propose(client)
        _login(client, "bob")

        entry = next(e for e in _inbox(client) if e["write_id"] == write_id)

        assert entry["awaiting_your_review"] is True
        assert entry["proposed_by_you"] is False

    def test_an_outsider_sees_nothing(self, client):
        _login(client, "alice")
        _propose(client)
        _login(client, "outsider", role="process_auditor")

        assert _inbox(client) == []

    def test_an_outsider_cannot_read_the_detail(self, client):
        _login(client, "alice")
        write_id = _propose(client)
        _login(client, "outsider", role="process_auditor")

        # 404, not 403: unknown, expired and not-yours are one answer.
        assert client.get(f"/api/writes/{write_id}").status_code == 404

    def test_an_outsider_cannot_confirm(self, client):
        # THE ONE THAT MATTERS MOST. A queue that merely HIDES a write
        # from someone who could still confirm it by id would be a
        # security hole with a cosmetic fix over it.
        _login(client, "alice")
        write_id = _propose(client)
        _login(client, "outsider", role="process_auditor")

        refused = client.post(
            f"/api/writes/{write_id}/confirm", json={"approved": True},
            headers=_csrf(client),
        )

        assert refused.status_code == 404

    def test_and_the_write_survives_that_refusal(self, client):
        # A denied confirm must not consume the proposal -- otherwise
        # anyone who can guess an id can destroy somebody else's work.
        _login(client, "alice")
        write_id = _propose(client)
        _login(client, "outsider", role="process_auditor")
        client.post(f"/api/writes/{write_id}/confirm", json={"approved": True},
                    headers=_csrf(client))

        _login(client, "bob")
        assert write_id in [entry["write_id"] for entry in _inbox(client)]


class TestTheDetail:
    def test_shows_the_current_and_proposed_values(self, client):
        _login(client, "alice")
        write_id = _propose(client, new_name="Grace Hopper")

        detail = client.get(f"/api/writes/{write_id}").json()

        [change] = detail["objects"][0]["changes"]
        assert change["field_name"] == "name"
        assert change["proposed_value"] == "Grace Hopper"
        assert change["readable"] is True
        assert detail["has_redacted_fields"] is False

    def test_redacts_a_field_the_reviewer_may_not_read(self, client):
        _login(client, "alice")
        write_id = _propose(client)
        with_roles(client.app, editor={"allowed_actions": frozenset([
            "read:Customer", "execute:UpdateCustomerName",
        ])})

        detail = client.get(f"/api/writes/{write_id}").json()

        [change] = detail["objects"][0]["changes"]
        assert change["field_name"] == "name"     # still named
        assert change["readable"] is False
        assert change["current_value"] is None
        assert change["proposed_value"] is None
        assert detail["has_redacted_fields"] is True

    def test_reading_the_detail_twice_is_harmless(self, client):
        # An inbox is opened and closed. If looking at a write claimed
        # it, a reviewer would lose the ability to approve it by
        # reading it.
        _login(client, "alice")
        write_id = _propose(client)

        assert client.get(f"/api/writes/{write_id}").status_code == 200
        assert client.get(f"/api/writes/{write_id}").status_code == 200
        assert [e["write_id"] for e in _inbox(client)] == [write_id]


class TestFailedDecisions:
    def test_a_refused_approval_leaves_the_write_in_the_queue(self, client):
        # Every control built for this flow lands AFTER the point of no
        # return, so the better the controls got, the more ways there
        # were to lose a proposal.
        _login(client, "alice")
        write_id = _propose(client)

        write_mediator = client.app.state.generation.write_mediator
        original = type(write_mediator)._apply_batch
        type(write_mediator)._apply_batch = lambda self, pending: (_ for _ in ()).throw(
            ValueError("refused")
        )
        try:
            refused = client.post(
                f"/api/writes/{write_id}/confirm", json={"approved": True},
                headers=_csrf(client),
            )
        finally:
            type(write_mediator)._apply_batch = original

        assert refused.status_code == 409
        assert refused.json()["detail"]        # the reason, not a blank 500
        assert [e["write_id"] for e in _inbox(client)] == [write_id]

    def test_and_it_can_then_be_approved_successfully(self, client):
        # THE PAIR. A write put back must be genuinely usable, not just
        # present -- a reservation left set would list it and refuse
        # every claim.
        _login(client, "alice")
        write_id = _propose(client)

        write_mediator = client.app.state.generation.write_mediator
        original = type(write_mediator)._apply_batch
        type(write_mediator)._apply_batch = lambda self, pending: (_ for _ in ()).throw(
            ValueError("refused")
        )
        try:
            client.post(f"/api/writes/{write_id}/confirm", json={"approved": True},
                        headers=_csrf(client))
        finally:
            type(write_mediator)._apply_batch = original

        retried = client.post(
            f"/api/writes/{write_id}/confirm", json={"approved": True},
            headers=_csrf(client),
        )

        assert retried.status_code == 200
        assert _inbox(client) == []


def _age_everything(client):
    """Backdates every stored write past its expiry.

    EXPIRY IS STAMPED AT STORE TIME, so lowering the store's _ttl
    afterwards changes nothing for a write already held -- a first
    version of these tests did that and watched them fail. Rewriting
    expires_at is what actually ages one.
    """
    from datetime import UTC, datetime, timedelta

    # MOVING THE CLOCK, not rewriting the store. This used to replace
    # the private dict wholesale; the store now keeps nothing in memory,
    # and its injectable clock is the seam for "time passed". A day on
    # is past any TTL a test deployment configures.
    store = client.app.state.pending_writes
    later = datetime.now(UTC) + timedelta(days=1)
    store._clock = lambda: later


class TestExpiry:
    def test_an_expired_write_is_gone_from_the_queue(self, client):
        _login(client, "alice")
        _propose(client)
        _age_everything(client)

        assert _inbox(client) == []

    def test_and_confirming_it_is_a_404(self, client):
        _login(client, "alice")
        write_id = _propose(client)
        _age_everything(client)

        refused = client.post(
            f"/api/writes/{write_id}/confirm", json={"approved": True},
            headers=_csrf(client),
        )

        assert refused.status_code == 404


class TestCaching:
    def test_neither_route_may_be_cached(self, client):
        # The detail is gated PER REVIEWER -- the same write redacts
        # differently for different people -- so a cached copy is one
        # person's permitted view served to another.
        _login(client, "alice")
        write_id = _propose(client)

        for path in ("/api/writes/awaiting", f"/api/writes/{write_id}"):
            response = client.get(path)
            assert "no-store" in response.headers.get("cache-control", ""), path


class TestIdenticalProposals:
    def test_the_queue_says_which_rows_are_duplicates(self, client):
        """The defect a real inbox showed: three rows, same action, same
        object, same values, nothing distinguishing them.

        SURFACED, NOT PREVENTED. A second identical proposal might be a
        double-click or a deliberate re-request, and only the reviewer
        can tell.
        """
        _login(client, "alice")
        _propose(client, "Ada L.")
        _propose(client, "Ada L.")
        _propose(client, "Ada L.")

        counts = [entry["duplicate_count"] for entry in _inbox(client)]

        assert counts == [2, 2, 2]

    def test_a_different_value_is_not_a_duplicate(self, client):
        # Two people proposing DIFFERENT names for one customer are in
        # conflict, not agreement, and calling them duplicates would
        # hide that.
        _login(client, "alice")
        _propose(client, "Ada L.")
        _propose(client, "Grace H.")

        assert [entry["duplicate_count"] for entry in _inbox(client)] == [0, 0]

    def test_approving_one_lowers_the_count_on_the_rest(self, client):
        # The count is live, not stamped at proposal time -- otherwise
        # a reviewer clearing duplicates would watch the warning persist
        # about rows that no longer exist.
        _login(client, "alice")
        ids = [_propose(client, "Ada L.") for _ in range(3)]

        client.post(f"/api/writes/{ids[0]}/confirm", json={"approved": True},
                    headers=_csrf(client))

        assert [entry["duplicate_count"] for entry in _inbox(client)] == [1, 1]
