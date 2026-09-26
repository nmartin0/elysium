"""The harness AL-8 needs, checked against the published figures.

Two halves are tested differently. The estimators are arithmetic and
are checked against numbers from the papers that defined them. The
grader is checked by driving the REAL loop over a REAL mediator --
because a grader that only ever sees hand-built dicts would not
notice the mediator returning a Decimal where the case file says
"49.99", which is the PA001-X2 shape exactly.
"""

import contextlib
import io

import pytest

from core.agent.agentic_loop import StopReason
from core.agent.evaluation import (
    CaseReport,
    EvalCase,
    ExpectedFact,
    TrialResult,
    grade,
    pass_at_k,
    pass_hat_k,
    plug_in_pass_hat_k,
)
from core.deployment_loader import build_generation
from core.intermediate_layer.auth import resolve_user_record

# ---------------------------------------------------------------- estimators


def test_pass_hat_k_matches_the_definition_that_introduced_it():
    """All k of k, from n observed trials.

    tau-bench: C(c, k) / C(n, k). With 3 successes in 4 trials, the
    chance a random pair were both successes is C(3,2)/C(4,2) = 3/6.
    """
    assert pass_hat_k(3, 4, 2) == pytest.approx(0.5)
    assert pass_hat_k(4, 4, 2) == 1.0
    assert pass_hat_k(1, 4, 1) == pytest.approx(0.25)


def test_fewer_successes_than_k_is_zero_not_a_small_number():
    """Two successes cannot contain three in a row."""
    assert pass_hat_k(2, 5, 3) == 0.0


def test_pass_at_k_is_the_optimistic_counterpart():
    """1 - C(n-c, k) / C(n, k). One success in four: the chance a
    random pair contains it is 1 - C(3,2)/C(4,2) = 1 - 0.5."""
    assert pass_at_k(1, 4, 2) == pytest.approx(0.5)
    assert pass_at_k(0, 4, 2) == 0.0
    assert pass_at_k(4, 4, 2) == 1.0


def test_the_gap_between_the_two_is_the_reason_for_the_metric():
    """THE FINDING THE HARNESS EXISTS TO SURFACE.

    The same trials, the same agent: optimistic metric excellent,
    strict metric poor. Published example is 97% at pass@3 against
    34.3% at pass^3.
    """
    successes, trials = 7, 10

    assert pass_at_k(successes, trials, 3) > 0.99
    assert pass_hat_k(successes, trials, 3) < 0.35


def test_the_plug_in_estimate_disagrees_and_is_kept_to_show_it():
    """(c/n)^k is what a secondary source calls pass^k. It is biased,
    and it disagrees on exactly the small-n runs a local harness does.
    Pinned so nobody 'simplifies' the unbiased estimator into it."""
    assert plug_in_pass_hat_k(3, 4, 2) == pytest.approx(0.5625)
    assert pass_hat_k(3, 4, 2) == pytest.approx(0.5)
    assert plug_in_pass_hat_k(3, 4, 2) != pass_hat_k(3, 4, 2)


def test_estimating_more_trials_than_were_run_is_refused():
    """Rather than silently returning something."""
    with pytest.raises(ValueError):
        pass_hat_k(2, 2, 3)
    with pytest.raises(ValueError):
        pass_at_k(2, 2, 3)


def test_all_trials_agreeing_is_reported_as_degenerate():
    """AT TEMPERATURE 0 THIS IS THE EXPECTED RESULT, and it must not
    be quoted as evidence of reliability.

    Every call this project makes is at temperature 0. If the loop is
    deterministic then c is always 0 or n, pass^k equals pass^1 for
    every k, and a quoted pass^3 could not have come out otherwise.
    """
    assert CaseReport("x", trials=5, successes=5).is_degenerate()
    assert CaseReport("x", trials=5, successes=0).is_degenerate()
    assert not CaseReport("x", trials=5, successes=4).is_degenerate()


def test_the_consistency_gap_is_what_an_average_hides():
    """Published: 77.4% average, 53.0% across five runs, 24.4 points."""
    report = CaseReport("x", trials=10, successes=8)

    assert report.mean_at_1 == pytest.approx(0.8)
    assert report.consistency_gap(3) > 0.3


# -------------------------------------------------------------------- grader

USER_ID = "user_alice"

CASE = EvalCase(
    name="ada_email",
    query="What is Ada Okafor's email address?",
    user_id=USER_ID,
    expected_facts=(
        ExpectedFact("Customer", "cust_001", "email", "ada.okafor@example.com"),
    ),
)


