"""
The invariants every authority decision in Elysium must satisfy.

WHY A FILE RATHER THAN A PARAGRAPH. SECURITY_ARCHITECTURE.md said
"once 2 and 3 exist there is something worth specifying, and the
properties above become testable rather than aspirational". They do,
and these are them.

EACH TEST HERE IS UNIVERSAL RATHER THAN PER-SITE. The individual
guards elsewhere pin one mechanism working; these pin that no OTHER
mechanism exists. That distinction is the whole value: a new write
path added next year passes every existing test and fails these.
"""

import inspect

from core.ontology import write_mediator as module


class TestEveryWriteGoesThroughOnePlace:
    def test_no_module_outside_write_mediator_reaches_an_adapter_write(self):
        """THE CHOKEPOINT INVARIANT, and the one the others rest on.

        `write_fields` and `create_object` are the only ways an
        adapter mutates anything, and both are called from
        `write_mediator` alone -- verified across the whole tree.

        A second caller would bypass the pending-write log, the
        approvals queue, the MAC check and the cross-compartment
        check, all at once, while every test of those still passed.
        """
        import pathlib

        offenders = []
        for path in pathlib.Path(".").rglob("*.py"):
            parts = set(path.parts)
            if parts & {"tests", ".venv", "adapters"}:
                continue
            if path.name in ("interface.py", "write_mediator.py"):
                continue
            for number, line in enumerate(
                path.read_text().split("\n"), start=1,
            ):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("*"):
                    continue
                if ".write_fields(" in line or ".create_object(" in line:
                    offenders.append(f"{path}:{number}")

        assert offenders == [], offenders


class TestAuthorityIsNeverStored:
    def test_confirmation_re_authorises_against_the_current_generation(self):
        """RE-EVALUATED AT THE POINT OF USE, never carried.

        A pending write survives a restart and a configuration reload,
        so a decision taken when it was proposed would be a decision
        taken under rules that may no longer exist.
        """
        import api.routes as routes

        source = inspect.getsource(routes)

        assert "_generation(request).config.roles" in source


class TestAttenuationOnly:
    def test_mac_is_checked_against_the_caller(self):
        """NO MECHANISM MAY DO WHAT ITS CALLER COULD NOT. An action
        declares no authority of its own, so there is nothing to
        intersect -- and every write is checked against
        `user_record.security_value`."""
        source = inspect.getsource(module.WriteMediator)

        assert "user_record.security_value" in source

    def test_no_user_record_is_synthesised(self):
        # THE SHAPE THIS FAILS IN: a service account, a scheduled
        # trigger, or an automation "running as the system".
        source = inspect.getsource(module)

        assert [
            line for line in source.split("\n")
            if "UserRecord(" in line
            and "user_record" not in line
            and not line.strip().startswith("#")
        ] == []


class TestDataDoesNotCrossCompartments:
    def test_the_check_compares_two_objects(self):
        """THE \\*-PROPERTY. Every OTHER check compares an object to
        the USER; this one compares what was read to what is being
        written, which is the only way a flow is visible at all."""
        source = inspect.getsource(module._compartment_crossings)

        assert "read_label" in source
        assert "write_label" in source


class TestTheInvariantsAreNamedWhereSomebodyWillLook:
    def test_the_architecture_document_states_them(self):
        """A TEST FILE IS NOT A SPECIFICATION. Somebody reasoning about
        this reads the document; somebody changing it runs the tests.
        Both must say the same thing, and this fails if the document
        stops naming what these check.
        """
        import pathlib

        document = pathlib.Path("SECURITY_ARCHITECTURE.md").read_text()
        # THE SECTION, NOT THE WHOLE FILE. A first version searched
        # everywhere and a control removing the phrase from the
        # algebra section still passed -- the words appear in the
        # prose above it too. What must stay is the SPECIFICATION.
        section = document.split("### 4. The grant algebra")[-1]

        for phrase in ("ATTENUATION ONLY", "CHOKEPOINT",
                       "AUTHORITY IS NEVER STORED", "COMPARTMENTS"):
            assert phrase in section, phrase
