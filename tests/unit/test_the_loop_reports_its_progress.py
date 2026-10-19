"""The agent loop tells a waiting person what it has done, between steps
(19 October) -- through a hook that can neither change the question nor
stop it."""

import contextlib
import io

from core.deployment_loader import build_generation
from core.intermediate_layer.auth import resolve_user_record
from scripts.llm_bench import CASES, USER_ID
from tests.unit.test_llm_bench import Scripted

LINK_FANOUT = next(case for case in CASES if case.name == "link_fanout")


def _loop(synced_deployment):
    generation = build_generation(synced_deployment.config_dir, synced_deployment.data_dir,
                                  synced_deployment.log_dir)
    generation.loop.client = Scripted()
    user = resolve_user_record(generation.config.users, USER_ID, generation.config.security_attribute)
    return generation.loop, user


def test_told_after_each_step_before_the_next_call(synced_deployment):
    loop, user = _loop(synced_deployment)
    told = []

    with contextlib.redirect_stdout(io.StringIO()):
        result = loop.run(user, LINK_FANOUT.query, progress=lambda gathered: told.append(len(gathered)))

    # Two reads, so told twice: after the first, and after the second --
    # each before the model was asked for what came next.
    assert told == [1, 2]
    assert len(result.gathered) == 2


def test_what_it_is_given_is_a_copy(synced_deployment):
    loop, user = _loop(synced_deployment)

    with contextlib.redirect_stdout(io.StringIO()):
        result = loop.run(user, LINK_FANOUT.query, progress=lambda gathered: gathered.clear())

    assert len(result.gathered) == 2


def test_a_failing_hook_does_not_stop_the_question(synced_deployment):
    loop, user = _loop(synced_deployment)

    def broken(gathered):
        raise RuntimeError("the page went away")

    with contextlib.redirect_stdout(io.StringIO()):
        result = loop.run(user, LINK_FANOUT.query, progress=broken)

    assert len(result.gathered) == 2 and not result.possibly_incomplete
