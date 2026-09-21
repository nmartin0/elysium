"""
Changing a role: proposed by one person, approved by another.

FOUNDRY'S MODEL -- security changes are approval requests, and a change
to access policy needs approval "from a user... other than the change
request author". Approving saves the role store and reloads, so the new
rules take effect atomically; if the reload fails, the save is undone.
"""

from tests.integration.test_api import _csrf_headers, _login  # noqa: F401


def _as(client, username, role="debug"):
    directory = client.app.state.user_directory
    if not directory.user_exists(username):
        directory.create_user(username, "correct-pw", "us-west", role)
    _login(client, username, "correct-pw")


def _grants(client, role):
    return client.get("/api/roles").json()["roles"][role]


def _propose(client, role, grants):
    return client.post(
        "/api/roles/changes", json={"role_name": role, "grants": grants},
        headers=_csrf_headers(client),
    )


def _approve(client, change_id):
    return client.post(
        f"/api/roles/changes/{change_id}/approve", headers=_csrf_headers(client),
    )


def _widened_customer_service(client):
    return sorted({*_grants(client, "customer_service"), "read:Account"})


class TestTheFlow:
    def test_proposed_by_one_approved_by_another_takes_effect(self, client):
        _as(client, "dana")
        change = _propose(client, "customer_service", _widened_customer_service(client))
        assert change.status_code == 200, change.text
        _as(client, "erin")

        assert _approve(client, change.json()["change_id"]).status_code == 200
        assert "read:Account" in _grants(client, "customer_service")

    def test_once_applied_the_store_governs(self, client):
        """HOW AN ADMINISTRATOR LEARNS that policy.yaml stopped working."""
        _as(client, "dana")
        change_id = _propose(
            client, "customer_service", _widened_customer_service(client),
        ).json()["change_id"]
        _as(client, "erin")
        _approve(client, change_id)

        assert client.get("/api/roles").json()["source"] == "role store"

    def test_nothing_changes_until_approved(self, client):
        _as(client, "dana")
        _propose(client, "customer_service", _widened_customer_service(client))

        assert "read:Account" not in _grants(client, "customer_service")
        assert client.get("/api/roles").json()["source"] == "policy.yaml"


class TestFourEyes:
    def test_the_author_cannot_approve(self, client):
        """"Other than the change request author." """
        _as(client, "dana")
        change_id = _propose(
            client, "customer_service", _widened_customer_service(client),
        ).json()["change_id"]

        assert _approve(client, change_id).status_code == 409

    def test_and_it_stays_pending_for_somebody_else(self, client):
        """FOUR-EYES IS NOT RECORDED as an outcome -- another approver
        may still take it."""
        _as(client, "dana")
        change_id = _propose(
            client, "customer_service", _widened_customer_service(client),
        ).json()["change_id"]
        _approve(client, change_id)

        pending = client.get("/api/roles/changes").json()["changes"]
        assert [c["change_id"] for c in pending] == [change_id]


class TestStale:
    def test_a_role_changed_since_the_proposal_is_refused(self, client):
        """AN APPROVER NEVER AGREES TO A MERGE NOBODY REVIEWED."""
        _as(client, "dana")
        base = _grants(client, "customer_service")
        first = _propose(client, "customer_service", sorted({*base, "read:Account"}))
        second = _propose(client, "customer_service", sorted({*base, "discover:Account"}))
        _as(client, "erin")
        _approve(client, first.json()["change_id"])

        response = _approve(client, second.json()["change_id"])

        assert response.status_code == 409
        assert "has changed since" in response.json()["detail"]

    def test_and_is_recorded_as_stale(self, client):
        _as(client, "dana")
        base = _grants(client, "customer_service")
        first = _propose(client, "customer_service", sorted({*base, "read:Account"}))
        second = _propose(client, "customer_service", sorted({*base, "discover:Account"}))
        _as(client, "erin")
        _approve(client, first.json()["change_id"])
        _approve(client, second.json()["change_id"])

        assert client.get("/api/roles/changes").json()["changes"] == []


class TestWhatIsRefusedAtProposal:
    def test_removing_manage_roles_from_your_own_role(self, client):
        _as(client, "dana")
        grants = [g for g in _grants(client, "debug") if g != "manage:roles"]

        response = _propose(client, "debug", grants)

        assert response.status_code == 400
        assert "your own role" in response.json()["detail"]

    def test_deleting_a_role_somebody_holds(self, client):
        """They would hold a role that does not exist."""
        _as(client, "cy", "customer_service")
        _as(client, "dana")

        response = _propose(client, "customer_service", None)

        assert response.status_code == 400
        # "ACCOUNT(S)", no longer "active user": disabled holders count
        # too, since they can be re-enabled into a missing role.
        assert "account(s) hold" in response.json()["detail"]

    def test_a_grant_the_validator_refuses(self, client):
        _as(client, "dana")

        response = _propose(client, "customer_service", ["read:NoSuchType"])

        assert response.status_code == 400

    def test_a_change_that_changes_nothing(self, client):
        _as(client, "dana")

        response = _propose(client, "customer_service", _grants(client, "customer_service"))

        assert response.status_code == 400


