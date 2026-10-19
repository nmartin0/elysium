#!/usr/bin/env python3
"""
llm_bench.py  (the VM run: reliability, parse failures, prefix reuse)

Three numbers, one session, against a real model on real data. Each
answers a question that is currently open and cannot be answered
without a model.

  pass^k              Is the agent right EVERY time, or just on
                      average? AL-8/R59. tau-bench introduced the
                      metric for exactly this case: "for real-world
                      agent tasks requiring reliability and
                      consistency", the question is whether ALL k
                      trials succeeded. An analyst asking the same
                      question twice and getting two answers has been
                      failed once, whatever the average says.

  parse failures      How often does next_step() fail closed on an
                      unusable reply? A published CPU tool-calling
                      benchmark found that adding a fallback parser
                      moved one model from 0.670 to 0.960 and moved
                      another DOWN from 0.880 to 0.780 -- a bigger
                      swing than any model swap in its table. A low
                      pass^k beside a high rate here is a PARSING
                      problem wearing a model problem's clothes, and
                      D1 would be the wrong fix.

  prefix reuse        AR-1's engine half. The structure is confirmed
                      -- 97.4%-97.7% of each hop's prompt is an exact
                      prefix of the previous one -- but whether
                      llama.cpp under Ollama actually SKIPS re-reading
                      it is a property of the server, not of us.

== READ THIS BEFORE TRUSTING ANY CACHE NUMBER ==

**SINCE 19 OCTOBER, READ prompt_eval_cached_count INSTEAD**: Ollama
now documents it as "how many prompt tokens were read from the cache",
and each trial's line reports it with reading and writing time. What
follows was true of the field the bench had, and is kept for that.

**IGNORE prompt_eval_count.** Ollama's own documented behaviour: it
"does not currently return an accurate count of just the tokens
processed in a request when using caching"; the field "reports the
Total Context Size of the request you sent, not the number of new
calculations the GPU performed". A worked example shows 723 on both a
cold and a warm request. It CANNOT detect a cache hit, and it is
exactly what someone would reach for.

So prefix reuse is measured by TIME. Hop 1 pays for the whole prompt;
later hops send a LONGER prompt that shares ~97% of it. If later hops
are not slower despite being longer, the shared part is not being
re-read.

**keep_alive matters and is already set.** The five-minute default
eviction dumps the KV cache; config.yaml sets keep_alive: -1 with
that reasoning. If a run shows no reuse, check that first.

== WHY THE CASES LOOK LIKE THIS ==

Graded on FACTS, not prose (see core/agent/evaluation.py). A grader
reading the synthesised answer needs a judge model or a regex over
English, and both are less trustworthy than the thing they grade. The
loop records what it read, so a case names the facts a correct run
must have gathered and grading is a subset check over data the
mediator itself returned.

Values below are the shipped deployment's real ones, read out of it
rather than guessed.
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.agent.evaluation import (  # noqa: E402
    DEFAULT_K,
    EvalCase,
    ExpectedAggregate,
    ExpectedFact,
    ExpectedMemory,
    aggregate,
    answer_states,
    grade,
)
from core.deployment_loader import (  # noqa: E402
    RuntimePaths,
    build_generation,
    resolve_runtime_paths,
)
from core.intermediate_layer.auth import resolve_user_record  # noqa: E402
from core.llm.agent_features import AgentFeatures  # noqa: E402
from core.llm.agent_step_prompt import (  # noqa: E402
    PLAN_INSTRUCTIONS,
    _build_system_prompt,
)
from core.llm.interface import LLMUnavailable  # noqa: E402
from core.request_context import RequestContext  # noqa: E402

USER_ID = "user_alice"

# Long enough that a cold call reports rather than dies. Not a
# deployment setting and never applied to a trial -- see the warm-up.
WARM_UP_TIMEOUT_SECONDS = 1800

CASES = (
    EvalCase(
        name="one_field",
        query="What is Ada Okafor's email address?",
        user_id=USER_ID,
        expected_facts=(
            ExpectedFact("Customer", "cust_001", "email", "ada.okafor@example.com"),
        ),
    ),
    EvalCase(
        name="one_field_other_customer",
        query="Which region is Bram Feldman in?",
        user_id=USER_ID,
        expected_facts=(
            ExpectedFact("Customer", "cust_002", "region", "us-west"),
        ),
    ),
    EvalCase(
        name="typed_field",
        query="How much was transaction 2?",
        user_id=USER_ID,
        # RENDERED, not stored: the mediator returns
        # Decimal("199.000000000") and the model is shown "199".
        # Grading goes through the same renderer the prompt does, so a
        # case cannot pass here and fail there.
        expected_facts=(
            ExpectedFact("Transaction", "2", "amount", "199"),
        ),
    ),
    EvalCase(
        # RENAMED FROM two_hops, WHICH IT NEVER WAS. The plan it
        # actually produced was a search with TWO FILTERS and one
        # read -- two constraints, not two hops. It is a real case and
        # worth keeping; the name was just wrong, and a case set that
        # lies about what it covers is worse than a smaller one.
        name="two_constraints",
        query="What is the email address of the customer in the us-west region "
              "whose name is Ada Okafor?",
        user_id=USER_ID,
        expected_facts=(
            ExpectedFact("Customer", "cust_001", "email", "ada.okafor@example.com"),
        ),
    ),
    EvalCase(
        # THE CASE THE SET WAS MISSING, and the gap only became visible
        # once --show-plan printed what the model wrote: every plan so
        # far resolved its handle to a SINGLE id, so the fan-out path
        # and the MAX_PLAN_FANOUT refusal have never run against a
        # real model. cust_001 has exactly two transactions, so a
        # correct plan must traverse the link and read BOTH.
        name="link_fanout",
        query="What are the amounts of all of Ada Okafor's transactions?",
        user_id=USER_ID,
        expected_facts=(
            ExpectedFact("Transaction", "1", "amount", "49.99"),
            ExpectedFact("Transaction", "2", "amount", "199"),
        ),
    ),
    EvalCase(
        # THE ADAPTIVITY CASE ReWOO's OWN AUTHORS NAME AS THE WEAKNESS:
        # plan-then-execute "may not be the best choice for tasks
        # requiring high adaptability and uncertainty of tool outputs".
        # Every other case here has a next step knowable in advance.
        # This one does not: WHICH transaction to read the category of
        # depends on a value the planner will never see.
        #
        # IT IS ANSWERABLE -- verified by hand before being written,
        # because a case the system cannot satisfy tests the case
        # rather than the system. The chain is aggregate max -> search
        # for that value -> read that object's field, with the value
        # flowing through a handle:
        #
        #     {"id": "a", "step": "aggregate_object", ... "max" ...}
        #     {"id": "b", "step": "search_object",
        #      "filter": {"amount": "$a"}}
        #     {"id": "c", "step": "get_field", "object_id": "$b",
        #      "field_name": "category"}
        #
        # The planner names $a and never learns it is 199. That is
        # adaptivity WITHOUT the planner reading data, which is the
        # thing ReWOO says plan-then-execute cannot do -- so whether
        # the model finds this chain is the real question.
        name="dependent_choice",
        query="What category was Ada Okafor's largest transaction?",
        user_id=USER_ID,
        expected_facts=(
            ExpectedFact("Transaction", "2", "category", "hardware"),
        ),
    ),
    # BLOCKING.md's agent-loop efficiency item: its observed question, verbatim. It took FIVE model
    # calls and fetched `transaction_date` twice; one aggregate step
    # answers it. Passes ONLY if the model chose `aggregate_object` --
    # counting ids from a search is the behaviour under test, not an
    # acceptable alternative. Read the hop count beside the verdict.
    EvalCase(
        name="count_by_aggregate",
        query="How many transactions does Ada Okafor have?",
        user_id=USER_ID,
        expected_facts=(),
        expected_aggregates=(
            ExpectedAggregate("Transaction", "count", "2", filter_mentions="cust_001"),
        ),
    ),
)


#: THE FOUR SWITCHES' CASES (core/llm/agent_features.py). Kept apart from
#: CASES so a plain run measures what it always measured; --cases names
#: them, and scripts/feature_bench.py runs them arm by arm. Each is
#: answerable without its switch -- the baseline arm asks whether the
#: switch is NEEDED, not only whether it works.
FEATURE_CASES = (
    EvalCase(
        # filter_operators: two values of one field. Without it, two
        # searches; with it, one {"in": [..]}.
        name="operators_in",
        query="What are the email addresses of Ada Okafor and Bram Feldman?",
        user_id=USER_ID,
        expected_facts=(
            ExpectedFact("Customer", "cust_001", "email", "ada.okafor@example.com"),
            ExpectedFact("Customer", "cust_002", "email", "bram.feldman@example.com"),
        ),
    ),
    EvalCase(
        # filter_operators: a range. Without it, the model reads every
        # one of Bram's amounts and compares them itself.
        name="operators_range",
        query="What category is Bram Feldman's transaction with a negative amount?",
        user_id=USER_ID,
        expected_facts=(ExpectedFact("Transaction", "4", "category", "refund"),),
    ),
    EvalCase(
        # free_text_search: part of a value. Without it, search_object
        # needs the whole name, which the question does not give.
        name="free_text_surname",
        query="What is the email address of the customer whose surname is Feldman?",
        user_id=USER_ID,
        expected_facts=(
            ExpectedFact("Customer", "cust_002", "email", "bram.feldman@example.com"),
        ),
    ),
    EvalCase(
        # remember_from_query. Graded on the object the memory was filed
        # against and one word of it; the bench removes it afterwards.
        name="remember_preference",
        query="Remember that Ada Okafor prefers to be contacted by email.",
        user_id=USER_ID,
        expected_facts=(),
        expected_memories=(ExpectedMemory("Customer", "cust_001", "email"),),
    ),
)
ALL_CASES = CASES + FEATURE_CASES


class _MemoryCleanup:
    """Removes memories a trial wrote about a case's objects, after the
    trial. A bench must not leave a person's deployment remembering
    things nobody asked it to -- and trial 2 must not be shown trial 1's
    memory, or it measures something else."""

    def __init__(self, generation, case):
        self._store = generation.memory.store if generation.memory else None
        self._objects = [(m.object_type, m.object_id) for m in case.expected_memories]
        self._before = self._ids()

    def _ids(self) -> set:
        if self._store is None:
            return set()
        return {m.memory_id for key in self._objects for m in self._store.about(*key)}

    def __call__(self) -> int:
        new = self._ids() - self._before
        for memory_id in new:
            self._store.remove(memory_id)
        return len(new)


class Timed:
    """Wraps the real adapter and records how long each call took.

    A WRAPPER, NOT A PATCH, because the shape of the numbers is the
    finding: hop 1 against hops 2+, on prompts that get LONGER.
    """

    def __init__(self, wrapped):
        self._wrapped = wrapped
        self.max_concurrent_requests = wrapped.max_concurrent_requests
        self.calls: list[tuple[int, float]] = []

    def chat(self, system_prompt, user_message, json_mode=False,
             temperature=None, *, deadline=None, usage=None, cancel=None):
        started = time.monotonic()
        try:
            return self._wrapped.chat(system_prompt, user_message, json_mode,
                                      temperature, deadline=deadline, usage=usage,
                                      cancel=cancel)
        finally:
            self.calls.append(
                (len(system_prompt) + len(user_message), time.monotonic() - started)
            )


def _show_plans() -> None:
    """Print the plan the model actually wrote.

    WITHOUT THIS, A PLAN-MODE RUN CANNOT BE JUDGED. The first one came
    back correct in one call and 64% faster than the loop -- and the
    output said nothing about whether the planner USED A HANDLE.

    That is the entire security property. A plan of
    `search_object(name=...)` then `get_field($a, email)` names a
    result the planner never saw. A plan that wrote `cust_001`
    directly would be the same speed and the same answer, and would
    prove nothing at all about AL-4 -- it would mean the model
    guessed an id, which is worse than the behaviour it replaced.

    next_plan() already logs the raw response at DEBUG. This turns
    that one logger up rather than the root, so the output stays
    readable.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("    %(message)s"))
    plan_logger = logging.getLogger("core.llm.agent_step_prompt")
    plan_logger.addHandler(handler)
    plan_logger.setLevel(logging.DEBUG)


