"""
The rules a role change must pass, tested apart from the endpoints.

SOME CANNOT BE REACHED THROUGH THE API on the test deployment: every
manage:roles holder there shares one role, so "not your own role"
fires before "nobody could edit roles again" ever can. The pure
functions are where the second is proved.
"""

import sqlite3

from core.role_changes import (
    RoleChange,
    approval_problem,
    change_problem,
    resulting_roles,
)


# THESE TESTS ARE ABOUT FOUR-EYES AND STALENESS, not escalation -- so
# the proposer holds everything, and escalation is tested on its own.
def _HOLDS_ALL(_grant):
    return True


ROLES = {
    "owner": {"allowed_actions": ["manage:roles", "manage:users"]},
    "second": {"allowed_actions": ["manage:roles"]},
    "reader": {"allowed_actions": ["read:X"]},
}


def _valid(_result):
    return None


class TestNoLockout:
    def test_leaving_nobody_able_to_edit_roles_is_refused(self):
        """ONCE THE STORE GOVERNS, policy.yaml cannot restore this."""
        holders = {"owner": 1, "second": 0}

        problem = change_problem(ROLES, "owner", ["manage:users"], holders, holders, _valid)

        assert "no active user could edit roles" in problem

    def test_a_role_nobody_holds_does_not_count(self):
        """HOLDING THE GRANT IS NOT ENOUGH -- somebody active must hold
        the role. `second` has manage:roles and no members."""
        assert change_problem(
            ROLES, "owner", ["manage:users"], {"owner": 1}, {"owner": 1}, _valid,
        )

    def test_another_active_holder_is_enough(self):
        holders = {"owner": 1, "second": 1}

        assert change_problem(ROLES, "owner", ["manage:users"], holders, holders, _valid) is None


class TestTheValidatorDecides:
    def test_a_refusal_is_reported(self):
        def refuses(_result):
            raise ValueError("grant 'read:Nope' references unknown type")

        problem = change_problem(ROLES, "reader", ["read:Nope"], {"owner": 1}, {"owner": 1}, refuses)

        assert "unknown type" in problem


class TestResultingRoles:
    def test_one_role_changes_and_the_rest_do_not(self):
        result = resulting_roles(ROLES, "reader", ["read:X", "read:Y"])

        assert result["reader"]["allowed_actions"] == ["read:X", "read:Y"]
        assert result["owner"] == {"allowed_actions": ["manage:roles", "manage:users"]}

    def test_none_deletes(self):
        assert "reader" not in resulting_roles(ROLES, "reader", None)


def _change(**overrides):
    base = {
        "change_id": "c1", "role_name": "reader", "before": ["read:X"],
        "after": ["read:X", "read:Y"], "proposed_by": "alice",
        "proposed_at": "", "status": "pending", "decided_by": None,
        "decided_at": None, "detail": None,
    }
    base.update(overrides)
    return RoleChange(**base)


class TestApproval:
    def test_four_eyes_is_not_recorded(self):
        """SOMEBODY ELSE MAY STILL APPROVE IT, so it stays pending."""
        status, _ = approval_problem(_change(), "alice", ROLES, {"owner": 1}, {"owner": 1}, _valid,
            proposer_holds=_HOLDS_ALL)

        assert status == ""

    def test_stale_is_recorded(self):
        """THE TRAIL SAYS WHY IT NEVER TOOK EFFECT."""
        changed = {**ROLES, "reader": {"allowed_actions": ["read:Z"]}}

        status, _ = approval_problem(_change(), "bob", changed, {"owner": 1}, {"owner": 1}, _valid,
            proposer_holds=_HOLDS_ALL)

        assert status == "stale"

    def test_a_clean_approval_passes(self):
        assert approval_problem(_change(), "bob", ROLES, {"owner": 1}, {"owner": 1}, _valid,
            proposer_holds=_HOLDS_ALL) is None


class TestTwoStoresMayShareAFile:
    def test_both_get_their_tables_whichever_opens_first(self, tmp_path):
        """THE CACHE WAS KEYED BY PATH. RoleChangeStore opened roles.db
        first, marked it verified, and RoleStore's CREATE TABLE never
        ran -- "no such table: role_store_meta". Keyed by path and
        schema, each store is guaranteed its own tables."""
        from core.role_changes import RoleChangeStore
        from core.role_store import RoleStore

        path = tmp_path / "roles.db"
        RoleChangeStore(path).propose("reader", None, ["read:X"], "alice")

        RoleStore(path).save({"reader": {"allowed_actions": ["read:X"]}})

        tables = {row[0] for row in sqlite3.connect(path).execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"role_changes", "roles", "role_store_meta"} <= tables


class TestTwoCountsTwoQuestions:
    def test_a_disabled_holder_blocks_deletion(self):
        """STRANDING COUNTS DISABLED ACCOUNTS -- they can be re-enabled."""
        problem = change_problem(
            ROLES, "reader", None, {"reader": 1, "owner": 1}, {"owner": 1}, _valid,
        )

        assert "counting disabled" in problem

    def test_but_a_disabled_holder_cannot_prevent_a_lockout(self):
        """LOCKOUT COUNTS ONLY ACTIVE ONES -- a disabled account cannot
        edit anything, so it cannot keep roles editable."""
        problem = change_problem(
            ROLES, "owner", ["manage:users"],
            {"owner": 1, "second": 1}, {"owner": 1}, _valid,
        )

        assert "no active user could edit roles" in problem



class TestEscalation:
    """ONLY WHAT A CHANGE ADDS, checked against its AUTHOR -- as
    Kubernetes checks the requester."""

    def _holds(self, *grants):
        return lambda grant: grant in grants

    def test_adding_a_lacked_grant_is_named(self):
        from core.role_changes import escalation_problem

        problem = escalation_problem(["read:X"], ["read:X", "read:Y"], self._holds("read:X"))

        assert "read:Y" in problem

    def test_adding_a_held_grant_passes(self):
        from core.role_changes import escalation_problem

        assert escalation_problem([], ["read:X"], self._holds("read:X")) is None

    def test_removal_passes(self):
        from core.role_changes import escalation_problem

        assert escalation_problem(["read:X", "read:Y"], ["read:X"], self._holds()) is None

    def test_a_new_role_checks_every_grant(self):
        """NO `before` MEANS EVERYTHING IS BEING ADDED."""
        from core.role_changes import escalation_problem

        assert escalation_problem(None, ["read:X"], self._holds())

    def test_manage_escalation_lets_anything_through(self):
        """THE WAY THROUGH, and it must exist: a grant added to the
        ontology today is held by nobody."""
        from core.role_changes import ESCALATE, escalation_problem

        assert escalation_problem([], ["execute:New"], self._holds(ESCALATE)) is None


class TestTheAuthorIsReCheckedAtApproval:
    def test_a_proposer_who_lost_the_grant_cannot_have_it_handed_out(self):
        """RE-EVALUATED AT THE POINT OF USE: what the proposer holds when
        the change takes effect, not when they asked."""
        change = _change(before=["read:X"], after=["read:X", "read:Y"])

        status, reason = approval_problem(
            change, "bob", ROLES, {"owner": 1}, {"owner": 1}, _valid,
            proposer_holds=lambda grant: grant == "read:X",
        )

        assert status == "stale"
        assert "read:Y" in reason

    def test_a_proposer_who_is_gone_cannot_have_anything_handed_out(self):
        change = _change(before=["read:X"], after=["read:X", "read:Y"])

        status, _ = approval_problem(
            change, "bob", ROLES, {"owner": 1}, {"owner": 1}, _valid,
            proposer_holds=None,
        )

        assert status == "stale"
