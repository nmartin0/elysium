"""
An action may refuse to be started by a trigger.

A DIFFERENT QUESTION FROM auto_execute, and the two are easy to
confuse. `auto_execute` asks whether a proposal needs confirming;
`automatable` asks whether a trigger may propose it AT ALL.

An action can be both: safe to run without confirmation when a person
asked for it, and never to be started by a condition firing at 3am.
Refusing the second is not a stricter version of the first -- it is
about WHO may begin the write rather than what happens after.

ABSENT MEANS TRUE, which is the one permissive default in that
validator. Every action already passes through the approvals queue
unless auto_execute says otherwise, so a trigger proposing one
produces a pending write somebody must decide on. The flag is for
actions that should not even be PROPOSED unattended.
"""

import pytest

from core.ontology.action_types import validate_action_types


def _action(**overrides):
    """A MINIMAL VALID ACTION, not a minimal dict.

    BUILT BY READING THE SHIPPED ONE rather than by guessing. Three
    attempts failed in sequence -- `sub_writes` must be non-empty,
    `affected_object_types` must be there, and a sub-write's changes
    are called `mutations` with a `set`/`property`/`value` shape.

    Each refusal was the validator being right, and each cost a cycle
    that reading `ontology_schema.yaml` first would have saved.
    """
    return {
        "description": "does a thing",
        "affected_object_types": ["Customer"],
        "parameters": {
            "customer_id": {
                "type": "object_reference",
                "object_type": "Customer",
                "required": True,
                "display_name": "Customer",
            },
            "new_name": {
                "type": "string",
                "required": True,
                "display_name": "New name",
            },
        },
        "sub_writes": [
            {
                "object_type": "Customer",
                "object_id": "parameter.customer_id",
                "operation": "update",
                "mutations": [
                    {
                        "set": {
                            "property": "name",
                            "value": "parameter.new_name",
                        },
                    },
                ],
            },
        ],
        **overrides,
    }


OBJECT_TYPES = {
    "Customer": {
        "id_field": "customer_id",
        "fields": {
            "customer_id": {"type": "data"},
            "name": {"type": "data"},
        },
    },
}


class TestTheFlagIsValidated:
    def test_true_is_accepted(self):
        validate_action_types({"A": _action(automatable=True)}, OBJECT_TYPES)

    def test_false_is_accepted(self):
        validate_action_types({"A": _action(automatable=False)}, OBJECT_TYPES)

    def test_absent_is_accepted(self):
        """ABSENT MEANS TRUE, and an author who wants otherwise says
        so -- rather than every author opting in to ordinary
        behaviour."""
        validate_action_types({"A": _action()}, OBJECT_TYPES)

    def test_a_string_is_refused(self):
        """"false" IS NOT False, and a deployment that wrote it would
        get automation it explicitly tried to prevent."""
        with pytest.raises(ValueError, match="must be true or false"):
            validate_action_types({"A": _action(automatable="false")},
                                  OBJECT_TYPES)

    def test_the_message_names_the_action(self):
        with pytest.raises(ValueError, match="'Risky'"):
            validate_action_types({"Risky": _action(automatable=1)},
                                  OBJECT_TYPES)


class TestItIsSeparateFromAutoExecute:
    def test_both_may_be_set_together(self):
        """SAFE WITHOUT CONFIRMATION WHEN A PERSON ASKED, and never
        started by a condition. That combination is the whole point of
        two flags."""
        # A LITERAL, NOT A PARAMETER, and the reason is a guard I did
        # not know about: "auto_execute cannot be combined with
        # model-supplied values... an unattended write would let the
        # model choose both whether to write and what to write -- and
        # ontology data reaches the model as text, so that text can be
        # attacker-influenced."
        #
        # My test tried exactly that combination and the validator
        # refused it, which is the guard working on the first person
        # to reach for it.
        literal_only = _action(auto_execute=True, automatable=False)
        literal_only["sub_writes"][0]["mutations"] = [
            {"set": {"property": "name", "value": "a fixed value"}},
        ]
        # AND THE NOW-UNUSED PARAMETER GOES, because another guard
        # catches that too: "parameter(s) ['new_name'] are declared but
        # never referenced". Two refusals in a row, each correct, each
        # teaching something about a file I had not read closely
        # enough.
        del literal_only["parameters"]["new_name"]

        validate_action_types({"A": literal_only}, OBJECT_TYPES)

    def test_neither_implies_the_other(self):
        validate_action_types(
            {"A": _action(auto_execute=False, automatable=True)}, OBJECT_TYPES,
        )


class TestTheRefusalType:
    def test_it_is_not_a_permission_error(self):
        """NOBODY'S GRANTS ARE WRONG. The action itself says it must
        be started by a person, and a PermissionError would send
        somebody auditing roles that are perfectly correct."""
        from core.ontology.write_mediator import NotAutomatable

        assert issubclass(NotAutomatable, ValueError)
        assert not issubclass(NotAutomatable, PermissionError)


class TestOriginKnowsAboutAutomation:
    def test_automation_is_a_third_origin(self):
        """NOT A KIND OF AGENT. An agent is a model reasoning on
        somebody's behalf in a conversation they are having; an
        automation is a condition that fired while everybody was
        asleep. The difference matters most to whoever decides whether
        to approve it."""
        import typing

        from core.ontology.write_mediator import Origin

        assert set(typing.get_args(Origin)) == {"human", "agent", "automation"}
