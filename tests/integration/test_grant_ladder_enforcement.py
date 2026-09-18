"""
The three states, enforced where they are read.

    (no grant)              does not exist, as far as you are concerned
    discover:Customer       the type exists; no search, no ids
    read:Customer           enumerate it, get ids back
    discover:Customer.email the field exists; the value is withheld
    read:Customer.email     the value

THE AGENT AND THE UI ARE DIFFERENT AUDIENCES, and visible_schema's
for_agent flag is the whole of that distinction.

A discover-only type or field is worth showing a PERSON: it says the
deployment holds something they cannot see, which is a fact about their
own access and one they may need to ask about. To the MODEL the schema
is a menu of what it can DO -- a type it cannot search is an item it
can only fail on, costing prompt tokens on every hop and producing
steps the mediator then denies.
"""

import pytest

from core.intermediate_layer.auth import UserRecord


def _role(mediator, name, actions):
    base = dict(mediator.roles["customer_service"])
    mediator.roles = {**mediator.roles, name: {**base, "allowed_actions": frozenset(actions)}}
    return UserRecord(name, "us-west", name)


@pytest.fixture
def granted(mediator):
    return set(mediator.roles["customer_service"]["allowed_actions"])


class TestAFieldOnTheMiddleRung:
    def test_the_ui_sees_the_field_named_but_not_readable(self, mediator, granted):
        user = _role(mediator, "spotter",
                     (granted - {"read:Customer.email"}) | {"discover:Customer.email"})

        fields = mediator.visible_schema(user)["Customer"]["fields"]

        assert "email" in fields
        assert fields["email"]["readable"] is False
        assert fields["name"]["readable"] is True

    def test_the_value_is_withheld(self, mediator, granted):
        # Naming a field must not leak it. The middle rung is about
        # existence, and get_field still requires read:.
        user = _role(mediator, "spotter2",
                     (granted - {"read:Customer.email"}) | {"discover:Customer.email"})

        assert mediator.get_field(user, "Customer", "cust_001", "email") is None
        assert mediator.get_field(user, "Customer", "cust_001", "name") == "Ada Okafor"

    def test_the_agent_does_not_see_it_at_all(self, mediator, granted):
        # A field the model cannot read is one it can only fail on.
        user = _role(mediator, "spotter3",
                     (granted - {"read:Customer.email"}) | {"discover:Customer.email"})

        fields = mediator.visible_schema(user, for_agent=True)["Customer"]["fields"]

        assert "email" not in fields
        assert "name" in fields


class TestATypeOnTheMiddleRung:
    def test_the_ui_sees_the_type_but_marked_unsearchable(self, mediator, granted):
        # THE STATE THAT WAS PREVIOUSLY UNREACHABLE. The weakest grant
        # anyone could write already permitted enumeration, and an id
        # is data.
        user = _role(mediator, "peeker",
                     {a for a in granted if not a.startswith("read:Customer")}
                     | {"discover:Customer"})

        visible = mediator.visible_schema(user)

        assert "Customer" in visible
        assert visible["Customer"]["readable"] is False

    def test_the_agent_does_not_see_it_at_all(self, mediator, granted):
        user = _role(mediator, "peeker2",
                     {a for a in granted if not a.startswith("read:Customer")}
                     | {"discover:Customer"})

        assert "Customer" not in mediator.visible_schema(user, for_agent=True)


class TestTheOrdinaryCase:
    def test_a_read_grant_still_gives_everything(self, mediator):
        # THE CONTROL, and the one that matters most: every existing
        # deployment holds read: grants and nothing else. `read:`
        # implies `discover:`, so nothing about this may change.
        user = UserRecord("alice", "us-west", "customer_service")

        visible = mediator.visible_schema(user)["Customer"]

        assert visible["readable"] is True
        assert all(field["readable"] for field in visible["fields"].values())

    def test_and_the_agent_sees_the_same_thing(self, mediator):
        user = UserRecord("alice", "us-west", "customer_service")

        for_ui = mediator.visible_schema(user)["Customer"]["fields"]
        for_agent = mediator.visible_schema(user, for_agent=True)["Customer"]["fields"]

        assert set(for_ui) == set(for_agent)

    def test_a_type_with_no_grant_at_all_is_invisible_to_both(self, mediator, granted):
        # The bottom rung still works: no grant means it does not exist
        # as far as this caller is concerned, for either audience.
        user = _role(mediator, "blind",
                     {a for a in granted if not a.startswith(("read:Customer", "discover:Customer"))})

        assert "Customer" not in mediator.visible_schema(user)
        assert "Customer" not in mediator.visible_schema(user, for_agent=True)


def test_the_agent_loop_asks_for_the_agent_view(mediator):
    """THE WIRING, which the tests above do not cover.

    They call visible_schema directly, so a loop that forgot
    for_agent=True would pass every one of them -- and the model would
    quietly receive types it cannot search. A control removing the flag
    from agentic_loop.py failed nothing until this existed.
    """
    from core.agent.agentic_loop import AgentLoop

    asked = {}
    original = type(mediator).visible_schema

    def record(self, user_record, *, for_agent=False):
        asked["for_agent"] = for_agent
        return original(self, user_record, for_agent=for_agent)

    type(mediator).visible_schema = record
    try:
        loop = AgentLoop(client=None, mediator=mediator, tools=[], max_hops=1)
        with pytest.raises(Exception):  # noqa: B017 -- no client; the schema call happens first
            loop.run(UserRecord("alice", "us-west", "customer_service"), "anything", None, None)
    finally:
        type(mediator).visible_schema = original

    assert asked.get("for_agent") is True, (
        "AgentLoop must ask for the agent view, or the model receives types "
        "and fields it can only fail on"
    )
