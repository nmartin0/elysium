"""Whether the agent gets it right EVERY time, not whether it can.

AL-8/R59. There is no reliability evaluation, and every remaining item
on the agentloop list -- plan-then-execute, native tool calling,
constrained decoding, prompt optimisation, routing simple questions
away from the loop -- changes MODEL BEHAVIOUR. None of them can be
shown to help without this.

THE PROJECT ALREADY HAS PROOF THAT PLAUSIBLE CHANGES HERE MAKE THINGS
WORSE. IDEAS.md records constrained decoding dropping accuracy from
19.7% to 11.0%. That is AR-5, still on the list, still looking
obviously correct. A harness is what separates the two cases.

PASS^K, NOT PASS@K, and the difference is the whole point. pass@k is
the chance that AT LEAST ONE of k trials succeeds; pass^k is the
chance that ALL k do. tau-bench (Yao et al., 2024), which introduced
pass^k, draws the line at exactly our situation: pass@k "captures the
trend of agents enabling discovery of solutions", while "for
real-world agent tasks requiring reliability and consistency like
customer service" the right question is whether every trial
succeeded. An analyst asking the same question twice and getting two
answers has been failed once, whatever the average says.

The gap between them is not academic. Published measurements: an
agent at 97% pass@3 was 34.3% at pass^3; a ReAct agent succeeding on
77.4% of runs succeeded on all five repetitions for only 53.0% of
tasks.

THE UNBIASED ESTIMATOR, NOT THE PLUG-IN ONE. With n trials of which c
succeeded, tau-bench gives

    pass^k = C(c, k) / C(n, k)        pass@k = 1 - C(n-c, k) / C(n, k)

A secondary source states pass^k as (c/n)^k. That is the plug-in
estimate and it is biased: it is what you would get by treating the
observed rate as the true rate. Both are implemented below so the
difference is visible rather than argued, and the estimator used for
reporting is the unbiased one.

THE FIRST THING TO MEASURE IS WHETHER ANY OF THIS APPLIES. Every model
call this project makes is at temperature 0. If the loop is fully
deterministic then c is always 0 or n, pass^k equals pass^1 for every
k, and the metric says nothing new -- the "ideal compliance posture"
one paper describes. If it is NOT deterministic at temperature 0, that
is itself a finding worth more than the score, and `is_degenerate()`
below is what says which world we are in. Reporting a pass^k without
checking that would be reporting a number that cannot vary.

GRADED ON FACTS, NOT PROSE. A grader that reads the synthesised answer
needs either a second model or a regex over English, and both are less
trustworthy than the thing they are grading. The loop already records
exactly what it read -- object type, id, field, value -- so a case
states which facts a correct run must have gathered, and grading is a
subset check over data the mediator itself returned. Deterministic,
cheap, and it cannot be fooled by fluent prose that did not look
anything up. This is the "code-based grader" the evaluation literature
puts first for outcome verification.

WHAT IT DELIBERATELY DOES NOT GRADE: whether the prose is well
written, whether the phrasing is natural, whether a human would like
it. Those need a judge model and belong to a later pass, if ever.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExpectedFact:
    """One reading a correct run must have made.

    `value` is compared as a STRING against the rendered value, because
    the mediator returns a Decimal for a decimal field and a date for a
    date field -- the exact types PA001-X2 crashed on -- and a case
    file should not have to import decimal to say "49.99".
    """

    object_type: str
    object_id: str
    field_name: str
    value: str


@dataclass(frozen=True)
class EvalCase:
    name: str
    query: str
    user_id: str
    expected_facts: tuple[ExpectedFact, ...]
    # A run that stopped for any reason other than a deliberate finish
    # is a failure even if it happened to gather the right facts: the
    # caller was told the answer might be partial, so it is not the
    # answer the case asks for.
    must_complete: bool = True


@dataclass
class TrialResult:
    case_name: str
    passed: bool
    missing: tuple[ExpectedFact, ...] = ()
    stop_reason: str = ""
    hops: int = 0
    # The gathered payload, kept so a failure can be read rather than
    # only counted. A score with no trace is a number nobody can act on.
    gathered: list[dict] = field(default_factory=list)


def _rendered(value: Any) -> str:
    """The value as a case file would write it.

    Uses the same renderer the prompt does, so a case cannot pass here
    and fail there (or the reverse) because two places formatted a
    decimal differently -- which is exactly the LB-5 defect one layer
    over.
    """
    from core.llm.prompt_values import render_value

    return str(render_value(value))


def grade(case: EvalCase, gathered: list[dict], stop_reason: str) -> TrialResult:
    """One trial, graded on what was read.

    Fails CLOSED on an unknown stop reason: a run that ended in a way
    this function does not recognise is not evidence of success.
    """
    from core.agent.agentic_loop import StopReason

    read: set[tuple[str, str, str, str]] = set()
    for entry in gathered:
        if not isinstance(entry, dict):
            continue
        if entry.get("step") != "get_field":
            continue
        object_type = entry.get("object_type")
        object_id = entry.get("object_id")
        field_name = entry.get("field_name")
        if object_type is None or object_id is None or field_name is None:
            continue
        read.add((str(object_type), str(object_id), str(field_name),
                  _rendered(entry.get("result"))))

    missing = tuple(
        expected for expected in case.expected_facts
        if (expected.object_type, expected.object_id,
            expected.field_name, expected.value) not in read
    )

    complete = stop_reason == StopReason.FINISHED
    passed = not missing and (complete or not case.must_complete)
    return TrialResult(
        case_name=case.name,
        passed=passed,
        missing=missing,
        stop_reason=stop_reason,
        hops=len(gathered),
        gathered=list(gathered),
    )


def pass_hat_k(successes: int, trials: int, k: int) -> float:
    """pass^k: the chance that ALL k trials succeed.

    The unbiased estimator from tau-bench, C(c, k) / C(n, k) -- the
    probability that a random k of the n observed trials were all
    successes. Zero when fewer than k succeeded, which is the honest
    answer rather than a small positive number.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    if trials < k:
        raise ValueError(f"cannot estimate pass^{k} from {trials} trials")
    if successes < k:
        return 0.0
    return math.comb(successes, k) / math.comb(trials, k)


