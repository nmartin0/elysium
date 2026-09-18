"""
An action may only mutate types its parameters can reach.

THE EFFECT SIGNATURE, WRITTEN AS A CHECK. An action is not a function
from one type to another -- it takes several parameters and mutates
several types -- so the honest shape is closer to

    action : (A, B, ...) -> Effect[C, D, ...]

and both halves were ALREADY DECLARED: parameters name their
`object_type`, sub-writes name the `object_type` they write. What was
missing was the arrow between them.

SO A TransferFunds TAKING TWO ACCOUNTS COULD QUIETLY MUTATE A CUSTOMER
and pass validation.

NO DEPENDENT TYPES REQUIRED, and none available: refinement and
dependent types for Python are academic -- Liquid Haskell, refinement
types for TypeScript, "Dependent Types in Practical Programming" from
1999 -- and the ecosystem offers runtime schema validation instead.
This is that, at config load, where this project already enforces
every other shape.
"""

import pytest

from core.ontology.action_types import _validate_effects_are_reachable

OBJECT_TYPES = {
    "Account": {"fields": {"owner": {"type": "link", "target": "Customer"}}},
    "Customer": {"fields": {"account": {"type": "link", "target": "Account"}}},
    "Audit": {"fields": {}},
}


def _check(parameters, sub_writes):
    _validate_effects_are_reachable(
        "T", {"parameters": parameters, "sub_writes": sub_writes}, OBJECT_TYPES,
    )


ACCOUNT_PARAM = {"a": {"type": "object_reference", "object_type": "Account"}}


class TestWhatAnActionMayWrite:
    def test_its_own_parameter_type(self):
        _check(ACCOUNT_PARAM, [{"object_type": "Account"}])

    def test_a_type_its_parameter_links_to(self):
        """AN ACTION ON A CUSTOMER MAY WRITE ITS TRANSACTIONS, which is
        what object_reference_list and link traversal exist for.
        Refusing that would break the legitimate case."""
        _check(ACCOUNT_PARAM, [{"object_type": "Customer"}])

    def test_several_sub_writes_across_reachable_types(self):
        _check(ACCOUNT_PARAM, [
            {"object_type": "Account"},
            {"object_type": "Customer"},
            {"object_type": "Account"},
        ])


class TestWhatItMayNot:
    def test_an_unrelated_type_is_refused(self):
        with pytest.raises(ValueError, match="none of its parameters reaches"):
            _check(ACCOUNT_PARAM, [{"object_type": "Audit"}])

    def test_the_message_names_what_is_reachable(self):
        # A refusal that does not say what WAS allowed leaves an author
        # guessing, which is how a guard gets worked around.
        with pytest.raises(ValueError, match="Account, Customer"):
            _check(ACCOUNT_PARAM, [{"object_type": "Audit"}])

    def test_one_bad_write_among_good_ones_is_caught(self):
        with pytest.raises(ValueError, match="'Audit'"):
            _check(ACCOUNT_PARAM, [
                {"object_type": "Account"},
                {"object_type": "Audit"},
            ])


class TestWhereTheCheckDoesNotApply:
    def test_an_action_with_no_object_parameter_is_left_alone(self):
        """NOTHING TO CHECK AGAINST. An action with no object_reference
        parameter CREATES rather than mutates, and what it may create
        is a different question from what it may reach."""
        _check({"name": {"type": "string"}}, [{"object_type": "Audit"}])

    def test_a_sub_write_without_an_object_type_is_left_alone(self):
        # Another validator's business; duplicating it here would give
        # two different messages for one mistake.
        _check(ACCOUNT_PARAM, [{"operation": "update"}])


def test_only_one_hop_through_links():
    """A TRANSITIVE CLOSURE WOULD REACH MOST OF AN ONTOLOGY and stop
    being a constraint at all. Customer links to Account and Account
    links to Customer, but neither links to Audit -- and a two-hop
    rule would still not reach it, which is the point: the limit is
    deliberate, not incidental.
    """
    deep = {
        "A": {"fields": {"b": {"type": "link", "target": "B"}}},
        "B": {"fields": {"c": {"type": "link", "target": "C"}}},
        "C": {"fields": {}},
    }

    with pytest.raises(ValueError, match="'C'"):
        _validate_effects_are_reachable(
            "T",
            {
                "parameters": {"a": {"type": "object_reference", "object_type": "A"}},
                "sub_writes": [{"object_type": "C"}],
            },
            deep,
        )
