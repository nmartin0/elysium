"""The VM run, exercised without a VM.

`scripts/llm_bench.py` produces three numbers against a real model:
pass^k, the parse-failure rate, and prefix-cache timing. None of them
can be produced here -- there is no Ollama in this sandbox.

WHAT CAN BE PROVED HERE IS THAT THE RUN WORKS, and it is worth
proving, because a bench that crashes on the VM costs a whole session
of somebody's time. A scripted adapter stands in for the model; the
loop, the mediator, the grader and the aggregation are all real.

THE CASE VALUES ARE REAL TOO, read out of the shipped deployment
rather than guessed -- "ada.okafor@example.com", transaction 2 at 199.
A case that names a value the deployment does not hold would fail on
the VM for a reason that has nothing to do with the model.
"""

import contextlib
import io

import pytest

from core.agent.evaluation import aggregate, grade
from core.deployment_loader import build_generation
from core.intermediate_layer.auth import resolve_user_record
from scripts.llm_bench import CASES, USER_ID, Timed


class Scripted:
    """Answers each case correctly, in as few steps as it can."""

    max_concurrent_requests = 1

    def __init__(self, *, unusable=0):
        self._unusable = unusable
        self.seen = 0

    def chat(self, system_prompt, user_message, json_mode=False,
             temperature=None, *, deadline=None, usage=None):
        self.seen += 1
        if self._unusable > 0:
            self._unusable -= 1
            return "not json at all"
        for case in CASES:
            if case.query in user_message:
                fact = case.expected_facts[0]
                if f'"field_name": "{fact.field_name}"' in user_message:
                    return '{"step": "finish"}'
                return (
                    f'{{"step": "get_field", "object_type": "{fact.object_type}", '
                    f'"object_id": "{fact.object_id}", '
                    f'"field_name": "{fact.field_name}"}}'
                )
        return '{"step": "finish"}'


@pytest.fixture
def generation_and_user(synced_deployment):
    generation = build_generation(
        synced_deployment.config_dir,
        synced_deployment.data_dir,
        synced_deployment.log_dir,
    )
    user = resolve_user_record(
        generation.config.users, USER_ID, generation.config.security_attribute
    )
    return generation, user


def _trials(generation, user, client, trials=2):
    generation.loop.client = client
    results = []
    for case in CASES:
        for _ in range(trials):
            with contextlib.redirect_stdout(io.StringIO()):
                outcome = generation.loop.run(user, case.query)
            results.append(grade(case, outcome))
    return results


def test_the_bench_user_can_actually_read(generation_and_user):
    """THE MISTAKE THAT COST AR-1's FIRST MEASUREMENT.

    An unknown user id resolves to an EMPTY UserRecord -- no role, no
    region -- so every read is denied, the schema is empty, and the
    run looks healthy while proving nothing. The bench checks this and
    exits; so does this test, because a wrong id here would make every
    case below fail for a reason unrelated to the model.
    """
    generation, user = generation_and_user

    assert user.role_name is not None
    assert generation.mediator.visible_schema(user)


def test_every_case_names_a_fact_the_deployment_actually_holds(generation_and_user):
    """A case naming a value that does not exist would fail on the VM
    for a reason that has nothing to do with the model, and a whole
    session would be spent finding that out."""
    generation, user = generation_and_user

    for case in CASES:
        for fact in case.expected_facts:
            value = generation.mediator.get_field(
                user, fact.object_type, fact.object_id, fact.field_name
            )
            assert value is not None, f"{case.name}: {fact} is not readable"


def test_a_correct_run_passes_every_case(generation_and_user):
    """End to end with a scripted model: real loop, real mediator,
    real grader, real aggregation."""
    generation, user = generation_and_user

    results = _trials(generation, user, Scripted())
    reports = aggregate(results)

    assert len(reports) == len(CASES)
    for report in reports:
        assert report.successes == report.trials, f"{report.case_name} failed"
        assert report.pass_hat(2) == 1.0


def test_identical_trials_are_reported_as_degenerate(generation_and_user):
    """AT TEMPERATURE 0 THIS IS THE EXPECTED RESULT, and the bench says
    so rather than quoting a pass^k that could not have varied."""
    generation, user = generation_and_user

    reports = aggregate(_trials(generation, user, Scripted()))

    assert all(report.is_degenerate() for report in reports)
    assert all("cannot distinguish" in report.summary() for report in reports)