def pass_at_k(successes: int, trials: int, k: int) -> float:
    """pass@k: the chance that AT LEAST ONE of k trials succeeds.

    Here for contrast, not for reporting. It is the optimistic metric,
    and the reason the gap between the two is worth printing: an agent
    can look excellent on this and be unusable.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    if trials < k:
        raise ValueError(f"cannot estimate pass@{k} from {trials} trials")
    failures = trials - successes
    if failures < k:
        return 1.0
    return 1.0 - math.comb(failures, k) / math.comb(trials, k)


def plug_in_pass_hat_k(successes: int, trials: int, k: int) -> float:
    """(c/n)^k -- the BIASED estimate, implemented so the difference is
    visible rather than argued.

    A secondary source gives this as the definition of pass^k. It is
    what you get by treating the observed rate as the true rate, and it
    disagrees with the unbiased estimator on exactly the small-n cases
    a local-model harness will actually run.
    """
    if trials <= 0:
        raise ValueError("trials must be positive")
    return (successes / trials) ** k


# Three is the smallest k that can show a consistency gap at all, and
# the k the published comparisons use. A local model at ~1.5 tokens/s
# decode makes every extra trial expensive, so the default is the
# smallest informative one rather than the most thorough.
DEFAULT_K = 3


@dataclass
class CaseReport:
    case_name: str
    trials: int
    successes: int

    @property
    def mean_at_1(self) -> float:
        """The average success rate -- what "accuracy" usually means."""
        return self.successes / self.trials if self.trials else 0.0

    def pass_hat(self, k: int) -> float:
        return pass_hat_k(self.successes, self.trials, k)

    def consistency_gap(self, k: int) -> float:
        """mean@1 minus pass^k, in the same units.

        The number that says whether an average is hiding an
        unreliability problem. Published example: 77.4% average, 53.0%
        across five runs -- a 24.4 point gap that no accuracy figure
        shows.
        """
        return self.mean_at_1 - self.pass_hat(k)

    def summary(self) -> str:
        """One line per case, as a runner would print it.

        pass^k FIRST and mean@1 beside it, never mean@1 alone: the
        whole argument for this module is that an average cannot tell
        a reliable agent from a lucky one. Degenerate runs say so
        rather than quoting a pass^k that could not have varied.
        """
        if self.is_degenerate():
            verdict = "all trials agreed -- pass^k cannot distinguish"
        else:
            verdict = (f"pass^{DEFAULT_K}={self.pass_hat(DEFAULT_K):.1%} "
                       f"gap={self.consistency_gap(DEFAULT_K):+.1%}")
        return (f"{self.case_name:<28} {self.successes}/{self.trials} "
                f"mean@1={self.mean_at_1:.1%}  {verdict}")

    def is_degenerate(self) -> bool:
        """Every trial agreed, so pass^k cannot distinguish anything.

        NOT A DEFECT -- at temperature 0 it is the expected and desired
        result, and it means pass^k == pass^1 for every k. It is
        reported because a pass^k quoted from all-identical trials is a
        number that could not have come out otherwise, and presenting
        it as evidence of reliability would be circular.
        """
        return self.successes in (0, self.trials)


def aggregate(results: list[TrialResult]) -> list[CaseReport]:
    """Trials grouped into one report per case.

    GROUPED BY CASE, NOT POOLED. pass^k is defined per task and then
    averaged across tasks -- tau-bench's estimator is an expectation
    over tasks, not over one pooled pile of trials. Pooling would let
    an easy case that always passes mask a hard one that never does,
    which is the averaging failure this module exists to expose.
    """
    order: list[str] = []
    counts: dict[str, list[int]] = {}
    for result in results:
        if result.case_name not in counts:
            counts[result.case_name] = [0, 0]
            order.append(result.case_name)
        counts[result.case_name][0] += 1
        counts[result.case_name][1] += int(result.passed)
    return [
        CaseReport(case_name=name, trials=counts[name][0], successes=counts[name][1])
        for name in order
    ]