def describe_gathered(gathered: list[dict]) -> list[str]:
    """What a trial did, one line per gathered entry, in order.

    WITHOUT THIS A FAILURE CANNOT BE DIAGNOSED, only named. The second
    bench run's dependent_choice was told "1 lacks amount", asked for
    exactly that, and was stopped as a DUPLICATE -- so some earlier step
    had claimed it. Which step, the summary line could not say. Every
    refusal and nudge is in `gathered` as a note; this prints them where
    they happened.
    """
    lines = []
    for item in gathered:
        step = item.get("step", "?")
        if "note" in item:
            lines.append(f"{step}: {str(item['note'])[:220]}")
            continue
        target = (item.get("object_ids") or item.get("object_id")
                  or item.get("filter") or "")
        what = " ".join(str(part) for part in (
            item.get("object_type", ""), target,
            item.get("field_name") or item.get("field_names") or "",
            item.get("aggregate") or "",
        ) if part != "")
        lines.append(f"{step} {what} -> {repr(item.get('result'))[:100]}")
    return lines


def use_model(client, model: str) -> None:
    """Point an adapter -- through its retrying and limiting wrappers --
    at another model on the same server. For scripts/compare_models.py:
    the same deployment, the same cases, only the model different."""
    adapter = client
    while hasattr(adapter, "_wrapped"):
        adapter = adapter._wrapped
    if not hasattr(adapter, "model"):
        raise ValueError(f"{type(adapter).__name__} has no model to change")
    adapter.model = model


