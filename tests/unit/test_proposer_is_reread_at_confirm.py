"""
A queued write runs on its PROPOSER'S authority as it is NOW (NEW-3).

THE GAP: a PendingWrite holds the proposer's record as it was at
proposal. Confirm re-checked the grant and the objects' reach against
that snapshot, so a proposer DISABLED, DELETED, moved to another ROLE or
to another COMPARTMENT since proposing still had their write applied
when a colleague approved it. disable_user() ended their sessions; it
did not end their queued writes.

THE FIX: the approve route re-reads the proposer from the user directory
and passes the result as `proposer_now`. None (gone or disabled) is
refused outright; a current record is what the grant and reach checks
use. A caller with no directory passes NOT_LOOKED_UP and keeps the
snapshot -- and a guard below holds every caller under api/ to passing
the argument, because api/ always has the directory.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.auth.credential_store import CredentialStore
from core.intermediate_layer.auth import UserRecord
from core.ontology.write_mediator import NOT_LOOKED_UP
from core.user_directory import UserDirectory
from tests.unit.test_confirming_a_write_rechecks_reach import WEST, build_deployment

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def deployment(tmp_path):
    return build_deployment(tmp_path)


def _proposed(deployment):
    return deployment.propose_action(WEST, "close", {"ticket": "t1"}, origin="human")


class TestTheProposerIsWhoTheyAreNow:
    def test_a_proposer_whose_account_is_gone_is_refused(self, deployment):
        pending = _proposed(deployment)

        with pytest.raises(ValueError, match="no longer has an active account"):
            deployment.confirm_and_execute(pending, approved=True, approver=WEST,
                                           proposer_now=None)
        assert deployment.status() == "open"

    def test_a_proposer_moved_to_another_compartment_is_refused(self, deployment):
        """The OBJECT did not move; the PROPOSER did. The snapshot says
        us-west, so only re-reading them can see it."""
        pending = _proposed(deployment)
        moved = UserRecord(user_id="u", security_value="us-east", role_name="agent")

        with pytest.raises(PermissionError, match="no longer within reach"):
            deployment.confirm_and_execute(pending, approved=True, approver=WEST,
                                           proposer_now=moved)
        assert deployment.status() == "open"

    def test_a_proposer_moved_to_a_role_without_the_grant_is_refused(self, deployment):
        """SAME GENERATION. Reassigning a user's role is a directory
        change, not a configuration one, so the generation shortcut must
        not skip it."""
        deployment.roles["viewer"] = {"allowed_actions": frozenset(["read:Ticket"])}
        pending = _proposed(deployment)
        demoted = UserRecord(user_id="u", security_value="us-west", role_name="viewer")

        with pytest.raises(ValueError, match="no longer holds 'execute:close'"):
            deployment.confirm_and_execute(pending, approved=True, approver=WEST,
                                           proposer_now=demoted)
        assert deployment.status() == "open"

    def test_an_unchanged_proposer_applies(self, deployment):
        pending = _proposed(deployment)
        deployment.confirm_and_execute(pending, approved=True, approver=WEST,
                                       proposer_now=WEST)
        assert deployment.status() == "closed"

    def test_without_a_directory_the_snapshot_is_used(self, deployment):
        pending = _proposed(deployment)
        deployment.confirm_and_execute(pending, approved=True, approver=WEST,
                                       proposer_now=NOT_LOOKED_UP)
        assert deployment.status() == "closed"

    def test_a_rejection_needs_no_proposer(self, deployment):
        """Declining a write grants nothing, so a gone proposer's write
        can still be cleared from the queue."""
        pending = _proposed(deployment)
        assert deployment.confirm_and_execute(pending, approved=False, approver=WEST,
                                              proposer_now=None) is None


class TestTheRouteLooksThemUp:
    @pytest.fixture
    def directory(self, tmp_path):
        path = tmp_path / "credentials.db"
        CredentialStore(path)
        directory = UserDirectory(path, {"agent": {"allowed_actions": frozenset()}})
        directory.create_user("u", "pw", "us-west", "agent")
        return directory

    def _lookup(self, directory, user_id):
        from api.routes import _proposer_as_they_are_now

        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            user_directory=directory)))
        return _proposer_as_they_are_now(request, user_id)

    def test_an_active_account_is_its_current_record(self, directory):
        assert self._lookup(directory, "u") == UserRecord("u", "us-west", "agent")

    def test_a_disabled_account_is_none(self, directory):
        directory.disable_user("u")
        assert self._lookup(directory, "u") is None

    def test_a_deleted_account_is_none(self, directory):
        directory.delete_user("u")
        assert self._lookup(directory, "u") is None


def test_every_confirm_under_api_says_which_proposer_it_found():
    """api/ holds the user directory, so it has no reason to fall back
    to the snapshot. A new route that confirms without `proposer_now`
    would quietly reopen NEW-3; this finds it."""
    calls = []
    for path in sorted((ROOT / "api").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            target = None
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "confirm_and_execute":
                    target = node
                elif (isinstance(func, ast.Attribute) and func.attr == "partial" and node.args
                      and isinstance(node.args[0], ast.Attribute)
                      and node.args[0].attr == "confirm_and_execute"):
                    target = node
            if target is not None:
                calls.append((path.name, target.lineno,
                              any(k.arg == "proposer_now" for k in target.keywords)))
    assert calls, "no confirm under api/ found -- the guard is looking in the wrong place"
    assert all(passed for _, _, passed in calls), calls
