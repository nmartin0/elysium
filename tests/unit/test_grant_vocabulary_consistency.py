"""
Every grant verb the validator accepts is one the code asks for.

THE THIRD CALIBRATION PROBE, after the step vocabulary and the filter
operators. Same class: a vocabulary spread across files, each side
individually correct, nothing asserting they describe the same thing.

Grants are declared in two places that must agree.

    policy_validation.py   what a deployment may WRITE in policy.yaml
    the call sites         what the code ever ASKS authorize() for

A GRANT ON NEITHER SIDE FAILS SILENTLY IN BOTH DIRECTIONS, which is
what makes this worth a test rather than a convention.

A verb the validator accepts and nothing asks for is dead vocabulary: a
deployment writes it, the linter approves, and it grants nothing. That
is the shape of `read:Customer.email` without `read:Customer` before
the coherence rule -- authorised on paper, inert in fact.

A verb the code asks for and the validator rejects is worse: the
deployment cannot express the grant at all, so the check it guards can
never pass and the feature is unreachable. That is exactly how
aggregate_object was lost.

authorize() itself is a bare set-membership test with no
existence-checking of its own -- deliberately, and documented as such
-- so neither mistake produces an error anywhere. It just never
matches.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# f-strings of the shape `word:{...}` that are NOT grants. Listed
# explicitly so adding one is a decision rather than a silent
# widening of the probe.
NOT_GRANTS = {
    "note",  # api/routes.py's note cache key: f"note:{type}:{id}"
}

# Every verb followed by a colon is a grant prefix. Kept as a set
# rather than a list because the ORDER means nothing and a duplicate
# would be a mistake.
def _verbs_the_validator_accepts() -> set[str]:
    source = (ROOT / "core" / "intermediate_layer" / "policy_validation.py").read_text()
    prefixed = set(re.findall(r'grant\.startswith\("([a-z_]+):"\)', source))
    exact = {
        grant.split(":", 1)[0]
        for grant in re.findall(r'grant == "([a-z_]+:[a-z_]+)"', source)
    }
    return prefixed | exact


def _verbs_the_code_asks_for() -> set[str]:
    """Every verb passed to authorize(), across core/ and api/.

    Both shapes: f-strings building a grant from an object type, and
    bare literals like "manage:users".
    """
    verbs = set()
    for path in list((ROOT / "core").rglob("*.py")) + list((ROOT / "api").rglob("*.py")):
        source = path.read_text()
        # EVERY f-string of the shape `verb:{...}`, minus a known
        # non-grant. Two earlier versions were each wrong in one
        # direction, and both were caught:
        #
        #   matching every f-string reported `note:` as an ungrantable
        #   verb -- that is api/routes.py's note CACHE KEY;
        #
        #   matching only f-strings INSIDE an authorize() call missed
        #   `tool:` and `write:`, which are assigned to a variable
        #   first and passed on the next line. The probe then compared
        #   two sets it was no longer reading properly, which is what
        #   test_the_probe_finds_anything_at_all exists to catch.
        #
        # So: the broad match, with the exclusion named and justified
        # rather than the pattern quietly narrowed until it agreed.
        verbs |= set(re.findall(r'f"([a-z_]+):\{', source)) - NOT_GRANTS
        verbs |= {
            grant.split(":", 1)[0]
            for grant in re.findall(r'authorize\([^)]*?"([a-z_]+:[a-z_]+)"', source, re.S)
        }
    return verbs


def test_every_verb_the_code_asks_for_can_be_granted():
    """THE UNREACHABLE-FEATURE DIRECTION.

    A verb the code checks and policy.yaml cannot express means the
    check never passes -- the feature is dead and nothing reports it.
    """
    unreachable = _verbs_the_code_asks_for() - _verbs_the_validator_accepts()

    assert not unreachable, (
        f"the code asks authorize() for {sorted(unreachable)} grants, which "
        f"policy_validation.py rejects -- a deployment cannot write them, so "
        f"those checks can never pass"
    )


def test_every_verb_the_validator_accepts_is_asked_for():
    """THE DEAD-VOCABULARY DIRECTION.

    A verb a deployment may write that nothing ever checks grants
    nothing, and the linter approves it. An operator would reasonably
    believe they had granted something.
    """
    unused = _verbs_the_validator_accepts() - _verbs_the_code_asks_for()

    assert not unused, (
        f"policy_validation.py accepts {sorted(unused)} grants that nothing asks "
        f"authorize() for -- a deployment can write them and they grant nothing"
    )


def test_the_ladder_verbs_are_both_present():
    """A named check on top of the set comparison.

    read and discover are the two rungs, and a set comparison would
    stay green if BOTH vanished together -- which is exactly what a
    careless refactor of the ladder would do.
    """
    accepted = _verbs_the_validator_accepts()

    assert "read" in accepted
    assert "discover" in accepted


def test_the_probe_finds_anything_at_all():
    """THE CONTROL ON THE PROBE ITSELF.

    Both tests above compare two sets. If a regex stopped matching,
    both sets would empty and both would pass -- reporting agreement
    between two things it was no longer reading. The sub-app probe had
    exactly this bug: a pattern that made a path invisible rather than
    absent.
    """
    assert len(_verbs_the_validator_accepts()) >= 5
    assert len(_verbs_the_code_asks_for()) >= 5
