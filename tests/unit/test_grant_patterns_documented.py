"""The grant vocabulary's documentation cannot fall behind its code
(001's F-12a).

WHAT WENT WRONG. policy_validation.py's module docstring opened "THE
SEVEN REAL GRANT PATTERNS" and then listed six. It had fallen three
behind: manage:roles and manage:escalation arrived with runtime role
editing, manage:deployment with the config surface, and none reached
the prose. The audit reported one missing literal; there were three.

That docstring is not decoration. It is where somebody writing a
policy.yaml, or reviewing a role, learns what may be granted -- and
this module's whole purpose is catching a grant string that references
something which does not exist. A file that polices typos elsewhere
while its own vocabulary goes stale is the specific irony worth a
test.

WHY A SOURCE SCAN IS LEGITIMATE HERE, when AGENTS.md records that "a
test asserting a WORD appears in source is not a test". The objection
there is to scanning as a SUBSTITUTE for calling the code -- a check
satisfied by deleting the behaviour and leaving the word in a comment.
This asserts something else: that two things in the repository AGREE
with each other. It COMPARES SETS, which is the case that same rule
explicitly allows. The behaviour of the validator is tested elsewhere;
what is tested here is that its documentation still describes it.
"""

import inspect

from core.intermediate_layer import policy_validation


def test_every_exact_grant_is_named_in_the_docstring():
    """Add a literal to EXACT_GRANTS without documenting it and this
    fails, which is precisely what did not happen three times."""
    documented = policy_validation.__doc__ or ""

    missing = [grant for grant in policy_validation.EXACT_GRANTS if grant not in documented]

    assert not missing, (
        f"EXACT_GRANTS holds {missing}, which the module docstring never mentions. "
        f"Document them, or stop enforcing them."
    )


def test_the_docstring_states_no_count_of_patterns():
    """THE ROOT CAUSE, not just the instance. A hand-maintained number
    beside a code-maintained list is what went stale; the test that
    would have caught F-12a is one that refuses the number at all.

    Without this, the obvious 'fix' is to change SEVEN to NINE and
    leave the next person the same trap.
    """
    # MATCHED ON THE HEADING FORM, not on any mention of a number.
    # The docstring deliberately QUOTES its own former wrong claim --
    # "THE SEVEN REAL GRANT PATTERNS" and then listed six -- because
    # the mistake is the useful part of the record. A test that looked
    # for the words anywhere would fail on that history and force the
    # explanation to be deleted to make it pass, which is the opposite
    # of what it is for. I wrote that version first and it fired
    # against the restored file.
    documented = " ".join((policy_validation.__doc__ or "").upper().split())

    counted = [word for word in ("FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN")
               if f"THE {word} REAL GRANT PATTERNS --" in documented]

    assert not counted, (
        f"The docstring heading counts its patterns ({counted}). That number is "
        f"maintained by hand beside a list maintained by code, which is how it "
        f"fell three behind."
    )


def test_exact_grants_has_no_duplicates_and_is_not_empty():
    """A control's companion: if EXACT_GRANTS were emptied, the first
    test above would pass vacuously -- nothing would be missing from
    the docstring because nothing would be required."""
    assert policy_validation.EXACT_GRANTS
    assert len(set(policy_validation.EXACT_GRANTS)) == len(policy_validation.EXACT_GRANTS)


def test_the_docstring_points_at_the_list_that_is_enforced():
    """The docstring no longer repeats the literals as its own list --
    it names EXACT_GRANTS. If that pointer is removed, the two can
    drift again even while the first test still passes."""
    source = inspect.getsource(policy_validation)
    documented = policy_validation.__doc__ or ""

    assert "EXACT_GRANTS" in documented
    assert "EXACT_GRANTS = (" in source
