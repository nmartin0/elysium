"""
Configuration cannot be mutated -- step 2a of HOT_RELOAD_PLAN.md.

TWO HAZARDS, and neither is hypothetical once a configuration is shared
across concurrent requests:

    config.roles["analyst"]["allowed_actions"].add("execute:Transfer")
    config.schema["Account"]["storage"]["table"] = "somewhere_else"

The first invents a grant no policy.yaml contains, no reload produced
and no audit entry records. The second redirects writes to a table the
ontology does not describe, while the write log records the intended
one -- a confirmed write landing elsewhere, with nothing left pending
for recovery to notice.

ENFORCED, NOT CONVENTIONAL, following what this project already does:
import-linter enforces layering on every ./lint.sh, and
require_assertions_enabled() refuses to start rather than trusting an
inspection -- its own history records that the inspection HAD been
wrong once. It is also finishing a job half done: _freeze_roles()
already froze allowed_actions, in the most security-sensitive field
the config has.
"""

from pathlib import Path

import pytest

from core.deployment_loader import load_deployment
from core.immutable import deep_freeze

DEPLOYMENT = Path(__file__).resolve().parent.parent.parent / "deployment" / "etc"


def test_a_field_cannot_be_rebound():
    config = load_deployment(DEPLOYMENT)

    with pytest.raises(Exception, match="cannot assign"):
        config.read_from_mirror = True


def test_a_grant_cannot_be_invented_by_mutating_roles():
    # THE AUTHORIZATION HAZARD. frozen=True alone does NOT stop this --
    # it prevents rebinding the field, not reaching inside it.
    config = load_deployment(DEPLOYMENT)
    role = next(iter(config.roles))

    with pytest.raises(TypeError):
        config.roles[role] = {"allowed_actions": frozenset(["manage:users"])}


def test_a_write_cannot_be_redirected_by_mutating_storage():
    # THE DATA-INTEGRITY HAZARD, and the worse of the two: the write
    # log would record the intended table while the bytes went
    # elsewhere. Four levels deep, which is why the freeze recurses.
    config = load_deployment(DEPLOYMENT)
    object_type = next(iter(config.schema))

    with pytest.raises(TypeError):
        config.schema[object_type]["storage"]["table"] = "somewhere_else"


def test_nested_lists_are_frozen_too():
    # deep_freeze turns lists into tuples, so append() is gone as well
    # as assignment. A grant list that can be appended to is the same
    # hazard as one that can be replaced.
    config = load_deployment(DEPLOYMENT)

    assert isinstance(config.enabled_tools, tuple)


@pytest.mark.parametrize("value,expected", [
    ({"a": 1}, "mappingproxy"),
    ([1, 2], "tuple"),
    ({1, 2}, "frozenset"),
    ("text", "str"),
    (7, "int"),
    (None, "NoneType"),
])
def test_deep_freeze_converts_containers_and_leaves_scalars_alone(value, expected):
    # A value it does not recognise is returned unchanged rather than
    # guessed at.
    assert type(deep_freeze(value)).__name__ == expected


def test_deep_freeze_reaches_arbitrary_depth():
    # The two hazards above are three and four levels deep. Freezing
    # only the top level would stop neither.
    frozen = deep_freeze({"a": {"b": [{"c": {"d": 1}}]}})

    with pytest.raises(TypeError):
        frozen["a"]["b"][0]["c"]["d"] = 2


def test_freezing_an_already_frozen_mapping_is_a_no_op():
    # Idempotent, so a reload that re-freezes an already-frozen
    # structure does not build a proxy around a proxy on every pass.
    once = deep_freeze({"a": 1})

    assert deep_freeze(once) is once
