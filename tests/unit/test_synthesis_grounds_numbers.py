"""No figure reaches the user that did not come from somewhere.

LB-1b, the half that catches what LB-1a cannot. The calculator gives
the model a way to be exact; this is what happens when it does not use
it. Reproduced before either existed: given records of 49.99 and
199.00, an answer claiming $7,412.00 was returned verbatim, and so was
wrong arithmetic, and so was an invented count of 47 transactions.

WHY THE TWO HAD TO SHIP IN THIS ORDER. Measured before 1a existed,
this check ALONE withheld the CORRECT total ($248.99) along with the
invented ones -- because a correct sum legitimately does not appear in
the records. The module docstring said so and was right. A check that
discards good answers gets turned off, which is worse than the gap it
closes.

With the calculator in the registry, a correct total CAN appear in the
records -- as the tool's own result -- so the check finally
distinguishes "computed exactly" from "computed in the model's head".
That distinction is what makes it safe to fail closed.

THE REMAINING FALSE POSITIVE IS DELIBERATE. On a deployment that has
not enabled the calculator, arithmetic done in the model's head is
withheld. That is the intended reading: without a calculator there is
no way to be sure the figure is right, and the project's stated
preference everywhere else is to say less rather than say something
unverified.
"""

import decimal

import pytest

from core.functions.registry import get_enabled_functions
from core.llm.synthesis_prompt import _has_only_grounded_numbers, synthesize_insight

RECORDS = [
    {"object_type": "Transaction", "object_id": "1",
     "amount": decimal.Decimal("49.99")},
    {"object_type": "Transaction", "object_id": "2",
     "amount": decimal.Decimal("199.00")},
]

QUERY = "How much did Ada spend?"


class Fixed:
    max_concurrent_requests = 1

    def __init__(self, answer):
        self.answer = answer

    def chat(self, system_prompt, user_message, json_mode=False,
             temperature=None, *, deadline=None, usage=None):
        return self.answer


def _answer(text, records=None, query=QUERY):
    return synthesize_insight(Fixed(text), query,
                              RECORDS if records is None else records)


def _withheld(text, records=None, query=QUERY):
    return "withheld" in _answer(text, records, query)


# ----------------------------------------------------- the reproduction cases


def test_an_invented_figure_is_withheld():
    """The case from the LB-1 reproduction: $7,412.00 has no relation
    to records of 49.99 and 199.00, and was returned verbatim."""
    assert _withheld("Ada spent $7,412.00 in total [R1][R2].")


def test_wrong_arithmetic_is_withheld():
    assert _withheld("Ada spent $1,248.99 in total [R1][R2].")


def test_an_invented_count_is_withheld():
    assert _withheld("Ada has 47 transactions [R1][R2].")


def test_a_copied_value_is_returned():
    """The check must not withhold a figure read straight from a
    record, or it withholds nearly everything."""
    assert not _withheld("One transaction was $49.99 [R1].")


def test_a_near_miss_is_still_withheld():
    """49.90 is not 49.99. Normalising trailing zeros must not blur two
    different figures into one."""
    assert _withheld("It was $49.90 [R1].")


# ------------------------------------------------- what makes it safe to ship


def test_the_calculator_result_grounds_the_total():
    """LB-1a AND LB-1b, composing -- the reason 1a shipped first.

    The model did not do this sum: the calculator did, its result is a
    gathered record, and the answer quoting it is therefore grounded.
    Before the calculator existed, this exact answer was withheld
    along with the invented ones.
    """
    total = get_enabled_functions(["calculator"])[0].run(
        expression="49.99 + 199.00"
    )
    records = [*RECORDS, {"step": "use_tool", "tool_name": "calculator",
                          "result": total}]

    assert not _withheld("Ada spent $248.99 in total [R1][R2][R3].", records)


def test_the_same_total_without_the_calculator_is_withheld():
    """THE CONTRAST THAT GIVES THE TEST ABOVE ITS MEANING.

    Identical answer, identical figure, correct arithmetic -- withheld,
    because nothing in the records says so. This is the deliberate
    false positive: without a calculator there is no way to know the
    sum is right, and saying less beats saying something unverified.
    """
    assert _withheld("Ada spent $248.99 in total [R1][R2].")


