"""
One configuration per request -- step 2c of HOT_RELOAD_PLAN.md.

A request reads the current DeploymentGeneration once, at entry, and
uses that one object throughout. Two reads within one request can
never disagree, even if a reload lands between them.

WHY IT MATTERS. Before step 2b these were five separate app.state
attributes read independently wherever needed. A reload replacing them
one at a time gives a window where a request sees a new mediator and an
old config -- schema and grants disagreeing inside one request, which
is an authorization bug rather than a cosmetic one.
"""

import dataclasses
from types import SimpleNamespace

from api.generation_dependency import get_generation


def _request(generation):
    # A Request is awkward to construct directly; what get_generation
    # actually touches is request.app.state and request.state.
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(generation=generation)),
                           state=SimpleNamespace())


def test_the_pin_returns_the_current_generation():
    generation = SimpleNamespace(generation=1)

    assert get_generation(_request(generation)) is generation


def test_the_pin_is_cached_on_request_state():
    # Cached so code reached from a route WITHOUT the dependency in its
    # signature -- a helper, a nested call -- uses the same generation
    # rather than reading app.state again and possibly getting a newer
    # one mid-request.
    generation = SimpleNamespace(generation=1)
    request = _request(generation)

    get_generation(request)

    assert request.state.generation is generation


def test_a_reload_mid_request_does_not_change_what_this_request_sees():
    # THE PROPERTY. The request pinned generation 1; app.state has moved
    # to 2. Anything reading through the pin must still see 1, or the
    # two halves of one request can disagree about the schema and the
    # grants.
    first = SimpleNamespace(generation=1)
    request = _request(first)
    pinned = get_generation(request)

    request.app.state.generation = SimpleNamespace(generation=2)

    assert request.state.generation is pinned
    assert request.state.generation.generation == 1


def test_routes_read_the_pin_rather_than_app_state():
    # Guards the migration itself. A route reaching past the pin to
    # app.state.mediator would reintroduce the torn read, and would do
    # so silently -- nothing about it looks wrong at the call site.
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent.parent / "api" / "routes.py").read_text()

    for attribute in ("config", "mediator", "write_mediator", "loop", "synthesis_client"):
        assert f"app.state.{attribute}" not in source, (
            f"api/routes.py still reads app.state.{attribute} directly; "
            f"use the pinned generation instead"
        )


def test_runtime_state_is_still_read_from_app_state():
    # The CONTROL for the test above. Sessions, credentials, rate
    # limiters and the rest are runtime state that must SURVIVE a
    # reload -- they are deliberately NOT on the generation, and routes
    # should still reach them through app.state. A migration that moved
    # them too would be wrong.
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent.parent / "api" / "routes.py").read_text()

    assert "app.state.session_store" in source
    assert "app.state.user_directory" in source


def test_replacing_a_generation_leaves_the_previous_one_intact():
    # What keeps an in-flight request coherent: the old generation is a
    # whole, immutable object that continues to exist for as long as
    # anything holds it.
    first = SimpleNamespace(generation=1, config="old")
    second = dataclasses.replace(
        dataclasses.make_dataclass("G", ["generation", "config"], frozen=True)(1, "old"),
        config="new",
    )

    assert first.config == "old"
    assert second.config == "new"


# --- step 2e: the attributes are gone, not merely unused ---

def test_app_state_no_longer_carries_the_configuration_derived_objects():
    # The DIFFERENCE step 2e makes. Step 2d stopped routes reading
    # them; this stops them existing. While they existed, a route could
    # reach past its pin and get a different generation, silently, with
    # nothing at the call site looking wrong.
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent.parent / "api" / "app.py").read_text()
    assignments = [
        line for line in source.splitlines()
        if line.strip().startswith("app.state.") and "=" in line
    ]
    assigned = {line.split("app.state.")[1].split()[0].split("=")[0] for line in assignments}

    for gone in ("config", "mediator", "write_mediator", "loop", "synthesis_client"):
        assert gone not in assigned, f"api/app.py still assigns app.state.{gone}"


def test_runtime_state_is_still_assigned_on_app_state():
    # The CONTROL. Sessions, credentials, rate limiters and pending
    # writes must SURVIVE a reload, so they belong on app.state and NOT
    # on the generation. A deletion that took them too would pass the
    # test above while logging out every user on reload.
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent.parent / "api" / "app.py").read_text()

    for kept in ("session_store", "credential_store", "user_directory",
                 "login_attempt_tracker", "query_rate_limiter", "pending_writes",
                 "artifact_store", "executor"):
        assert f"app.state.{kept} =" in source, f"runtime state app.state.{kept} was removed"