def answer_for(generation, case_query: str, outcome, usage) -> str | None:
    """The answer a person would have been shown, timed into `usage` --
    the call the bench never made until 19 October, though it is prose
    with no length limit and may be the longest of the question. None for
    a trial that ended in a proposed write, which has no answer to write."""
    if outcome.pending_write is not None:
        return None
    from core.agent.agentic_loop import AgentLoop
    from core.llm.inferred_values import inferred_fields
    from core.llm.synthesis_prompt import synthesize_insight

    return synthesize_insight(
        generation.synthesis_client, case_query, AgentLoop.filter_real_data(outcome.gathered),
        outcome.possibly_incomplete, usage=usage,
        inferred=inferred_fields(generation.config.schema, None),
        brief=generation.loop.features.brief_answers)


def run(paths: RuntimePaths, trials: int, cases: tuple = CASES,
        mode: str = "step", show_plan: bool = False, show_steps: bool = False,
        constrain: bool = False, features: AgentFeatures | None = None,
        collect: list | None = None, *, answer: bool = True,
        model: str | None = None, answer_model: str | None = None,
        timings: list | None = None) -> int:
    """One bench session. `collect`, when given, receives every graded
    trial as it completes -- scripts/feature_bench.py's way of reading
    the results without parsing the report, as (TrialResult, seconds).

    `answer` writes each trial's answer too, as a person would be shown
    it, so a trial's time is a whole question's. `model` and
    `answer_model` point the steps and the answer at other models on the
    configured server. `timings` receives (case name, TokenUsage, seconds)
    per trial -- where each one's time went."""
    if show_plan:
        _show_plans()
    generation = build_generation(paths.config_dir, paths.data_dir, paths.log_dir)
    if model is not None:
        use_model(generation.loop.client, model)
    if model is not None or answer_model is not None:
        use_model(generation.synthesis_client, answer_model or model)
    if constrain:
        generation.loop.constrain_steps = True
    if features is not None:
        # THE ARM'S SWITCHES, WHATEVER config.yaml SAYS -- as --constrain
        # does for AR-5. A bench comparing arms must set every one.
        generation.loop.features = features
    print(f"steps {'CONSTRAINED to the step schema' if generation.loop.constrain_steps else 'free JSON'}")
    print(f"features {', '.join(generation.loop.features.names_on) or 'all off'}")
    user = resolve_user_record(
        generation.config.users, USER_ID, generation.config.security_attribute
    )
    if user.role_name is None:
        # THE MISTAKE THAT COST ME AR-1's FIRST MEASUREMENT. An unknown
        # user id resolves to an EMPTY UserRecord -- no role, no region
        # -- so every read is denied, the schema is empty, and the run
        # looks healthy while proving nothing.
        print(f"FATAL: {USER_ID!r} has no role. Check policy.yaml.")
        return 2

    # WARM THE PREFIX BEFORE TIMING ANYTHING.
    #
    # The first call of a run is cold, and the VM measured prompt
    # evaluation at 0.104 seconds per character -- about 578s for the
    # step prompt against a 600s timeout. A dependent_choice run died
    # exactly there: the plan failed on attempt 1, and attempt 2, which
    # would have shown the revision working, timed out instead.
    #
    # The integration injection test already does this and could not
    # run without it. The bench needed it for the same reason and I
    # did not carry it across.
    #
    # WITH THE REAL SYSTEM PROMPT, which is the whole point. A tiny
    # prompt would warm the MODEL, and the diagnostic already measured
    # that at 3.7 seconds -- nothing. The cost is evaluating the 5,500
    # characters of system prompt, and only sending those caches them.
    #
    # I wrote the tiny version first and caught it against my own
    # measurement, which is the second time this session that "warm
    # the model" and "warm the prefix" have been quietly different
    # things.
    #
    # NOT TIMED, and excluded from the table below, because it is not
    # a trial. The timings that follow are warm ones, which is what
    # every query after the first of the day gets anyway.
    visible_schema = generation.mediator.visible_schema(user, for_agent=True)
    warm_system = _build_system_prompt(
        visible_schema, generation.loop.tools, False, {},
        data_is_shown=(mode != "plan"),
        # THE ARM'S PROMPT, or the warm-up caches a prefix no trial sends.
        features=generation.loop.features if mode != "plan" else AgentFeatures(),
    )
    if mode == "plan":
        warm_system += PLAN_INSTRUCTIONS
    # AND THE WARM-UP GETS ITS OWN, GENEROUS TIMEOUT.
    #
    # It timed out at 600s on its first outing, which is arithmetic
    # rather than a fault: 6,154 characters at the measured 0.104
    # s/char is about 640 seconds. The deployment's timeout is below
    # the cost of its own cold call.
    #
    # RAISING THE DEPLOYMENT'S TIMEOUT IS NOT THE ANSWER -- that is
    # the chasing I stopped doing three patches ago. But this call is
    # not a query: its entire job is to ABSORB the cold cost so the
    # trials afterwards are warm, and a call whose purpose is to be
    # slow should not be killed for being slow.
    #
    # scripts/diagnose_slow_call.py already does exactly this, for
    # exactly this reason -- "so a slow call REPORTS its number
    # instead of timing out". Third time this session I have failed to
    # carry something across from one script to another.
    #
    # THE TRIALS GET IT TOO, AND I HAD THIS BACKWARDS.
    #
    # I wrote "the trials keep the deployment's own limit, so nothing
    # measured runs under a limit the deployment would not use". That
    # sounded principled and produced NO DATA: run after run died at
    # 600s with nothing to report, including the revision attempt that
    # was the whole point of the last one.
    #
    # The variance here is the reason. Identical prompts have been
    # measured at 52.2s and 459.4s -- 8.8x -- so a 600s limit kills
    # the tail of a distribution whose median is about 150s, at
    # random. A killed trial is not a measurement of anything.
    #
    # A BENCH MEASURES; A DEPLOYMENT ENFORCES. The timing table below
    # reports every call's duration, so anyone can apply any limit
    # they like after the fact and see which calls would have failed.
    # Enforcing one DURING the run just throws the number away.
    #
    # The deployment's own timeout being below its cold call is a real
    # problem and a separate one, already reported. It is not fixed by
    # making the bench unable to measure it.
    adapter = generation.loop.client
    while not hasattr(adapter, "timeout_seconds") and hasattr(adapter, "_wrapped"):
        adapter = adapter._wrapped
    real_timeout = getattr(adapter, "timeout_seconds", None)

    print(f"warming the prefix ({len(warm_system)} chars)...", flush=True)
    warm_started = time.monotonic()
    try:
        if real_timeout is not None:
            adapter.timeout_seconds = WARM_UP_TIMEOUT_SECONDS
        generation.loop.client.chat(
            warm_system, "Reply with {}",
            # AN EMPTY OBJECT AND NOTHING ELSE, enforced by the server.
            # The warm-up exists to load the PREFIX; what the model
            # writes is thrown away. Asked politely, the plan prompt's
            # model wrote a whole plan instead -- and, uncapped, kept
            # writing for half an hour, three times.
            json_mode={"type": "object", "properties": {}, "additionalProperties": False},
            temperature=0,
        )
    except LLMUnavailable as e:
        print(f"  model unreachable during warm-up: {e}")
        return 1

    print(f"  {time.monotonic() - warm_started:.1f}s\n")
    if real_timeout is not None:
        adapter.timeout_seconds = WARM_UP_TIMEOUT_SECONDS

    timer = Timed(generation.loop.client)
    generation.loop.client = timer

    results = []
    started = time.monotonic()
    planned = len(cases) * trials
    done = 0
    for case in cases:
        for trial in range(trials):
            before = len(timer.calls)
            cleanup = _MemoryCleanup(generation, case)
            trial_started = time.monotonic()
            # A CONTEXT PER TRIAL, as the query route makes one per
            # request: its tally is where this trial's time went. No
            # deadline -- a bench measures; a deployment enforces.
            context = RequestContext.new()
            try:
                # THE WHOLE REASON run_planned() IS A SIBLING ENTRY
                # POINT rather than a config flag: AL-4 can be measured
                # against the loop it replaces, today, without wiring
                # anyone else owns.
                outcome = (generation.loop.run_planned(user, case.query, context=context)
                           if mode == "plan"
                           else generation.loop.run(user, case.query, context=context))
                answered = (answer_for(generation, case.query, outcome, context.token_usage)
                            if answer else None)
            except KeyboardInterrupt:
                # STOPPING IS NOT LOSING. Every trial already finished
                # is still worth reporting, and on slow hardware
                # somebody WILL stop a run that is taking too long.
                print(f"\n  stopped after {len(results)} trials")
                return _report(results, timer, partial=True,
                                       deployment_limit=real_timeout or 0)
            except LLMUnavailable as e:
                # REPORT WHAT WE HAVE AND STOP, rather than raising.
                #
                # Found by running this without a model: it exited on a
                # traceback and threw away every trial already
                # completed. On the VM that is a whole session -- each
                # trial costs real minutes at ~1.5 tokens/s, and a
                # model evicted or restarted halfway through would lose
                # all of them.
                print(f"\n  MODEL UNREACHABLE after {len(results)} trials: {e}")
                print("  Reporting what was collected. Check the model is")
                print("  loaded (`ollama ps`) and that keep_alive is -1.")
                return _report(results, timer, partial=True,
                                       deployment_limit=real_timeout or 0)
            graded = grade(case, outcome)
            removed = cleanup()
            results.append(graded)
            said = answer_states(case, answered)
            if timings is not None:
                timings.append((case.name, context.token_usage, time.monotonic() - trial_started,
                                said))
            if collect is not None:
                collect.append((graded, time.monotonic() - trial_started))
            done += 1
            elapsed = time.monotonic() - started
            print(f"  {case.name:<26} trial {trial + 1}/{trials}  "
                  f"{'pass' if graded.passed else 'FAIL':<4}  "
                  f"{graded.stop_reason:<20} "
                  f"hops={graded.hops} "
                  f"calls={len(timer.calls) - before} "
                  f"unusable={len(graded.fabricated_finishes)} "
                  f"[{elapsed / 60:.1f}m]"
                  + f"\n      {context.token_usage.describe()}"
                  + ("" if said is None else
                     f"\n      the answer {'states' if said else 'DOES NOT STATE'} the expected facts")
                  + (f"  (removed {removed} memory written by the trial)" if removed else ""))
            if show_steps:
                for number, line in enumerate(describe_gathered(outcome.gathered), 1):
                    print(f"      {number:>2}. {line}")
            if done == 1 and planned > 1:
                # A PROJECTION AFTER THE FIRST TRIAL, because on this
                # hardware the difference between "twenty minutes" and
                # "three hours" decides whether anyone waits. The
                # config's own measurement is ~5.4 tokens/s prefill,
                # which makes one hop minutes rather than seconds.
                print(f"\n  first trial took {elapsed / 60:.1f} minutes. "
                      f"{planned} trials projects to roughly "
                      f"{elapsed * planned / 60:.0f} minutes.")
                print("  Ctrl-C stops it and still reports what it has.\n")

    return _report(results, timer, partial=False,
                   deployment_limit=real_timeout or 0)


