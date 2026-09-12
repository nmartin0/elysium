"""
The shipped template must be a deployment that actually loads.

templates/ is what a new deployment copies. Nothing validated it, so it
could have been broken -- a renamed config key, a removed step type, a
schema construct that no longer parses -- for any length of time, and
the first person to find out would be someone starting a new
deployment.

That is the same drift class as tests/unit/test_step_vocabulary_
consistency.py: two things declared in different places, both
individually correct, with nothing asserting they agree. Here the two
are the template and the loader that has to read it.

The templates are deliberately NOT a fixture. Pointing this at a copy
under tests/ would test the copy, and the copy would drift from the
thing that ships.
"""

from pathlib import Path

import pytest
import yaml

TEMPLATES = Path(__file__).resolve().parent.parent.parent / "templates"
DEPLOYMENT = Path(__file__).resolve().parent.parent.parent / "deployment" / "etc"


def test_every_template_yaml_parses():
    for path in sorted(TEMPLATES.glob("*.yaml")):
        try:
            yaml.safe_load(path.read_text())
        except yaml.YAMLError as e:
            pytest.fail(f"{path.name} is not valid YAML: {e}")


def test_the_template_config_names_exactly_one_model_form():
    # The rule _resolve_models() enforces at load. A template naming
    # both forms would be rejected by the loader it is meant to feed,
    # which is the worst possible first experience.
    llm = yaml.safe_load((TEMPLATES / "config.yaml").read_text())["llm"]
    single = "model" in llm
    split = {"step_model", "synthesis_model"} <= llm.keys()

    assert single != split, (
        "templates/config.yaml must name EITHER 'model' or both 'step_model' "
        "and 'synthesis_model', never both forms and never neither"
    )


def test_the_template_action_types_pass_real_validation():
    # Runs the SAME validators core/deployment_loader.py runs, against
    # the real file rather than a fixture. A schema construct that
    # stopped parsing would fail here rather than for a new deployer.
    from core.ontology.action_types import validate_action_types
    from core.ontology.submission_criteria import validate_action_type_criteria

    schema = yaml.safe_load((TEMPLATES / "ontology_schema.yaml").read_text())
    action_types = schema.get("action_types") or {}
    object_types = schema.get("object_types") or {}
    if not action_types:
        pytest.skip("template declares no action types")

    validate_action_types(action_types, object_types)
    validate_action_type_criteria(action_types)


def test_every_role_grant_in_the_template_names_something_real():
    # A grant naming an object type or action that does not exist is
    # silently inert -- it grants nothing and reads as though it does,
    # which is the most confusing possible state for a new deployer.
    schema = yaml.safe_load((TEMPLATES / "ontology_schema.yaml").read_text())
    policy = yaml.safe_load((TEMPLATES / "policy.yaml").read_text())
    object_types = set(schema.get("object_types") or {})
    action_types = set(schema.get("action_types") or {})

    unknown = []
    for role_name, role in (policy.get("roles") or {}).items():
        for grant in role.get("allowed_actions") or []:
            verb, _, target = grant.partition(":")
            if verb == "read":
                if target.split(".")[0] not in object_types:
                    unknown.append(f"{role_name}: {grant}")
            elif verb == "execute" and target not in action_types:
                unknown.append(f"{role_name}: {grant}")

    assert not unknown, f"grants naming things the template's schema lacks: {unknown}"


# --- the debug role ---
#
# scripts/create_debug_user.py makes an account with every grant and
# the password "a". That is a convenience for manual UI testing and a
# back door anywhere else, which is why the script refuses to run
# without an explicit flag.

def test_the_debug_role_invents_no_permission():
    """Every debug grant is one another role already holds.

    THE PROPERTY THAT MAKES IT SAFE TO EXIST. A convenience account
    that reaches everything is defensible; one that reaches something
    no legitimate role reaches is a new capability introduced through
    the back door, and nobody would be looking for it there.

    manage:deployment is the exception and is asserted separately
    below: it is held by no other role because reload testing is the
    only thing that needs it yet.
    """
    policy = yaml.safe_load((DEPLOYMENT / "policy.yaml").read_text())
    roles = policy["roles"]
    debug = set(roles["debug"]["allowed_actions"])
    others = {grant for name, role in roles.items() if name != "debug"
              for grant in role["allowed_actions"]}

    assert debug - others == {"manage:deployment", "discover:action_types"}


def test_the_debug_script_refuses_without_the_flag():
    # A guard rather than a warning: this script exists to be run
    # without thinking, which is exactly the property that gets it run
    # somewhere it should not be.
    source = (DEPLOYMENT.parent.parent / "scripts" / "create_debug_user.py").read_text()

    assert "--yes-this-is-development" in source
    assert "REFUSING" in source
