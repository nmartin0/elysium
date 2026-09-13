"""
Every "still authorized?" check agrees about what disabled means.

FOUND BY AN ASYMMETRY. The agent loop's per-hop refresh_user() asks
is_user_disabled(); the post-loop re-verification compared UserRecords
instead. Those are two checks of the same question, and they disagreed.

get_user_record() returns the SAME UserRecord whether or not an account
is disabled -- verified directly rather than assumed -- so a user
disabled mid-request with unchanged MAC value and role compared EQUAL
and the answer was served.

The window was narrow: disabled after the last hop but before synthesis
finished, which is one LLM call. Narrow is not none, and the asymmetry
was the tell.

THE SESSION QUESTION THIS ANSWERS, recorded in IDEAS.md as unconfirmed:
disabling takes effect IMMEDIATELY, not at the next login. Every
request resolves its UserRecord through get_current_user(), which
checks is_user_disabled() -- so the exposure is one request, never one
token lifetime.
"""

import pytest

from core.user_directory import UserDirectory

ROLES = {"editor": {"allowed_actions": frozenset(["read:Customer"])}}


@pytest.fixture
def directory(tmp_path):
    directory = UserDirectory(tmp_path / "creds.db", roles=lambda: ROLES)
    directory.create_user("alice", "pw", "us-west", "editor")
    return directory


def test_a_disabled_user_keeps_an_identical_record(directory):
    """THE PROPERTY THAT MAKES THE BUG POSSIBLE, pinned deliberately.

    This is not wrong -- a UserRecord describes WHO someone is, and
    disabling does not change their MAC value or role. It is recorded
    here so the next person comparing records to decide "still
    authorized?" meets this test rather than the bug.
    """
    before = directory.get_user_record("alice")
    directory.disable_user("alice")

    assert directory.get_user_record("alice") == before
    assert directory.is_user_disabled("alice") is True


def test_disabling_is_visible_the_moment_it_happens(directory):
    # Not at the next login. Every request re-asks, so the exposure is
    # one request rather than one token lifetime.
    assert directory.is_user_disabled("alice") is False

    directory.disable_user("alice")

    assert directory.is_user_disabled("alice") is True


def test_re_enabling_is_equally_immediate(directory):
    # THE CONTROL. A flag that only ever went one way would pass the
    # test above and lock people out permanently.
    directory.disable_user("alice")
    directory.enable_user("alice")

    assert directory.is_user_disabled("alice") is False


def test_an_unknown_user_is_NOT_reported_disabled_and_that_is_correct(directory):
    """A deliberate decision, pinned because it looks like a bug.

    is_user_disabled() returns False for a username that does not
    exist, and its own comment explains why: "doesn't exist" and
    "disabled" are different facts, and this method answers only the
    second. I wrote a test asserting the opposite before reading it.

    THE SAFETY LIVES ELSEWHERE, and the test below is that safety. A
    caller handling identity relies on get_user_record()'s empty-record
    contract, not on this flag.
    """
    assert directory.is_user_disabled("no-such-person") is False


def test_an_unknown_user_gets_a_record_that_grants_nothing(directory):
    """THE LOAD-BEARING CONTRACT, verified rather than assumed.

    Because is_user_disabled() deliberately says nothing about a
    missing account, the empty record is what keeps a deleted user from
    acting -- a UserRecord with no MAC value and no role, which
    authorize() denies for every grant.

    If this ever stopped being true, a deleted account would pass
    through auth_dependency's disabled check and act with whatever the
    empty record happened to allow.
    """
    from core.intermediate_layer.access_control import authorize

    ghost = directory.get_user_record("no-such-person")

    assert ghost.role_name is None
    assert ghost.security_value is None
    for grant in ("read:Customer", "manage:users", "execute:UpdateCustomerName"):
        assert authorize(ghost, ROLES, grant) is False


def test_the_post_loop_check_asks_about_disabled_at_all(directory):
    """The fix, asserted against the source rather than the route.

    THE ROUTE-LEVEL TEST COULD NOT BE WRITTEN HERE. /api/query calls a
    live model, and this environment has none -- the same reason the
    seventeen test_real_model_* integration tests fail. A version of
    this test that drove the route passed for the wrong reason
    (refused at AUTH time with 401, never reaching the check) and two
    controls caught it; a corrected version could not run at all.

    So this asserts the narrower, honest thing: that the post-loop
    re-verification asks about disabled, not only about record
    equality. It would not catch a semantic regression, and it WOULD
    catch the specific asymmetry that caused the bug -- one check
    asking is_user_disabled while its counterpart compares records that
    a disabling does not change.
    """
    import pathlib

    routes = pathlib.Path(__file__).resolve().parents[2] / "api" / "routes.py"
    source = routes.read_text()

    marker = "current_record_now = user_directory.get_user_record(current_user.user_id)"
    assert marker in source
    check = source[source.index(marker): source.index(marker) + 400]

    assert "is_user_disabled" in check, (
        "the post-loop re-verification compares records only -- a user disabled "
        "with unchanged MAC and role compares EQUAL and is served the answer"
    )
