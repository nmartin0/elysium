#!/usr/bin/env python3
"""
compare_models.py  (D1 and D2 as a measurement, not an opinion)

Runs llm_bench's seven cases against each model you name -- the same
deployment, the same questions, only the model different -- and ends
with one table: how many it got right, how long a whole question took,
and where that time went.

    python -m scripts.compare_models phi4-mini qwen3:4b-instruct-2507-q4_K_M
    python -m scripts.compare_models phi4-mini --answer-model qwen2.5:1.5b
    python -m scripts.compare_models phi4-mini --cases one_field,count_by_aggregate

Each name is a model ON THE CONFIGURED SERVER (`ollama pull` it first).
To compare SERVERS -- Ollama against llama-server (D2) -- run this once
per server, with --config pointing at a copy whose llm connection names
the other one; llama-server is reached by the OpenAI-style adapter
(provider: vllm), which reads its timings.

WHY IT EXISTS. D1 asked whether to switch phi4-mini to Qwen3-4B "after
the bench", and the bench answered correctness only: 7 of 7, in 20
minutes for seven questions, the answers not written and so not timed.
What a person waits for is the whole question, and on a CPU the two
halves of a call cost very differently -- this deployment measured
about 5.4 tokens a second reading and 1.5 writing. So the table splits
each question into the steps and the answer, and each of those into
reading and writing, from what the server itself reported. A model
that is right as often and writes twice as fast is the answer to D1; a
server that writes the same model faster is the answer to D2.

WHAT THE COLUMNS ARE:

  right        cases passed, graded on facts the mediator returned
  said         answers that stated their expected facts, of those with any
  question     median seconds for a whole question, answer included
  steps        median seconds in step calls, and how many calls
  answer       median seconds writing the answer
  written      median tokens written per question (steps and answer)
  write/s      tokens written per second of writing, over every call
  reused       share of prompt tokens the server did not re-read

A dash is "the server did not say", never zero.

THE RESULTS ARE ALSO WRITTEN to compare_models.json in the log
directory, so the numbers survive the terminal.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.deployment_loader import RuntimePaths, resolve_runtime_paths  # noqa: E402
from scripts.llm_bench import ALL_CASES, CASES, run  # noqa: E402


def summarise(trials: list, timings: list) -> dict:
    """One model's row, from llm_bench.run()'s `collect` and `timings`."""
    def median(values):
        values = [value for value in values if value is not None]
        return statistics.median(values) if values else None

    per_question, step_seconds, step_calls, answer_seconds, written = [], [], [], [], []
    writing = tokens_while_writing = 0.0
    prompt_tokens = cached_tokens = 0
    told_reuse = False
    said = [entry[3] for entry in timings if len(entry) > 3 and entry[3] is not None]
    for _name, usage, seconds, *_ in timings:
        per_question.append(seconds)
        parts = usage.by_part()
        steps = parts.get("step") or parts.get("plan") or {}
        step_seconds.append(steps.get("seconds"))
        step_calls.append(steps.get("calls"))
        answer_seconds.append((parts.get("answer") or {}).get("writing_seconds")
                              or (parts.get("answer") or {}).get("seconds"))
        out = [part.get("output_tokens") for part in parts.values()]
        written.append(sum(value for value in out if value is not None)
                       if any(value is not None for value in out) else None)
        for record in usage.records:
            if record.writing_seconds and record.output_tokens:
                writing += record.writing_seconds
                tokens_while_writing += record.output_tokens
            # ONLY CALLS THAT SAID: a call silent on reuse is not one
            # that reused nothing.
            if record.input_tokens and record.cached_input_tokens is not None:
                told_reuse = True
                prompt_tokens += record.input_tokens
                cached_tokens += record.cached_input_tokens
    return {
        "right": sum(1 for result, _ in trials if result.passed),
        "trials": len(trials),
        # THE ANSWER, graded too: how many stated their expected facts, of
        # those that had any to state (core.agent.evaluation.answer_states).
        "said": sum(1 for value in said if value),
        "said_of": len(said),
        "question_seconds": median(per_question),
        "step_seconds": median(step_seconds),
        "step_calls": median(step_calls),
        "answer_seconds": median(answer_seconds),
        "tokens_written": median(written),
        "write_per_second": tokens_while_writing / writing if writing else None,
        "reused": cached_tokens / prompt_tokens if told_reuse and prompt_tokens else None,
    }


def _shown(value, form: str) -> str:
    return "-" if value is None else format(value, form)


def table(rows: dict) -> str:
    lines = [f"  {'model':<34} {'right':>6} {'said':>6} {'question':>9} {'steps':>12} {'answer':>8} "
             f"{'written':>8} {'write/s':>8} {'reused':>7}"]
    for model, row in rows.items():
        steps = (f"{_shown(row['step_seconds'], '.0f')}s/{_shown(row['step_calls'], '.0f')}"
                 if row["step_seconds"] is not None else "-")
        lines.append(
            f"  {model:<34} {row['right']:>3}/{row['trials']:<2} "
            f"{row.get('said', 0):>3}/{row.get('said_of', 0):<2} "
            f"{_shown(row['question_seconds'], '.0f'):>8}s {steps:>12} "
            f"{_shown(row['answer_seconds'], '.0f'):>7}s {_shown(row['tokens_written'], '.0f'):>8} "
            f"{_shown(row['write_per_second'], '.1f'):>8} "
            f"{_shown(row['reused'] * 100 if row['reused'] is not None else None, '.0f'):>6}%")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("models", nargs="+", help="models on the configured server")
    parser.add_argument("--answer-model", help="one model for every answer, so only the "
                                               "steps' model varies")
    parser.add_argument("--cases", help="comma-separated; default the original seven")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--mode", choices=("step", "plan"), default="step")
    parser.add_argument("--config", help="overrides ELYSIUM_CONFIG_DIR")
    parser.add_argument("--data", help="overrides ELYSIUM_DATA_DIR")
    parser.add_argument("--log", help="overrides ELYSIUM_LOG_DIR")
    args = parser.parse_args(argv)

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
    cases = CASES
    if args.cases:
        wanted = [name.strip() for name in args.cases.split(",")]
        unknown = set(wanted) - {case.name for case in ALL_CASES}
        if unknown:
            print(f"Unknown case(s): {sorted(unknown)}. Known: {[c.name for c in ALL_CASES]}")
            return 2
        cases = tuple(case for name in wanted for case in ALL_CASES if case.name == name)

    rows: dict[str, dict] = {}
    for model in args.models:
        print(f"\n######## {model}")
        trials: list = []
        timings: list = []
        try:
            run(paths, args.trials, cases, args.mode, collect=trials, timings=timings,
                model=model, answer_model=args.answer_model)
        except KeyboardInterrupt:
            print(f"\n  stopped during {model}")
        except ValueError as e:
            print(f"  {e}")
            return 2
        # A MODEL THAT DID NOT FINISH IS NOT COMPARED: its row would be a
        # row about the interruption. What it did finish is printed above.
        if len(trials) < len(cases) * args.trials:
            print(f"\n  {model} did not finish ({len(trials)} of {len(cases) * args.trials} "
                  "trials); stopping.")
            break
        rows[model] = summarise(trials, timings)

    if not rows:
        print("\nNo model finished -- nothing to compare.")
        return 1
    print("\n\n======== MODELS ========")
    if args.answer_model:
        print(f"  every answer written by {args.answer_model}")
    print(table(rows))
    print("\n  Seconds are medians per question. A dash is \"the server did not say\".")
    out = paths.log_dir / "compare_models.json"
    try:
        out.write_text(json.dumps({"at": datetime.now(UTC).isoformat(), "mode": args.mode,
                                   "answer_model": args.answer_model,
                                   "cases": [case.name for case in cases], "models": rows},
                                  indent=2))
        print(f"  written to {out}")
    except OSError as e:
        print(f"  could not write {out}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