class Scripted:
    max_concurrent_requests = 1

    def __init__(self, *steps):
        self._steps = list(steps)

    def chat(self, system_prompt, user_message, json_mode=False,
             temperature=None, *, deadline=None, usage=None):
        return self._steps.pop(0) if self._steps else '{"step": "finish"}'


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
    assert user.role_name is not None, "the fixture user has no role"
    return generation, user


def _run(generation, user, *steps):
    generation.loop.client = Scripted(*steps)
    with contextlib.redirect_stdout(io.StringIO()):
        return generation.loop.run(user, CASE.query)


READ_EMAIL = (
    '{"step": "get_field", "object_type": "Customer", '
    '"object_id": "cust_001", "field_name": "email"}'
)


def test_a_run_that_reads_the_expected_fact_passes(generation_and_user):
    """REAL MEDIATOR, deliberately. A grader checked only against
    hand-built dicts would not notice the mediator returning a Decimal
    or a date where the case file says a string -- PA001-X2's shape."""
    generation, user = generation_and_user
    result = _run(generation, user, READ_EMAIL, '{"step": "finish"}')

    assert grade(CASE, result).passed


def test_a_run_that_reads_nothing_fails(generation_and_user):
    generation, user = generation_and_user
    result = _run(generation, user, '{"step": "finish"}')

    graded = grade(CASE, result)
    assert not graded.passed
    assert graded.missing == CASE.expected_facts


def test_a_run_that_read_the_right_fact_but_did_not_finish_fails():
    """THE CASE THAT MAKES THIS MORE THAN A SUBSET CHECK.

    A run that gathered everything and then hit the hop cap told the
    caller its answer might be partial. That is not the answer the
    case asked for, however complete the data happens to be. Without
    this, LB-3's silent partial answers would grade as successes.
    """
    gathered = [{
        "step": "get_field", "object_type": "Customer",
        "object_id": "cust_001", "field_name": "email",
        "result": "ada.okafor@example.com",
    }]

    assert grade(CASE, _result(gathered, StopReason.FINISHED)).passed
    assert not grade(CASE, _result(gathered, StopReason.MAX_HOPS)).passed
    assert not grade(CASE, _result(gathered, StopReason.REPEATED_ITSELF)).passed


def test_an_unrecognised_stop_reason_fails_closed():
    """A run that ended in a way the grader does not know about is not
    evidence of success."""
    gathered = [{
        "step": "get_field", "object_type": "Customer",
        "object_id": "cust_001", "field_name": "email",
        "result": "ada.okafor@example.com",
    }]

    assert not grade(CASE, _result(gathered, "something_new")).passed


def test_a_decimal_value_grades_against_a_plain_string_in_the_case():
    """The case file says "49.99"; the mediator returns
    Decimal("49.990000000"). Grading through the same renderer the
    prompt uses means a case cannot pass here and fail there."""
    import decimal

    case = EvalCase(
        name="amount", query="how much?", user_id=USER_ID,
        expected_facts=(
            ExpectedFact("Transaction", "1", "amount", "49.99"),
        ),
    )
    gathered = [{
        "step": "get_field", "object_type": "Transaction",
        "object_id": "1", "field_name": "amount",
        "result": decimal.Decimal("49.990000000"),
    }]

    assert grade(case, _result(gathered, StopReason.FINISHED)).passed


def test_a_failure_keeps_its_trace(generation_and_user):
    """A score with no trace is a number nobody can act on."""
    generation, user = generation_and_user
    result = _run(generation, user, READ_EMAIL, '{"step": "finish"}')

    graded = grade(CASE, result)
    assert graded.gathered == result.gathered
    # THE REAL HOP COUNT, not len(gathered). One hop can append several
    # entries -- get_object appends one per field -- so the length was
    # always an approximation, and hops_used is what the loop measured.
    assert graded.hops == result.hops_used


# ---------------------------------------------------------------- aggregate


def _result(gathered, stop_reason, fabricated=()):
    """The real AgentLoopResult, not a stand-in.

    The grader takes the whole object now, so building one here tests
    it against the shape the loop actually returns rather than two
    fields chosen by hand.
    """
    from core.agent.agentic_loop import AgentLoopResult
    return AgentLoopResult(gathered=list(gathered), stop_reason=stop_reason,
                           fabricated_finishes=fabricated)


def _trial(case_name, passed):
    from core.agent.evaluation import TrialResult
    return TrialResult(case_name=case_name, passed=passed,
                       stop_reason=StopReason.FINISHED)