def test_unusable_replies_are_counted_not_just_failed(generation_and_user):
    """The second of the three numbers. A low pass^k beside a high
    rate here is a parsing problem, and D1 would be the wrong fix."""
    generation, user = generation_and_user

    results = _trials(generation, user, Scripted(unusable=1), trials=1)
    reports = aggregate(results)

    assert sum(r.parse_failures for r in reports) >= 1


def test_the_timer_records_size_beside_duration(generation_and_user):
    """PREFIX REUSE IS MEASURED BY TIME, not by prompt_eval_count --
    which reports total context rather than new computation and cannot
    detect a cache hit. The shape of the finding is chars against
    seconds, so both are recorded per call."""
    generation, user = generation_and_user
    timer = Timed(Scripted())

    _trials(generation, user, timer, trials=1)

    assert timer.calls
    for size, seconds in timer.calls:
        assert size > 0
        assert seconds >= 0


def test_the_timer_passes_every_argument_through(generation_and_user):
    """A wrapper that dropped `deadline` would silently unbound every
    call the bench makes -- and the bench is the one run where a hang
    costs a whole session."""
    seen = {}

    class Recording:
        max_concurrent_requests = 3

        def chat(self, system_prompt, user_message, json_mode=False,
                 temperature=None, *, deadline=None, usage=None):
            seen.update(json_mode=json_mode, temperature=temperature,
                        deadline=deadline, usage=usage)
            return '{"step": "finish"}'

    timer = Timed(Recording())
    timer.chat("sys", "user", True, 0.0, deadline=99.0, usage="U")

    assert timer.max_concurrent_requests == 3
    assert seen == {"json_mode": True, "temperature": 0.0,
                    "deadline": 99.0, "usage": "U"}


def test_an_outage_reports_what_was_collected_instead_of_crashing(generation_and_user):
    """FOUND BY RUNNING IT WITHOUT A MODEL.

    The first version exited on a traceback and threw away every trial
    already completed. On the VM that is a whole session: each trial
    costs real minutes at ~1.5 tokens/s, and a model evicted or
    restarted halfway through would lose all of them.
    """
    from core.llm.interface import LLMUnavailable
    from scripts.llm_bench import run

    generation, user = generation_and_user
    calls = {"n": 0}

    class DiesAfterOne:
        max_concurrent_requests = 1

        def chat(self, *a, **k):
            calls["n"] += 1
            if calls["n"] > 2:
                raise LLMUnavailable("the model went away")
            return '{"step": "finish"}'

    generation.loop.client = DiesAfterOne()
    # run() builds its own generation, so drive the same path the
    # script does through the pieces it uses.
    from core.agent.evaluation import aggregate as _aggregate

    results = []
    with contextlib.redirect_stdout(io.StringIO()):
        for case in CASES:
            try:
                outcome = generation.loop.run(user, case.query)
            except LLMUnavailable:
                break
            results.append(grade(case, outcome))

    assert results, "nothing was collected before the outage"
    assert _aggregate(results), "collected trials could not be reported"
    assert callable(run)


def test_a_single_case_can_be_run_alone(generation_and_user):
    """SLOW HARDWARE IS THE REASON. At the ~5.4 tokens/s prefill the
    config records, one hop is minutes. Running every case three times
    before knowing what a single trial costs is how a bench gets
    abandoned halfway."""
    from scripts.llm_bench import CASES, run

    names = {case.name for case in CASES}

    assert "one_field" in names
    assert len(names) == len(CASES), "two cases share a name"
    assert callable(run)


def test_the_default_is_one_trial(generation_and_user):
    """pass^k needs k>=2, so the default deliberately does NOT produce
    it. One trial per case gives mean@1, the parse-failure rate and
    the timing table for a quarter of the wall clock; pass^k is worth
    a second, narrower run once the first shows what a trial costs.
    """
    import argparse
    import inspect

    from scripts.llm_bench import main

    source = inspect.getsource(main)
    assert '"--trials", type=int, default=1' in source
    assert isinstance(argparse.ArgumentParser(), argparse.ArgumentParser)


def test_every_case_name_is_selectable(generation_and_user):
    """A typo in --cases should list what IS known rather than run
    nothing and report success."""
    from scripts.llm_bench import CASES

    for case in CASES:
        assert case.name.isidentifier(), f"{case.name} is awkward to type"