class TestWhoMay:
    def test_manage_users_alone_may_not_propose(self, client):
        _as(client, "ann", "admin")

        assert _propose(client, "admin", ["manage:users"]).status_code == 403


class TestRejecting:
    def test_a_rejected_change_never_applies(self, client):
        _as(client, "dana")
        change_id = _propose(
            client, "customer_service", _widened_customer_service(client),
        ).json()["change_id"]
        _as(client, "erin")

        client.post(f"/api/roles/changes/{change_id}/reject",
                    headers=_csrf_headers(client))

        assert _approve(client, change_id).status_code == 409
        assert "read:Account" not in _grants(client, "customer_service")


class TestAFailedReloadIsUndone:
    def test_the_store_is_put_back(self, client, monkeypatch):
        """SAVE, RELOAD, AND UNDO THE SAVE IF THE RELOAD FAILS -- it can
        fail for a reason unrelated to roles. Leaving the store saved
        would make the next restart load roles nobody saw take effect."""
        import api.routes as routes

        _as(client, "dana")
        change_id = _propose(
            client, "customer_service", _widened_customer_service(client),
        ).json()["change_id"]
        _as(client, "erin")

        def broken(*args, **kwargs):
            raise ValueError("an unrelated YAML file is broken")
        monkeypatch.setattr(routes, "reload_generation", broken)

        assert _approve(client, change_id).status_code == 500
        assert client.get("/api/roles").json()["source"] == "policy.yaml"


class TestApprovalsDoNotLoseEachOther:
    def test_a_request_pinned_before_another_approval_keeps_it(self, client, monkeypatch):
        """THE PER-REQUEST PIN DEFEATED THE APPROVAL LOCK.

        An approve request pins its generation when it first checks
        manage:roles -- BEFORE taking the lock. If another approval
        finishes while it waits, it computes the new role set from its
        pinned, OLDER roles and saves that -- silently undoing the other
        approval. The lock existed to stop exactly that lost update.

        Staged by pinning the second approval to the generation from
        BEFORE the first one applied, which is what the wait produces.
        """
        import api.routes as routes

        _as(client, "dana")
        base_cs = _grants(client, "customer_service")
        first = _propose(client, "customer_service", sorted({*base_cs, "read:Account"}))
        base_ed = _grants(client, "editor")
        second = _propose(client, "editor", sorted({*base_ed, "discover:Account"}))
        _as(client, "erin")
        before_first = client.app.state.generation

        assert _approve(client, first.json()["change_id"]).status_code == 200

        monkeypatch.setattr(routes, "_generation", lambda request: before_first)
        assert _approve(client, second.json()["change_id"]).status_code == 200
        monkeypatch.undo()

        roles = client.get("/api/roles").json()["roles"]
        assert "discover:Account" in roles["editor"]
        assert "read:Account" in roles["customer_service"], (
            "the second approval, computed from an older pinned generation, "
            "overwrote the first"
        )


class TestNobodyIsStranded:
    def test_a_role_held_only_by_a_disabled_account_cannot_be_deleted(self, client):
        """A DISABLED ACCOUNT CAN BE RE-ENABLED. Counting only ACTIVE
        holders is right for the lockout check -- a disabled account
        cannot edit anything -- and wrong for this one: delete the role,
        re-enable the account, and it holds a role that does not exist.

        One map of holders was answering two questions.
        """
        directory = client.app.state.user_directory
        _as(client, "cy", "customer_service")
        directory.disable_user("cy")
        _as(client, "dana")

        response = _propose(client, "customer_service", None)

        assert response.status_code == 400
        assert "hold" in response.json()["detail"]


class TestAccountCreationWaitsForAnApproval:
    def test_it_waits_while_an_approval_holds_the_lock(self, client):
        """THE RACE RECORDED IN PATCH 285, now closed.

        An account created in a role at the instant an approval deletes
        it -- between the approval counting holders and saving -- would
        hold a role that no longer exists. Account creation now takes
        the same lock, so it waits for the approval to finish.

        BEHAVIOURAL, NOT SEQUENTIAL. A test that approved and then
        created would pass without the lock too; the race needs both in
        flight. So this holds the lock itself, starts a creation on
        another thread, and checks the creation is WAITING before
        letting it go.
        """
        import threading

        import api.routes as routes

        _as(client, "ann", "admin")
        headers = _csrf_headers(client)
        outcome = {}

        def create():
            outcome["status"] = client.post(
                "/api/users",
                json={"username": "newcomer", "password": "a-long-password-1",
                      "mac_value": "us-west", "role_name": "customer_service"},
                headers=headers,
            ).status_code

        with routes._role_change_lock:
            worker = threading.Thread(target=create)
            worker.start()
            worker.join(timeout=1.0)
            assert worker.is_alive(), "creation did not wait for the lock"
            assert "status" not in outcome

        worker.join(timeout=10)
        assert outcome["status"] == 201