def test_trials_are_grouped_per_case_not_pooled():
    """THE AVERAGING FAILURE THIS MODULE EXISTS TO EXPOSE.

    tau-bench's estimator is an expectation over TASKS. Pooling every
    trial into one pile lets an easy case that always passes mask a
    hard one that never does -- 3/3 and 0/3 pooled look like 50%, and
    nothing says one case is entirely broken.
    """
    from core.agent.evaluation import aggregate

    reports = aggregate([
        _trial("easy", True), _trial("easy", True), _trial("easy", True),
        _trial("hard", False), _trial("hard", False), _trial("hard", False),
    ])

    assert [r.case_name for r in reports] == ["easy", "hard"]
    assert reports[0].pass_hat(3) == 1.0
    assert reports[1].pass_hat(3) == 0.0


def test_a_flaky_case_is_distinguishable_from_a_reliable_one():
    """Same mean, different reliability -- the point of pass^k."""
    from core.agent.evaluation import aggregate

    reliable, flaky = aggregate([
        _trial("reliable", True), _trial("reliable", True),
        _trial("reliable", True), _trial("reliable", True),
        _trial("flaky", True), _trial("flaky", True),
        _trial("flaky", True), _trial("flaky", False),
    ])

    assert reliable.mean_at_1 == 1.0
    assert flaky.mean_at_1 == 0.75
    assert reliable.pass_hat(3) == 1.0
    assert flaky.pass_hat(3) == pytest.approx(0.25)
    # 4/4 IS degenerate -- every trial agreed, so its pass^3 of 1.0
    # could not have come out any other way and must not be quoted as
    # evidence. The flaky case is the one pass^k actually measures.
    assert reliable.is_degenerate()
    assert not flaky.is_degenerate()


def test_the_summary_line_never_quotes_a_passk_that_could_not_vary():
    """A degenerate run says so instead of reporting 100%."""
    from core.agent.evaluation import CaseReport

    degenerate = CaseReport("all_passed", trials=3, successes=3).summary()
    varied = CaseReport("mixed", trials=4, successes=3).summary()

    assert "cannot distinguish" in degenerate
    assert "pass^3" not in degenerate
    assert "pass^3" in varied


# ------------------------------------------- the parse-failure rate beside it


def test_unusable_replies_are_carried_into_the_report():
    """ONE RUN, BOTH NUMBERS.

    A published CPU tool-calling benchmark found that adding a
    fallback parser for non-standard output moved one model from 0.670
    to 0.960 and moved another DOWN from 0.880 to 0.780 -- a bigger
    swing than any model swap in its table. next_step() fails closed
    on every parse failure, so a low pass^k beside a high rate here is
    a PARSING problem wearing a model problem's clothes, and swapping
    the model would be the wrong fix.
    """
    from core.agent.evaluation import aggregate

    reports = aggregate([
        TrialResult(case_name="c", passed=True,
                    fabricated_finishes=("malformed_step",)),
        TrialResult(case_name="c", passed=True,
                    fabricated_finishes=("malformed_step", "unparseable_reply")),
        TrialResult(case_name="c", passed=False),
    ])

    assert reports[0].parse_failures == 3
    assert reports[0].parse_failures_per_trial == pytest.approx(1.0)


def test_a_clean_run_reports_no_parse_failures():
    """The denominator has to be trustworthy: a case with none must not
    report a rate."""
    from core.agent.evaluation import aggregate

    reports = aggregate([TrialResult(case_name="c", passed=True)])

    assert reports[0].parse_failures == 0
    assert reports[0].parse_failures_per_trial == 0.0


def test_the_summary_mentions_unusable_replies_only_when_there_were_some():
    """A line reading "unusable replies=0.00/trial" on every healthy
    case is noise that teaches people to skim the line."""
    from core.agent.evaluation import CaseReport

    clean = CaseReport("c", trials=4, successes=3).summary()
    noisy = CaseReport("c", trials=4, successes=3, parse_failures=2).summary()

    assert "unusable" not in clean
    assert "unusable replies=0.50/trial" in noisy


def test_grade_carries_the_fabricated_finishes_through():
    """The grader takes the whole result precisely so a field added to
    the loop later is not invisible here -- which is what happened to
    fabricated_finishes before this."""
    gathered = [{
        "step": "get_field", "object_type": "Customer",
        "object_id": "cust_001", "field_name": "email",
        "result": "ada.okafor@example.com",
    }]

    graded = grade(CASE, _result(gathered, StopReason.FINISHED,
                                 fabricated=("malformed_step",)))

    assert graded.fabricated_finishes == ("malformed_step",)
