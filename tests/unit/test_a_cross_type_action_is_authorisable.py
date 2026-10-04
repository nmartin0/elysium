"""
A valid policy can authorise a cross-type action.

`F-02`, reproduced 24 September and outranking everything in
BLOCKING.md since: the policy validator rejected EVERY `write:` grant
while `write_mediator` demanded `write:<Type>.<field>` for each
mutation of a cross-type action. The two halves had never agreed, so
no valid policy could authorise one at all.

THE OWNER CHOSE OPTION C, which the research surfaced and the file did
not have. Foundry's model: "you must hold edit permissions on the
action type AND on all ontology resource types edited by the action."
So the grant is per ACTION and per TYPE -- never per field.

    execute:TransferFunds   the action
    write:Order             each type it edits
    write:Customer

WHAT THE OTHER TWO WOULD HAVE COST. Restoring the per-field grant (A)
restores something vestigial -- this codebase's own comment says it
"was accepted here and checked by no authorize() call anywhere... a
policy granting write:Order.total validated cleanly and permitted
nothing". Relying on `execute:` alone (B) is simpler and weaker than
anything in the precedent: it drops the per-type check Foundry keeps.

`F-03` GOES WITH IT, AND NOT BY COINCIDENCE. The old loop read
`sw_def["mutations"]`, which a DELETE sub-write does not have --
that was the KeyError. Asking per type rather than per mutation
removes the key access entirely. One change, because they were one
defect seen from two sides.

`F-12c` GOES TOO. The rejection message claimed `write:` is "not
enforced anywhere", which was false before (the write path demanded
it) and would be false now (the type-level form is checked).
"""

import pytest

from core.intermediate_layer.policy_validation import _validate_one_grant

TYPES = {"Order": {}, "Customer": {}}
ACTIONS = {"TransferFunds": {}}


def _check(grant):
    _validate_one_grant("analyst", grant, TYPES, ACTIONS, [])


class TestTheGrantThatMakesItPossible:
    @pytest.mark.parametrize("grant", ["write:Order", "write:Customer"])
    def test_a_type_level_write_is_valid(self, grant):
        """THE WHOLE POINT. Before this, no `write:` grant of any shape
        could appear in a valid policy."""
        _check(grant)

    def test_the_action_grant_is_unaffected(self):
        _check("execute:TransferFunds")

    def test_both_together_are_what_a_cross_type_action_needs(self):
        for grant in ("execute:TransferFunds", "write:Order", "write:Customer"):
            _check(grant)


class TestWhatStaysRejected:
    def test_a_per_field_write_still_fails(self):
        """For the ORIGINAL reason, which was always right: nothing
        checks it, so it would permit nothing while reading as a
        permission."""
        with pytest.raises(ValueError, match="names a FIELD"):
            _check("write:Order.total")

    def test_the_field_rejection_offers_the_type_form(self):
        """Somebody reaching for `write:Order.total` wants to permit a
        write to Order. The message says how."""
        with pytest.raises(ValueError) as caught:
            _check("write:Order.total")

        assert "write:Order" in str(caught.value)
        assert "execute:" in str(caught.value)

    def test_an_undeclared_type_fails(self):
        with pytest.raises(ValueError, match="not a declared object type"):
            _check("write:Nonsense")

    def test_the_undeclared_rejection_lists_what_exists(self):
        with pytest.raises(ValueError, match="Customer"):
            _check("write:Nonsense")


class TestF12cTheFalseClaim:
    def test_no_message_claims_write_is_unenforced(self):
        """It was false before -- the write path demanded it -- and
        would be false now."""
        for grant in ("write:Order.total", "write:Nonsense"):
            with pytest.raises(ValueError) as caught:
                _check(grant)
            assert "not enforced anywhere" not in str(caught.value)

    def test_the_source_no_longer_carries_the_claim(self):
        from pathlib import Path

        source = Path("core/intermediate_layer/policy_validation.py").read_text()
        # THE MESSAGE, not the prose. The phrase survives in a comment
        # explaining that the claim was false, which is the opposite of
        # making it -- a substring check cannot tell those apart.
        i = source.index('if grant.startswith("write:"):')
        block = source[i:i + 2200]
        code = [line for line in block.splitlines()
                if line.strip() and not line.strip().startswith("#")]

        assert not [line for line in code if "not enforced anywhere" in line]


class TestF03TheDeleteKeyError:
    """The old loop read `sw_def["mutations"]` directly. A delete
    sub-write has no such key -- `F-03`.

    THESE ARE SOURCE CHECKS AND I AM SAYING SO. The behavioural
    reproduction needs a mediator with a declared cross-type action
    containing a delete, which is a fixture this file does not have.
    What is verified here is that the key access is gone and that the
    loop no longer walks mutations at all -- which is why the KeyError
    cannot occur, rather than evidence that it does not.
    """

    def test_the_cross_type_check_no_longer_indexes_mutations(self):
        from pathlib import Path

        source = Path("core/ontology/write_mediator.py").read_text()
        i = source.index("affected_types = {sw[")
        block = source[i:i + 1800]
        code = [line for line in block.splitlines()
                if line.strip() and not line.strip().startswith("#")]

        assert not [line for line in code if '["mutations"]' in line], code

    def test_it_iterates_types_rather_than_mutations(self):
        from pathlib import Path

        source = Path("core/ontology/write_mediator.py").read_text()
        i = source.index("affected_types = {sw[")
        block = source[i:i + 1800]

        assert "for affected_type in sorted(affected_types):" in block
        assert 'f"write:{affected_type}"' in block

    def test_the_only_other_direct_access_is_behind_a_delete_return(self):
        """`action_types.py` indexes it too, but a delete sub-write
        returns before reaching that line -- checked, because a second
        source of the same KeyError would make this fix partial."""
        from pathlib import Path

        source = Path("core/ontology/action_types.py").read_text()
        i = source.index('if not isinstance(sub_write["mutations"], list)')
        before = source[max(0, i - 600):i]

        assert "must not declare mutations" in before
        assert "return" in before
