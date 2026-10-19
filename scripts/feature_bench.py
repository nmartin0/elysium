#!/usr/bin/env python3
"""
feature_bench.py  (one session that decides the four agent switches)

core/llm/agent_features.py holds four changes to what the model sees
or may do -- filter operators, a search-result cap, free-text search,
remember-from-query. Each is built, tested without a model, and OFF,
because this project does not change model behaviour on reasoning
alone: AR-5 looked obviously right and cost 60% more wall clock for no
gain on the deployment's own model (BLOCKING.md, agent-loop item).

This runs every arm in one sitting, on the deployment's own model, and
ends with a verdict per switch and the config.yaml lines that follow
from it. Nothing is turned on by running it.

    python -m scripts.feature_bench                 # every arm, 1 trial each
    python -m scripts.feature_bench --arms operators,free_text

THE ARMS, and what each answers:

  baseline     the four new cases with every switch OFF. Whether a
               switch is NEEDED, not only whether it works: if the
               model already answers operators_in with two searches in
               the same hops, the operator is not worth its prompt.
  operators    filter_operators ON: the original seven (does the
               longer prompt cost anything?) and the two operator cases.
  cap          search_result_cap=1 ON: the original seven. The fixture
               data has at most two results per search, so a cap of 1
               is the only one that truncates anything here -- this
               asks whether the note sends the model to aggregate or
               to a narrower search rather than leaving it stuck.
  free_text    free_text_search ON: its case, and two lookups that must
               not get worse.
  remember     remember_from_query ON: its case, and one ordinary
               question during which nothing may be remembered.

Memories a trial writes are removed after it (llm_bench._MemoryCleanup):
a bench must not leave the deployment remembering what nobody asked.

THE RESULTS ARE ALSO WRITTEN to feature_bench.json in the log
directory, so the numbers survive the terminal.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.deployment_loader import RuntimePaths, resolve_runtime_paths  # noqa: E402
from core.llm.agent_features import AgentFeatures  # noqa: E402
from scripts.llm_bench import ALL_CASES, CASES, run  # noqa: E402

ORIGINAL = tuple(case.name for case in CASES)


@dataclass(frozen=True)
class Arm:
    name: str
    features: AgentFeatures
    cases: tuple[str, ...]


ARMS = (
    Arm("baseline", AgentFeatures(),
        ("operators_in", "operators_range", "free_text_surname", "remember_preference")),
    Arm("operators", AgentFeatures(filter_operators=True),
        (*ORIGINAL, "operators_in", "operators_range")),
    Arm("cap", AgentFeatures(search_result_cap=1), ORIGINAL),
    Arm("free_text", AgentFeatures(free_text_search=True),
        ("free_text_surname", "one_field", "two_constraints")),
    Arm("remember", AgentFeatures(remember_from_query=True),
        ("remember_preference", "one_field")),
)

#: The original seven passed 7 of 7 with every switch off, step mode,
#: free JSON, 2026-10-12 (BLOCKING.md). An arm that fails one of them
#: has made something worse.
ORIGINAL_BASELINE = "7/7 on 2026-10-12"


def _summary(trials: list) -> dict:
    by_case: dict[str, dict] = {}
    for graded, seconds in trials:
        entry = by_case.setdefault(graded.case_name, {"passed": 0, "trials": 0, "hops": [],
                                                       "seconds": []})
        entry["trials"] += 1
        entry["passed"] += int(graded.passed)
        entry["hops"].append(graded.hops)
        entry["seconds"].append(round(seconds, 1))
    return by_case


def _all_pass(summary: dict, names) -> bool:
    return all(summary.get(n, {}).get("passed") == summary.get(n, {}).get("trials", -1)
               and summary.get(n, {}).get("trials") for n in names)


def _mean(values: list) -> float:
    return sum(values) / len(values) if values else 0.0


def verdicts(results: dict[str, dict]) -> list[tuple[str, str, str]]:
    """(switch, verdict, why) from whichever arms ran. A verdict is a
    recommendation for a person, not something this applies."""
    out = []
    base = results.get("baseline", {})

    def better_or_equal(arm: dict, case: str) -> tuple[bool, str]:
        mine, theirs = arm.get(case), base.get(case)
        if not mine:
            return False, f"{case} did not run"
        if not _all_pass(arm, [case]):
            return False, f"{case} failed with the switch on"
        if theirs and _all_pass(base, [case]):
            fewer = _mean(mine["hops"]) <= _mean(theirs["hops"])
            return fewer, (f"{case}: {_mean(theirs['hops']):.1f} hops / "
                           f"{_mean(theirs['seconds']):.0f}s off, "
                           f"{_mean(mine['hops']):.1f} / {_mean(mine['seconds']):.0f}s on")
        return True, f"{case} passes on, and did not pass off"

    if "operators" in results:
        arm = results["operators"]
        if not _all_pass(arm, ORIGINAL):
            out.append(("filter_operators", "OFF",
                        f"an original case failed with it on (they were {ORIGINAL_BASELINE})"))
        else:
            checks = [better_or_equal(arm, c) for c in ("operators_in", "operators_range")]
            ok = all(good for good, _ in checks)
            out.append(("filter_operators", "ON" if ok else "OFF",
                        "; ".join(why for _, why in checks)))
    if "cap" in results:
        arm = results["cap"]
        failed = [n for n in ORIGINAL if not _all_pass(arm, [n])]
        out.append(("search_result_cap", "ON (choose a cap above 1, e.g. 20)" if not failed
                    else "OFF", "the original seven all pass under a cap of 1" if not failed
                    else f"failed under a cap of 1: {', '.join(failed)}"))
    if "free_text" in results:
        arm = results["free_text"]
        if not _all_pass(arm, ("one_field", "two_constraints")):
            out.append(("free_text_search", "OFF", "an ordinary lookup failed with it on"))
        else:
            good, why = better_or_equal(arm, "free_text_surname")
            out.append(("free_text_search", "ON" if good else "OFF", why))
    if "remember" in results:
        arm = results["remember"]
        ok = _all_pass(arm, ("remember_preference", "one_field"))
        out.append(("remember_from_query", "ON" if ok else "OFF",
                    "remembered when asked, and answered an ordinary question normally"
                    if ok else "remember_preference or one_field failed with it on"))
    return out


CONFIG_LINE = {
    "filter_operators": "  filter_operators: true",
    "search_result_cap": "  search_result_cap: 20",
    "free_text_search": "  free_text_search: true",
    "remember_from_query": "  remember_from_query: true",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arms", help="comma-separated; default all: "
                        + ", ".join(arm.name for arm in ARMS))
    parser.add_argument("--trials", type=int, default=1, help="trials per case (default 1)")
    parser.add_argument("--show-steps", action="store_true")
    parser.add_argument("--config", help="overrides ELYSIUM_CONFIG_DIR")
    parser.add_argument("--data", help="overrides ELYSIUM_DATA_DIR")
    parser.add_argument("--log", help="overrides ELYSIUM_LOG_DIR")
    args = parser.parse_args()

    arms = ARMS
    if args.arms:
        wanted = [name.strip() for name in args.arms.split(",")]
        unknown = set(wanted) - {arm.name for arm in ARMS}
        if unknown:
            print(f"Unknown arm(s): {sorted(unknown)}. Known: {[a.name for a in ARMS]}")
            return 2
        arms = tuple(arm for arm in ARMS if arm.name in wanted)

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

    by_name = {case.name: case for case in ALL_CASES}
    planned = sum(len(arm.cases) for arm in arms) * args.trials
    print(f"{len(arms)} arm(s), {planned} trials. On a CPU model that is roughly "
          f"{planned * 3} minutes, plus a warm-up per arm.\n")

    results: dict[str, dict] = {}
    unfinished: dict[str, dict] = {}
    started = time.monotonic()
    for arm in arms:
        print(f"\n######## ARM {arm.name}: {', '.join(arm.features.names_on) or 'all off'}")
        trials: list = []
        try:
            # NO ANSWERS: every arm here is about the steps, and on a CPU
            # the answer is the longest call of a question.
            run(paths, args.trials, tuple(by_name[n] for n in arm.cases),
                show_steps=args.show_steps, features=arm.features, collect=trials,
                answer=False)
        except KeyboardInterrupt:
            pass
        # AN ARM THAT DID NOT FINISH DECIDES NOTHING. The model went away
        # or somebody pressed Ctrl-C (llm_bench reports and returns on
        # both); a verdict from half an arm -- or from none of it, which
        # read as "OFF" before this -- would be a verdict about the
        # interruption. Its trials are still printed, and the session
        # stops: the next arm would meet the same unreachable model.
        if len(trials) < len(arm.cases) * args.trials:
            unfinished[arm.name] = _summary(trials)
            print(f"\n  arm {arm.name} did not finish ({len(trials)} of "
                  f"{len(arm.cases) * args.trials} trials); stopping the session.")
            break
        results[arm.name] = _summary(trials)

    print("\n\n======== FEATURE BENCH ========")
    for arm_name, summary in results.items():
        print(f"\n  {arm_name}")
        for case, entry in summary.items():
            print(f"    {case:<26} {entry['passed']}/{entry['trials']}  "
                  f"hops {entry['hops']}  seconds {entry['seconds']}")
    for arm_name, summary in unfinished.items():
        print(f"\n  {arm_name} (UNFINISHED -- no verdict from it)")
        for case, entry in summary.items():
            print(f"    {case:<26} {entry['passed']}/{entry['trials']}  "
                  f"hops {entry['hops']}  seconds {entry['seconds']}")
    decided = verdicts(results)
    print("\n  VERDICTS (a recommendation; nothing has been turned on)")
    if not decided:
        print("    none -- no arm finished. Check the model is loaded (`ollama ps`).")
    for switch, verdict, why in decided:
        print(f"    {switch:<20} {verdict:<6} {why}")
    on = [CONFIG_LINE[s] for s, verdict, _ in decided if verdict.startswith("ON")]
    if on:
        print("\n  To follow them, under `agent:` in config.yaml:")
        for line in on:
            print(f"  {line}")
    print(f"\n  total {(time.monotonic() - started) / 60:.1f} minutes")

    out = paths.log_dir / "feature_bench.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "trials_per_case": args.trials,
            "arms": results,
            "unfinished": unfinished,
            "verdicts": [{"switch": s, "verdict": v, "why": w} for s, v, w in decided],
        }, indent=2))
        print(f"  written to {out}")
    except OSError as e:
        print(f"  could not write {out}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