# --------------------------------------------------- the false-positive guards


def test_a_count_is_grounded_by_the_length_of_the_list():
    """"2 transactions" is correct, deterministic and checkable, and 2
    appears in no value. Without this the check withholds counting --
    one of the most common things anyone asks.

    NON-NUMERIC IDS, and a control is why. The first version used ids
    ["1", "2"], so the count 2 was already grounded by an id and
    deleting the list-length logic changed nothing -- the test passed
    against the broken code. Ids with no digits force the count to be
    grounded by the LENGTH or not at all.
    """
    records = [{"step": "search_object", "object_type": "Transaction",
                "result": ["alpha", "beta"]}]

    assert not _withheld("Ada has 2 transactions [R1].", records, "How many?")
    assert _withheld("Ada has 47 transactions [R1].", records, "How many?")


def test_a_figure_the_user_supplied_is_not_a_hallucination():
    """An answer to "over $100 in 2026" restates 100 and 2026, and
    neither need appear in a record."""
    assert not _withheld(
        "No transactions over $100 were found [R1].",
        [RECORDS[0]],
        "Any transactions over $100 in 2026?",
    )


def test_citation_markers_are_not_read_as_figures():
    """[R1] contains a 1. Counting it would ground every answer that
    cited record 1, making the check pass for reasons unrelated to the
    data.

    NON-NUMERIC IDS AGAIN, for the same reason a control found above:
    against RECORDS, whose ids are "1" and "2", the digits in [R1][R2]
    coincide with real data and removing the citation-stripping
    changed nothing.
    """
    records = [{"object_type": "Customer", "object_id": "ada",
                "region": "us-west"}]

    assert _has_only_grounded_numbers("Ada is in the west [R1].",
                                      records, "Where is Ada?") == []
    # ...and the check still fires on a real figure in the same answer.
    assert _has_only_grounded_numbers("Ada is in the west, 88 of them [R1].",
                                      records, "Where is Ada?") == ["88"]


def test_an_answer_with_no_figures_passes_vacuously():
    """Same shape as the citation and email checks: nothing to check
    is not a failure."""
    assert not _withheld("Ada is a customer in the west region [R1].")


def test_thousands_separators_do_not_hide_a_figure():
    """1,248.99 and 1248.99 are the same number, and an invented one
    must not pass by being written with a comma."""
    assert _has_only_grounded_numbers("Total $1,248.99 [R1].", RECORDS, QUERY)
    assert _has_only_grounded_numbers("Total $1248.99 [R1].", RECORDS, QUERY)


def test_it_names_the_figures_it_rejected():
    """Returns the offending numbers rather than a bool, so the log
    says what was wrong instead of only that something was."""
    assert _has_only_grounded_numbers("Ada spent $7,412.00 [R1].",
                                      RECORDS, QUERY) == ["7412", "7412.00"]


def test_the_rendered_form_is_what_grounds_an_answer():
    """LB-5's trap, closed -- and the fixture was chosen by a control.

    The obvious case, Decimal("49.990000000") against an answer of
    49.99, does NOT distinguish: str() of that value contains
    "49.990000000", and stripping trailing zeros yields 49.99 anyway,
    so grounding against the raw value passed too.

    Decimal("4.999E+3") does not distinguish either -- it normalises
    at construction, so str() is already "4999". That was the SECOND
    fixture a control rejected.

    Decimal("1E+3") does: str() is "1E+3", whose numbers are 1 and 3;
    render_value() gives "1000", which is what the model is shown and
    what it copies. Grounding against the raw value would reject a
    correctly copied 1000.
    """
    records = [{"object_type": "Transaction", "object_id": "t",
                "amount": decimal.Decimal("1E+3")}]

    assert not _withheld("It was $1000 [R1].", records)


@pytest.mark.parametrize("answer", [
    "Ada spent $7,412.00 [R1][R2].",
    "Ada has 47 transactions [R1].",
    "The average was 615.50 [R1][R2].",
])
def test_the_withholding_message_says_what_happened(answer):
    """Not a bare refusal: the caller is told the figures were not in
    the records, which is actionable."""
    out = _answer(answer)

    assert "withheld" in out
    assert "figures" in out
    assert answer not in out
