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
import dataclasses
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
             temperature=None, *, deadline=None, usage=None, cancel=None):
        self.seen += 1
        if self._unusable > 0:
            self._unusable -= 1
            return "not json at all"
        for case in CASES:
            if case.query not in user_message:
                continue
            # EVERY expected fact, not just the first. link_fanout
            # needs two reads, and a stand-in that answers one of them
            # would let a case pass here that a real model would fail.
            for fact in case.expected_facts:
                already = (f'"object_id": "{fact.object_id}"' in user_message
                           and f'"field_name": "{fact.field_name}"' in user_message)
                if not already:
                    return (
                        f'{{"step": "get_field", '
                        f'"object_type": "{fact.object_type}", '
                        f'"object_id": "{fact.object_id}", '
                        f'"field_name": "{fact.field_name}"}}'
                    )
            # AND EVERY EXPECTED AGGREGATE, as the one step a correct
            # model would take. This is also the proof that the case is
            # REACHABLE: the step goes through the real loop's own
            # validation, so a case asking for an aggregate the loop
            # would refuse fails here rather than on somebody's GPU.
            for expected in case.expected_aggregates:
                if '"step": "aggregate_object"' not in user_message:
                    return (
                        f'{{"step": "aggregate_object", '
                        f'"object_type": "{expected.object_type}", '
                        f'"aggregate": "{expected.aggregate}", '
                        f'"filter": {{"customer_id": "{expected.filter_mentions}"}}}}'
                    )
            return '{"step": "finish"}'
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
                 temperature=None, *, deadline=None, usage=None, cancel=None):
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


def test_the_plan_can_be_shown(generation_and_user, caplog):
    """WITHOUT THIS, A PLAN-MODE RUN CANNOT BE JUDGED.

    The first plan-mode run came back correct, in one call, 64% faster
    than the loop -- and said nothing about whether the planner USED A
    HANDLE. That is the entire security property. A plan of
    `search_object(name=...)` then `get_field($a, email)` names a
    result the planner never saw; a plan that wrote `cust_001`
    directly would be the same speed and the same answer and would
    prove nothing -- it would mean the model guessed an id, which is
    worse than the behaviour it replaced.
    """
    import logging

    from scripts.llm_bench import _show_plans

    _show_plans()
    plan_logger = logging.getLogger("core.llm.agent_step_prompt")

    assert plan_logger.level == logging.DEBUG
    # Turned up on that ONE logger, not the root, or the output is
    # unreadable and nobody looks at it.
    assert logging.getLogger().level != logging.DEBUG


def test_the_warm_up_uses_the_real_system_prompt(generation_and_user):
    """WARMING THE MODEL AND WARMING THE PREFIX ARE DIFFERENT THINGS.

    The diagnostic measured model load at 3.7 seconds and prompt
    evaluation at 591.1s for 5,675 characters. A tiny warm-up call
    would load the model and cache nothing that matters, leaving the
    first real call to pay full price -- which is how a
    dependent_choice run lost its revision attempt to a 600s timeout.

    I wrote the tiny version first. This asserts the size, because
    that is the difference between warming and pretending to.
    """
    import inspect

    from scripts.llm_bench import run

    source = inspect.getsource(run)

    assert "_build_system_prompt(" in source, "warms something other than the prompt"
    assert "PLAN_INSTRUCTIONS" in source, "plan mode's prefix differs and must match"

    # AND IT MUST HAPPEN BEFORE THE TIMER IS INSTALLED, or the warm-up
    # appears in the timing table as call 1 and every prefix-reuse
    # number in the report is measured against it.
    #
    # An earlier version of this test looked for a phrase from the
    # comment instead, and failed because the phrase wrapped across
    # two comment lines. Asserting on prose is asserting on
    # formatting; this asserts on order.
    assert source.index("warm_system") < source.index("timer = Timed(")


def test_the_warm_up_matches_the_mode(generation_and_user):
    """PLAN MODE'S PREFIX IS NOT THE STEP PREFIX. It drops the
    untrusted-data framing and appends the plan instructions, so
    warming the step prompt would cache a prefix the plan calls never
    use -- all of the cost, none of the benefit."""
    from core.llm.agent_step_prompt import PLAN_INSTRUCTIONS, _build_system_prompt

    schema = {"Customer": {"id_field": "customer_id",
                           "fields": {"name": {"type": "data"}}}}
    step = _build_system_prompt(schema, [], False, {}, data_is_shown=True)
    plan = _build_system_prompt(
        schema, [], False, {}, data_is_shown=False
    ) + PLAN_INSTRUCTIONS

    assert step != plan
    assert not plan.startswith(step), "the prefixes genuinely differ"


def test_a_slow_call_is_flagged_rather_than_killed():
    """A BENCH MEASURES; A DEPLOYMENT ENFORCES. I had this backwards.

    I wrote "the trials keep the deployment's own limit, so nothing
    measured runs under a limit the deployment would not use". That
    sounded principled and produced NO DATA: run after run died at
    600s with nothing to report, including the revision attempt that
    was the whole point of one of them.

    The variance is the reason. Identical prompts have been measured
    at 52.2s and 459.4s -- 8.8x -- so a 600s limit kills the tail of a
    distribution whose median is about 150s, at random, and a killed
    trial measures nothing.

    So every call's duration is reported and the ones a deployment
    would have cut off are MARKED. Anyone can apply any limit after
    the fact; enforcing one during the run throws the number away.
    """
    import contextlib
    import io

    from core.agent.evaluation import TrialResult
    from scripts.llm_bench import _report

    class Calls:
        calls = [(6000, 120.0), (6000, 700.0)]

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _report([TrialResult(case_name="c", passed=True)], Calls(),
                partial=False, deployment_limit=600)
    out = buffer.getvalue()

    assert "over the deployment's limit" in out, "the slow call is not marked"
    assert "1 of 2 calls exceeded" in out, "no count of what would have failed"
    assert "700.00" in out, "the number itself was thrown away"


