"""
DeploymentGeneration -- step 2b of HOT_RELOAD_PLAN.md.

THE PROPERTY THIS EXISTS FOR: everything derived from one load of the
configuration files moves together or not at all.

Until now they were five separate attributes on app.state, and a route
read app.state.mediator and app.state.config as two independent reads.
Replacing them one at a time gives a window where a request sees a new
mediator and an old config -- schema and grants disagreeing inside one
request, which is an authorization bug rather than a cosmetic one.

Not hypothetical. Step 2a hit it directly: a test replaced config.roles
and the MEDIATOR carried on authorizing against the old grants, because
it holds its own reference. Mutation had only ever "worked" because
config, mediator and write_mediator all held the same dict object.
"""

import dataclasses
from pathlib import Path

import pytest

from core.deployment_loader import DeploymentGeneration, build_generation

DEPLOYMENT = Path(__file__).resolve().parent.parent.parent / "deployment" / "etc"


@pytest.fixture
def generation(tmp_path):
    return build_generation(DEPLOYMENT, data_dir=tmp_path, log_dir=tmp_path / "log")


def test_one_generation_holds_every_configuration_derived_object(generation):
    for name in ("config", "mediator", "write_mediator", "loop", "synthesis_client"):
        assert getattr(generation, name) is not None, f"{name} missing from the generation"


def test_the_objects_inside_agree_with_each_other(generation):
    # THE TORN-READ PROPERTY. The mediator and write_mediator must hold
    # the SAME roles the config does -- not an equal copy, the same
    # object -- or a request using both can see them disagree.
    assert generation.mediator.roles is generation.config.roles
    assert generation.write_mediator.roles is generation.config.roles
    assert generation.write_mediator.mediator is generation.mediator


def test_the_generation_identity_matches_its_config(generation):
    assert generation.generation == generation.config.generation
    assert generation.source_digest == generation.config.source_digest
    assert generation.loaded_at == generation.config.loaded_at


def test_a_generation_cannot_be_mutated(generation):
    # Frozen, because the read path takes NO LOCK: a request reads this
    # reference once and uses it throughout. That is read-copy-update,
    # and it is only sound while the shared object cannot change.
    with pytest.raises(dataclasses.FrozenInstanceError):
        generation.mediator = None


def test_two_builds_are_independent_objects(generation, tmp_path):
    # What a reload does. The new generation must share nothing
    # mutable with the old, or swapping the reference would not
    # actually isolate in-flight requests on the previous one.
    second = build_generation(DEPLOYMENT, data_dir=tmp_path, log_dir=tmp_path / "log")

    assert second.generation != generation.generation
    assert second.mediator is not generation.mediator
    assert second.write_mediator is not generation.write_mediator


def test_mirror_snapshots_is_empty_when_not_reading_from_the_mirror(generation):
    # Nothing to pin when the mirror is not being read. Empty rather
    # than absent, so callers need no special case.
    assert generation.config.read_from_mirror is False
    assert generation.mirror_snapshots == {}


def test_building_does_not_resume_pending_writes(generation, monkeypatch, tmp_path):
    # resume_pending_writes() recovers writes interrupted by a crash and
    # belongs to STARTING UP, not to loading configuration. A reload
    # must not repeat it: the writes it recovers are already recovered,
    # and re-running it against in-flight state is a different
    # operation with different risks.
    called = []
    monkeypatch.setattr(
        type(generation.write_mediator), "resume_pending_writes",
        lambda self: called.append(1) or {"resumed": 0},
    )
    build_generation(DEPLOYMENT, data_dir=tmp_path, log_dir=tmp_path / "log")

    assert called == [], "build_generation() must not resume pending writes"


def test_the_generation_is_what_app_state_is_built_from():
    # Guards the ONE construction path. If app.py ever rebuilds these
    # independently again, the attributes stop being views onto the
    # generation and the torn read comes back.
    source = (Path(__file__).resolve().parent.parent.parent / "api" / "app.py").read_text()

    assert "build_generation(" in source
    assert "AgentLoop.from_deployment(" not in source, "app.py must not build the loop itself"
    assert "WriteMediator(" not in source, "app.py must not build the write mediator itself"


def test_every_field_is_declared(generation):
    # The shape is decided ONCE. Adding a field later means changing
    # every construction site twice, which is why mirror_snapshots is
    # here from the start rather than added at step 5.
    declared = {f.name for f in dataclasses.fields(DeploymentGeneration)}

    assert declared == {
        "generation", "loaded_at", "source_digest",
        "config", "mediator", "write_mediator", "loop", "synthesis_client",
        "write_adapters", "mirror_snapshots",
    }
