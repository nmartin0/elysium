"""
A change hint names a type and a verb, and only to someone who may
already know that type exists.

THE TRANSPORT IS NOT BUILT. There is no SSE, no `EventSource`, no
streaming response anywhere in `api/`, and whether live updates are
wanted enough to carry a streaming endpoint is the owner's decision --
BLOCKING.md item 17. This is the half that has to be right BEFORE
that, not invented under deadline after it.

THE DESIGN DECISION, quoted because the wording is the point:

    EVENTS CARRY NO DATA. An event says "something of this kind
    changed", never what changed. The client then refetches through
    the SAME authorised endpoints it already uses, so MAC, roles and
    every permission check apply exactly as they do now.

    The alternative -- pushing the changed object down the stream --
    would put a second, parallel read path beside the mediator, and
    every security rule would have to be re-implemented on it
    correctly, forever.

THAT IS THE INDUSTRY'S ANSWER, not a local preference: "rich payloads
bypass authorization -- data in events is accessible to all
subscribers regardless of permission levels", while "notification
events preserve security -- API calls enforce field-level and row-level
authorization properly". For regulated data the published guidance is
"never in events, API with authorization only"; for consumers with
DIFFERENT authorization levels, "notification + API required".
Elysium authorises per field and per row, so it is squarely that case.

AND THE USUAL CRITICISM DOES NOT APPLY. Thin events are faulted
because "a consumer that receives an ID and immediately asks you for
the record has not been decoupled from you". Here the refetch IS the
point -- it is where authorization happens. The cost everyone else
complains about is the security property.

THE FILTER DEFERS RATHER THAN DECIDING. `visible_schema` already
answers "which types may this caller know exist", including a type
"whenever discover:{type} is granted". My first version imported
`authorize` and tested `discover:` itself -- correct on the day, and
one ladder change away from drifting. A second place deciding one
security question is what the published-history route refused to be.
"""

import pytest

from core.change_hints import CHANGE_KINDS, describe_hint, hints_for


class TestOnlyTypesTheCallerMayKnowOf:
    def test_a_type_outside_the_visible_schema_is_dropped(self):
        """Telling someone with no grant on Customer that "a Customer
        changed" tells them the deployment HAS customers and that
        somebody is editing them."""
        visible = {"Order": {}}

        assert hints_for(visible, ["Customer", "Order"]) == ["Order"]

    def test_an_empty_visible_schema_yields_nothing(self):
        assert hints_for({}, ["Customer"]) == []
        assert hints_for(None, ["Customer"]) == []

    def test_nothing_changed_yields_nothing(self):
        assert hints_for({"Customer": {}}, []) == []
        assert hints_for({"Customer": {}}, None) == []

    def test_duplicates_collapse(self):
        """A type that changed twice in one window is still one hint --
        a count is a measurement of data the caller may not read."""
        visible = {"Customer": {}}

        assert hints_for(visible, ["Customer", "Customer"]) == ["Customer"]

    def test_the_input_order_is_kept(self):
        """Not sorted. A stable ordering across recipients is one more
        thing two colleagues could compare."""
        visible = {"A": {}, "B": {}}

        assert hints_for(visible, ["B", "A"]) == ["B", "A"]


class TestItDecidesNothingItself:
    def test_it_takes_a_visible_schema_rather_than_a_user(self):
        """The regression test for the design. A signature taking a
        user record and roles would mean this module deciding the
        question `visible_schema` already answers."""
        import inspect

        parameters = list(inspect.signature(hints_for).parameters)

        assert parameters == ["visible_schema", "changed_types"]

    def test_the_module_imports_nothing_from_core(self):
        """A leaf. Importing `authorize` is exactly how the second
        opinion creeps back in."""
        from pathlib import Path

        source = Path("core/change_hints.py").read_text()
        imports = [line for line in source.splitlines()
                   if line.startswith(("import ", "from "))]

        assert not [line for line in imports if "core." in line], imports


class TestWhatAHintMayCarry:
    @pytest.mark.parametrize("kind", CHANGE_KINDS)
    def test_a_type_and_a_verb(self, kind):
        assert describe_hint("Customer", kind) == {
            "object_type": "Customer", "change": kind}

    def test_nothing_else_is_in_the_payload(self):
        """No id, no field, no count, no timestamp. Each is a fact
        about data the recipient may not be able to read."""
        hint = describe_hint("Customer", "updated")

        assert set(hint) == {"object_type", "change"}

    def test_an_invented_verb_is_refused(self):
        with pytest.raises(ValueError, match="a hint may say"):
            describe_hint("Customer", "4 rows changed")

    def test_the_refusal_says_why(self):
        """A count is the tempting one: "4 Customers changed" looks
        harmless and maps the size and rhythm of a compartment somebody
        cannot see."""
        with pytest.raises(ValueError, match="may not be allowed to read"):
            describe_hint("Customer", "counted")


class TestWhatIsHonestlyNotBuilt:
    def test_there_is_still_no_streaming_endpoint(self):
        """This module is the security half of a feature whose
        transport is not built and may never be. If live updates are
        declined, DELETE IT rather than leave it looking load-bearing
        -- the whitelist entry says so too."""
        from pathlib import Path

        api = "\n".join(path.read_text()
                        for path in Path("api").rglob("*.py"))

        assert "EventSource" not in api
        assert "text/event-stream" not in api
