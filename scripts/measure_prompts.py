"""Measures what the agent actually does, one variable at a time.

WHY A HARNESS RATHER THAN READING PROMPTS. Four questions have been
waiting on a machine with a model, and every one of them is a question
about BEHAVIOUR that cannot be answered by looking at the prompt:

  1. Does the agent over-fetch, and would a different example change
     it?
  2. Are aggregates chosen when they should be?
  3. Do the pre-flight action verdicts earn their keep?
  4. Can a small model work without the schema in the prompt?

ITERATE, DO NOT HAND-WRITE THREE PROMPTS AND PICK ONE. The recorded
guidance is to vary ONE thing at a time against the real prompt and
measure, because three hand-written variants measure the author's
taste rather than the model's behaviour.

WHAT IT MEASURES, all of it from the agent's own `gathered` list and
the wall clock -- no new instrumentation and no judgement calls:

  hops          how many steps the agent took
  objects       how many distinct objects it fetched
  step mix      which kinds of step, so aggregate use is visible
  answered      whether it reached an answer at all
  seconds       wall time, which is what a person feels

RUN FROM THE REPOSITORY ROOT, with a model serving:

    cd ~/elysium
    python -m scripts.measure_prompts --runs 3

THREE RUNS BY DEFAULT because one run of a sampling model is an
anecdote. The report shows the spread, and a variant whose spread
overlaps the baseline's has not been shown to differ.

NOTHING HERE CHANGES A PROMPT. It reports; a person decides. A harness
that edited the prompt it was measuring would be marking its own
homework.
"""

import argparse
import statistics
import sys
import time
from dataclasses import dataclass, field

from core.deployment_loader import build_generation, resolve_runtime_paths
from core.intermediate_layer.auth import UserRecord
from core.llm.interface import LLMUnavailable

# THE QUESTIONS, and why each one is here.
#
# Chosen to separate the four measurements rather than to look
# impressive: a question that could be answered several ways measures
# nothing, because two runs taking different routes are both correct.
QUESTIONS = [
    # OVER-FETCHING. One object, one field. Any step beyond the minimum
    # is the agent taking more than it needed.
    ("single_field", "What is cust_001's name?"),
    # TRAVERSAL. Requires following a link, so the floor is higher --
    # what matters is how far above the floor it lands.
    ("one_hop", "What are cust_001's transactions?"),
    # AGGREGATION. A count over a set is exactly what aggregate_object
    # is for. If the agent fetches every row and counts them itself,
    # that is the finding.
    ("aggregate", "How many transactions are there in each category?"),
    # BREADTH. Several objects, one field each. Distinguishes an agent
    # that batches from one that walks.
    ("multi_object", "What are the names of all customers?"),
]


@dataclass
class Observation:
    """One run of one question."""

    question: str
    hops: int
    objects: int
    steps: dict[str, int] = field(default_factory=dict)
    answered: bool = False
    seconds: float = 0.0


def observe(loop, user: UserRecord, question: str) -> Observation:
    """Runs one question and records what the agent did.

    FAILURES ARE OBSERVATIONS TOO. A run that errors is recorded with
    answered=False rather than crashing the sweep -- a prompt variant
    that breaks the agent is a finding, and losing the other runs to
    it would be the harness getting in the way of its own measurement.
    """
    started = time.monotonic()
    try:
        result = loop.run(user, question)
        gathered = result.gathered
        answered = not result.hit_max_hops and not result.cancelled
    except LLMUnavailable:
        # NOT AN OBSERVATION. Every question will fail the same way, so
        # continuing would print the same connection error twelve times
        # and call it a measurement. Raised to the caller, which stops.
        raise
    except Exception as e:  # noqa: BLE001 - see the docstring
        print(f"    (run failed: {type(e).__name__}: {e})", file=sys.stderr)
        gathered = []
        answered = False

    steps: dict[str, int] = {}
    object_ids = set()
    for entry in gathered:
        name = entry.get("step", "unknown")
        steps[name] = steps.get(name, 0) + 1
        if "object_id" in entry:
            object_ids.add((entry.get("object_type"), entry["object_id"]))

    return Observation(
        question=question,
        hops=len(gathered),
        objects=len(object_ids),
        steps=steps,
        answered=answered,
        seconds=time.monotonic() - started,
    )


def _summarise(runs: list[Observation]) -> str:
    """Median and range, not a mean.

    A MEAN HIDES THE THING WORTH SEEING. One run of a sampling model
    that takes nine hops where the others take two is the interesting
    result, and averaging it into 4.3 loses both facts.
    """
    hops = sorted(run.hops for run in runs)
    seconds = sorted(run.seconds for run in runs)
    answered = sum(1 for run in runs if run.answered)
    step_names = sorted({name for run in runs for name in run.steps})
    return (
        f"    hops    median {statistics.median(hops):.0f}  range {hops[0]}-{hops[-1]}\n"
        f"    seconds median {statistics.median(seconds):.1f}  "
        f"range {seconds[0]:.1f}-{seconds[-1]:.1f}\n"
        f"    answered {answered}/{len(runs)}\n"
        f"    steps used: {', '.join(step_names) or 'none'}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3,
                        help="runs per question (default 3; one run of a "
                             "sampling model is an anecdote)")
    parser.add_argument("--user", default="debug",
                        help="who asks. Their grants and MAC value bound what "
                             "the agent can reach, so this changes the answer.")
    parser.add_argument("--region", default="us-west")
    parser.add_argument("--role", default="debug")
    args = parser.parse_args()

    paths = resolve_runtime_paths()
    generation = build_generation(paths.config_dir, paths.data_dir, paths.log_dir)
    if generation.loop is None:
        # THE WHOLE POINT OF THE HARNESS IS THE MODEL, so its absence
        # is the one thing worth refusing over rather than reporting
        # zeros for.
        print("No agent loop in this generation -- is a model configured?",
              file=sys.stderr)
        return 1

    user = UserRecord(args.user, args.region, args.role)

    # TWO MODELS, NOT ONE. A deployment names a step model and a
    # synthesis model separately, and a measurement that reported one
    # would be ambiguous about which produced the behaviour.
    print(f"Step model: {generation.config.step_model}")
    print(f"Synthesis:  {generation.config.synthesis_model}")
    print(f"Asking as: {args.user} ({args.role}, {args.region})")
    print(f"{args.runs} run(s) per question\n")

    for label, question in QUESTIONS:
        print(f"{label}: {question}")
        try:
            runs = [observe(generation.loop, user, question) for _ in range(args.runs)]
        except LLMUnavailable as e:
            print(f"\nThe model is not reachable: {e}", file=sys.stderr)
            print("Start it and re-run. Nothing was measured.", file=sys.stderr)
            return 1
        print(_summarise(runs))
        print()

    print("Nothing here changes a prompt. Vary ONE thing -- an example, the")
    print("schema block, a verdict -- re-run, and compare the medians. A")
    print("variant whose range overlaps the baseline's has not been shown")
    print("to differ.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