def _report(results: list, timer: Timed, *, partial: bool,
            deployment_limit: float = 0) -> int:
    if not results:
        print("\n  No trials completed -- nothing to report.")
        return 1

    print("\n=== RELIABILITY ===")
    reports = aggregate(results)
    for report in reports:
        print("  " + report.summary())

    degenerate = [r for r in reports if r.is_degenerate()]
    if len(degenerate) == len(reports):
        print("\n  EVERY case was degenerate -- all trials agreed.")
        print("  At temperature 0 that is the EXPECTED and desired result:")
        print("  pass^k equals pass^1 for every k, and the metric cannot")
        print("  distinguish anything. If some case had varied, THAT would")
        print("  have been the finding.")

    print("\n=== PARSE FAILURES ===")
    total_unusable = sum(len(r.fabricated_finishes) for r in results)
    print(f"  {total_unusable} unusable replies over {len(results)} trials")
    if total_unusable:
        causes: dict[str, int] = {}
        for r in results:
            for cause in r.fabricated_finishes:
                causes[cause] = causes.get(cause, 0) + 1
        for cause, count in sorted(causes.items()):
            print(f"    {cause:<22} {count}")
        print("\n  A LOW pass^k BESIDE THIS IS A PARSING PROBLEM, not a model")
        print("  problem. Try a fallback parser before D1: a published")
        print("  benchmark moved one model 0.670 -> 0.960 by adding one, and")
        print("  moved another DOWN, a bigger swing than any model swap.")

    print("\n=== PREFIX REUSE (AR-1's engine half) ===")
    print("  prompt chars vs seconds, in call order.")
    print("  IGNORE prompt_eval_count -- it reports total context, not new")
    print("  computation, and cannot detect a cache hit.\n")
    firsts = [d for n, (_, d) in enumerate(timer.calls) if n == 0]
    print(f"  {'call':>5} {'chars':>7} {'seconds':>8} {'s/1k chars':>11}")
    for n, (size, seconds) in enumerate(timer.calls[:12], start=1):
        # FLAGGED, NOT KILLED. A call the deployment would have cut
        # off still gives a number here, and the marker says which.
        over = "  <- over the deployment's limit" if seconds > deployment_limit else ""
        print(f"  {n:>5} {size:>7} {seconds:>8.2f} "
              f"{1000 * seconds / size:>11.3f}{over}")
    exceeded = [d for _, d in timer.calls if d > deployment_limit]
    if exceeded:
        print(f"\n  {len(exceeded)} of {len(timer.calls)} calls exceeded the "
              f"deployment's {deployment_limit}s timeout.")
        print("  Those are queries a real user would have seen fail.")
    if len(timer.calls) > 1:
        first = timer.calls[0][1]
        rest = [d for _, d in timer.calls[1:]]
        print(f"\n  first call        {first:.2f}s")
        print(f"  later calls       median {statistics.median(rest):.2f}s "
              f"over {len(rest)}")
        print("\n  Later prompts are LONGER. If they are not slower, the shared")
        print("  prefix is not being re-read -- which is the reuse AR-1 could")
        print("  only confirm structurally. If they ARE proportionally slower,")
        print("  check keep_alive (config.yaml sets -1) before concluding.")
    assert firsts is not None
    return 1 if partial else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # DEFAULT 1, NOT DEFAULT_K, and that is about this hardware rather
    # than about the metric. One trial per case gives mean@1, the
    # parse-failure rate and the timing table -- two and a half of the
    # three numbers -- for a quarter of the wall clock. pass^k needs
    # k>=2 and is worth a second, narrower run once the first shows
    # what a trial costs.
    parser.add_argument("--trials", type=int, default=1,
                        help=f"trials per case (default 1; pass^k needs at "
                             f"least 2, and {DEFAULT_K} is the smallest k that "
                             f"can show a consistency gap)")
    parser.add_argument("--show-plan", action="store_true",
                        help="print the plan the model wrote. Use it: a fast "
                             "correct answer proves nothing about AL-4 unless "
                             "the plan used a handle rather than naming an id.")
    parser.add_argument("--show-steps", action="store_true",
                        help="print every step a trial took, with each "
                             "refusal and nudge where it happened. What a "
                             "failure needs to be diagnosed, not just named.")
    parser.add_argument("--constrain", action="store_true",
                        help="constrain each step reply to the step schema "
                             "(AR-5), whatever config.yaml says. Run once "
                             "with and once without; the difference is the "
                             "finding.")
    parser.add_argument("--mode", choices=("step", "plan"), default="step",
                        help="step: one model call per hop (today's loop). "
                             "plan: the whole plan in one call (AL-4). Run "
                             "both and compare -- that is what this is for.")
    parser.add_argument("--cases", help="comma-separated case names; "
                        "default the original seven. Run one case first on slow "
                        "hardware. The switches' cases are named here too: "
                        + ", ".join(c.name for c in FEATURE_CASES))
    parser.add_argument("--features", default="",
                        help="comma-separated switches to turn on for this run, "
                             "whatever config.yaml says: filter_operators, "
                             "free_text_search, remember_from_query. 'none' "
                             "turns every one off. Absent: config.yaml's.")
    parser.add_argument("--search-cap", type=int, default=None,
                        help="search_result_cap for this run (AL-3)")
    parser.add_argument("--no-answer", action="store_true",
                        help="do not write each trial's answer. By default it is "
                             "written, as a person would be shown it, so a "
                             "trial's time is a whole question's.")
    parser.add_argument("--model", help="the steps' model, on the configured server, "
                                        "whatever config.yaml says")
    parser.add_argument("--answer-model", help="the answer's model, likewise; "
                                               "default --model")
    parser.add_argument("--config", help="overrides ELYSIUM_CONFIG_DIR")
    parser.add_argument("--data", help="overrides ELYSIUM_DATA_DIR")
    parser.add_argument("--log", help="overrides ELYSIUM_LOG_DIR")
    args = parser.parse_args()

    # THE SAME THREE LOCATIONS EVERY OTHER ENTRY POINT USES, resolved
    # the same way -- ELYSIUM_CONFIG_DIR / ELYSIUM_DATA_DIR /
    # ELYSIUM_LOG_DIR, defaulting to deployment/etc, deployment/var/lib
    # and deployment/var/log.
    #
    # THE FIRST VERSION MADE --data AND --log REQUIRED, and the first
    # person to run it pasted the placeholders from my own
    # instructions and got `bash: data: No such file or directory`. A
    # bench nobody can start measures nothing. The flags remain as
    # overrides; none of them is needed for a normal run.
    paths = resolve_runtime_paths()
    paths = RuntimePaths(
        config_dir=Path(args.config) if args.config else paths.config_dir,
        data_dir=Path(args.data) if args.data else paths.data_dir,
        log_dir=Path(args.log) if args.log else paths.log_dir,
    )
    if not paths.data_dir.exists():
        print(f"No data at {paths.data_dir}. Run a sync first:")
        print("    python3 -m scripts.run_sync")
        return 2
    print(f"config {paths.config_dir}  data {paths.data_dir}  "
          f"log {paths.log_dir}\n")
    cases = CASES
    if args.cases:
        wanted = [name.strip() for name in args.cases.split(",")]
        cases = tuple(c for name in wanted for c in ALL_CASES if c.name == name)
        unknown = set(wanted) - {c.name for c in ALL_CASES}
        if unknown:
            print(f"Unknown case(s): {sorted(unknown)}")
            print(f"Known: {[c.name for c in ALL_CASES]}")
            return 2
    try:
        features = parse_features(args.features, args.search_cap)
    except ValueError as e:
        print(e)
        return 2
    print(f"mode {args.mode}")
    return run(paths, args.trials, cases, args.mode, args.show_plan, args.show_steps,
               args.constrain, features, answer=not args.no_answer, model=args.model,
               answer_model=args.answer_model)


SWITCHES = ("filter_operators", "free_text_search", "remember_from_query")


def parse_features(names: str, search_cap: int | None) -> AgentFeatures | None:
    """--features and --search-cap as one AgentFeatures, or None to keep
    config.yaml's when neither was given."""
    if not names and search_cap is None:
        return None
    wanted = set() if names in ("", "none") else {n.strip() for n in names.split(",")}
    unknown = wanted - set(SWITCHES)
    if unknown:
        raise ValueError(f"Unknown switch(es): {sorted(unknown)}. Known: {list(SWITCHES)}")
    if search_cap is not None and search_cap < 1:
        raise ValueError("--search-cap must be at least 1")
    return AgentFeatures(search_result_cap=search_cap,
                         **{name: name in wanted for name in SWITCHES})


if __name__ == "__main__":
    raise SystemExit(main())
