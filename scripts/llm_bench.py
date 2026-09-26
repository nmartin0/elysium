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
    ExpectedFact,
    aggregate,
    grade,
)
from core.deployment_loader import (  # noqa: E402
    RuntimePaths,
    build_generation,
    resolve_runtime_paths,
)
from core.intermediate_layer.auth import resolve_user_record  # noqa: E402
from core.llm.interface import LLMUnavailable  # noqa: E402

USER_ID = "user_alice"

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
        name="two_hops",
        query="What is the email address of the customer in the us-west region "
              "whose name is Ada Okafor?",
        user_id=USER_ID,
        expected_facts=(
            ExpectedFact("Customer", "cust_001", "email", "ada.okafor@example.com"),
        ),
    ),
)


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
             temperature=None, *, deadline=None, usage=None):
        started = time.monotonic()
        try:
            return self._wrapped.chat(system_prompt, user_message, json_mode,
                                      temperature, deadline=deadline, usage=usage)
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


def run(paths: RuntimePaths, trials: int, cases: tuple = CASES,
        mode: str = "step", show_plan: bool = False) -> int:
    if show_plan:
        _show_plans()
    generation = build_generation(paths.config_dir, paths.data_dir, paths.log_dir)
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

    timer = Timed(generation.loop.client)
    generation.loop.client = timer

    results = []
    started = time.monotonic()
    planned = len(cases) * trials
    done = 0
    for case in cases:
        for trial in range(trials):
            before = len(timer.calls)
            try:
                # THE WHOLE REASON run_planned() IS A SIBLING ENTRY
                # POINT rather than a config flag: AL-4 can be measured
                # against the loop it replaces, today, without wiring
                # anyone else owns.
                outcome = (generation.loop.run_planned(user, case.query)
                           if mode == "plan"
                           else generation.loop.run(user, case.query))
            except KeyboardInterrupt:
                # STOPPING IS NOT LOSING. Every trial already finished
                # is still worth reporting, and on slow hardware
                # somebody WILL stop a run that is taking too long.
                print(f"\n  stopped after {len(results)} trials")
                return _report(results, timer, partial=True)
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
                return _report(results, timer, partial=True)
            graded = grade(case, outcome)
            results.append(graded)
            done += 1
            elapsed = time.monotonic() - started
            print(f"  {case.name:<26} trial {trial + 1}/{trials}  "
                  f"{'pass' if graded.passed else 'FAIL':<4}  "
                  f"{graded.stop_reason:<20} "
                  f"hops={graded.hops} "
                  f"calls={len(timer.calls) - before} "
                  f"unusable={len(graded.fabricated_finishes)} "
                  f"[{elapsed / 60:.1f}m]")
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

    return _report(results, timer, partial=False)


def _report(results: list, timer: Timed, *, partial: bool) -> int:
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
        print(f"  {n:>5} {size:>7} {seconds:>8.2f} {1000 * seconds / size:>11.3f}")
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
    parser.add_argument("--mode", choices=("step", "plan"), default="step",
                        help="step: one model call per hop (today's loop). "
                             "plan: the whole plan in one call (AL-4). Run "
                             "both and compare -- that is what this is for.")
    parser.add_argument("--cases", help="comma-separated case names; "
                        "default all. Run one case first on slow hardware.")
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
        wanted = {name.strip() for name in args.cases.split(",")}
        cases = tuple(c for c in CASES if c.name in wanted)
        unknown = wanted - {c.name for c in CASES}
        if unknown:
            print(f"Unknown case(s): {sorted(unknown)}")
            print(f"Known: {[c.name for c in CASES]}")
            return 2
    print(f"mode {args.mode}")
    return run(paths, args.trials, cases, args.mode, args.show_plan)


if __name__ == "__main__":
    raise SystemExit(main())