def test_the_warm_up_is_exempt_from_the_deployment_timeout(generation_and_user):
    """A CALL WHOSE JOB IS TO BE SLOW SHOULD NOT BE KILLED FOR IT.

    The warm-up timed out at 600s on its first outing -- arithmetic,
    not a fault: 6,154 characters at the measured 0.104 s/char is
    about 640 seconds. The deployment's timeout is below the cost of
    its own cold call.

    Raising the deployment's timeout would be the chasing I stopped
    doing. This call is not a query: its entire job is to absorb the
    cold cost so the trials afterwards are warm.
    """
    import inspect

    from scripts.llm_bench import WARM_UP_TIMEOUT_SECONDS, run

    assert WARM_UP_TIMEOUT_SECONDS >= 1200, "too short to absorb a cold call"

    source = inspect.getsource(run)
    assert "adapter.timeout_seconds = WARM_UP_TIMEOUT_SECONDS" in source


def test_the_generous_timeout_is_not_restored_and_that_is_deliberate():
    """THIS TEST USED TO ASSERT THE OPPOSITE.

    It checked that the real timeout was restored in a `finally`
    after the warm-up, so trials ran under the deployment's limit.
    That was the design, and the design was wrong: it produced no
    data, run after run.

    Now the generous timeout stays for the trials too, and the report
    marks any call the deployment would have cut off. The old test
    asserted the behaviour that was throwing the measurements away,
    which is why it is replaced rather than deleted quietly.
    """
    import inspect

    from scripts.llm_bench import run

    source = inspect.getsource(run)

    assert "adapter.timeout_seconds = real_timeout" not in source, (
        "the trials are back under a limit that kills them at random"
    )
    assert "deployment_limit=real_timeout" in source, (
        "the real limit must still be REPORTED, just not enforced"
    )


class _Reporting:
    """Scripted steps, each reporting what a provider would."""

    max_concurrent_requests = 1

    def __init__(self, wrapped):
        self._script = wrapped

    def chat(self, system_prompt, user_message, json_mode=False, temperature=None, *,
             deadline=None, usage=None, cancel=None):
        if usage is not None:
            usage.add(100, 12, seconds=0.02, reading_seconds=0.005, writing_seconds=0.015)
        return self._script.chat(system_prompt, user_message, json_mode, temperature)


class _Answering:
    max_concurrent_requests = 1

    def __init__(self):
        self.asked = 0

    def chat(self, system_prompt, user_message, json_mode=False, temperature=None, *,
             deadline=None, usage=None, cancel=None):
        self.asked += 1
        if usage is not None:
            usage.add(300, 40, seconds=0.05, writing_seconds=0.04)
        return "Ada Okafor's email address is ada.okafor@example.com [R1]."


def _bench(monkeypatch, synced_deployment, **options):
    """scripts/llm_bench.run(), end to end, on scripted models."""
    import scripts.llm_bench as bench

    generation = build_generation(synced_deployment.config_dir, synced_deployment.data_dir,
                                  synced_deployment.log_dir)
    generation.loop.client = _Reporting(Scripted())
    answering = _Answering()
    generation = dataclasses.replace(generation, synthesis_client=answering)
    monkeypatch.setattr(bench, "build_generation", lambda *a: generation)
    timings: list = []
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        status = bench.run(synced_deployment, 1, (CASES[0],), timings=timings, **options)
    return status, timings, answering, out.getvalue()


def test_a_trial_is_a_whole_question_answer_included(monkeypatch, synced_deployment):
    """THE ANSWER WAS NEVER TIMED (19 October): the bench ran the loop and
    stopped, though the answer is prose with no length limit."""
    status, timings, answering, out = _bench(monkeypatch, synced_deployment)

    assert status == 0 and answering.asked == 1
    ((name, usage, seconds),) = timings
    assert name == "one_field" and seconds > 0
    parts = [record.part for record in usage.records]
    assert parts[-1] == "answer" and set(parts[:-1]) == {"step"}
    # AND SAID, per trial, where a person running it on the VM reads it.
    assert "answer 1 call" in out and "step " in out


def test_the_answer_can_be_left_out(monkeypatch, synced_deployment):
    status, timings, answering, _ = _bench(monkeypatch, synced_deployment, answer=False)

    assert answering.asked == 0
    assert "answer" not in {record.part for record in timings[0][1].records}


def test_another_model_through_every_wrapper():
    from adapters.ollama_adapter import OllamaAdapter
    from core.llm.concurrency_limited_adapter import ConcurrencyLimitedLLMAdapter
    from core.llm.retrying_adapter import RetryingLLMAdapter
    from scripts.llm_bench import use_model

    inner = OllamaAdapter("phi4-mini", {"base_url": "http://ollama.invalid/api/chat"})
    use_model(ConcurrencyLimitedLLMAdapter(RetryingLLMAdapter(inner)), "qwen3:4b")

    assert inner.model == "qwen3:4b"
