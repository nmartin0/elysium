"""
An action carries no authority its caller lacks.

THE PROPERTY, NAMED: attenuation only. No mechanism may let a request
do something the requesting user could not already do -- anything else
is a confused deputy.

VERIFIED RATHER THAN ASSUMED, and the assumption was wrong in an
interesting direction. SECURITY_ARCHITECTURE.md listed "intersection
for action authority" as work to do, on the premise that an action
"declares at most what it may touch". It declares no authority at all,
so there is no second authority to intersect with -- every write is
already checked against the CALLER's own security value.

WHAT IS DELIBERATE RATHER THAN MISSING: a user needs
`execute:ActionName` and NOT a write grant on the underlying type. An
action IS the capability. Granting "may transfer funds" without
granting "may write Account" is the reason named actions exist, and
Foundry's model is the same.

THIS FILE EXISTS BECAUSE THE PROPERTY IS INCIDENTAL. Nothing declares
it, and a future path that synthesised a UserRecord -- a service
account, a scheduled trigger, an automation running "as the system" --
would break it with no test objecting.
"""

import inspect

from core.ontology import write_mediator as module


class TestEveryWriteChecksTheCaller:
    def test_mac_compares_against_the_user_record(self):
        """THE ONE THING THAT MUST STAY TRUE. A check against anything
        else -- an action's own label, a deployment default, a
        constant -- is a confused deputy however carefully it is
        written."""
        source = inspect.getsource(module.WriteMediator)

        assert "user_record.security_value" in source

    def test_nothing_synthesises_a_user(self):
        """A SYNTHESISED UserRecord IS THE SHAPE this fails in. A
        scheduled trigger or an automation "running as the system"
        would need one, and would carry authority nobody granted.

        Automations are designed to run AS THE OWNER for this reason
        -- see TRIGGERS_AND_PLUGINS.md -- which means passing a real
        user's record, not building one.
        """
        source = inspect.getsource(module)

        constructions = [
            line for line in source.split("\n")
            if "UserRecord(" in line and "user_record" not in line
            and not line.strip().startswith("#")
        ]

        assert constructions == [], constructions


class TestAnActionDeclaresNoAuthority:
    def test_its_declared_keys_carry_none(self):
        """IF AN ACTION COULD DECLARE AUTHORITY, intersection would be
        needed. It cannot, which is why it is not.

        A key added here that grants anything -- `security`,
        `run_as`, `allowed_actions` -- would need the intersection
        this test's absence currently makes unnecessary.
        """
        from core.deployment_loader import build_generation, resolve_runtime_paths

        paths = resolve_runtime_paths()
        generation = build_generation(
            paths.config_dir, paths.data_dir, paths.log_dir,
        )

        for name, action in generation.config.action_types.items():
            granting = {"security", "run_as", "allowed_actions", "authority",
                        "grants", "as_user"} & set(action)
            assert not granting, f"{name} declares authority: {granting}"
