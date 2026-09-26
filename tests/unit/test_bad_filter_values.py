"""A value the model writes must never crash the query.

Found while building a harder bench case. A plan chained an aggregate
into a filter, and the whole thing died on an uncaught
`decimal.InvalidOperation` -- not from plan mode, but from the LIVE
loop, reachable today:

    {"step": "search_object", "object_type": "Transaction",
     "filter": {"amount": "$100"}}

A filter value is converted to the field's declared type before the
query runs. On a DATE field a bad value raises ValueError, which
_execute_step catches, and the model is told it made a mistake. On a
DECIMAL field it raises decimal.InvalidOperation -- an ArithmeticError
-- which was caught by nothing. It left the loop, left the handler,
and became a 500.

THE SAME CLASS OF MODEL MISTAKE, TWO DIFFERENT OUTCOMES, decided by
which library happens to raise what. That asymmetry is the defect;
the crash is just how it shows.

AND "$100" IS NOT AN EXOTIC INPUT. The schema tells the model `amount`
is searchable and now tells it the field is a decimal. A user asking
about money and a model writing the currency symbol is the ordinary
case, not the adversarial one.

This is AL-1's shape: a model-written value crashing /query outside
the error handling.
"""

import contextlib
import io

import pytest

from core.deployment_loader import build_generation
from core.intermediate_layer.auth import resolve_user_record

USER_ID = "user_alice"


class Once:
    """Offers one step, then finishes."""

    max_concurrent_requests = 1

    def __init__(self, step_json):
        self._replies = [step_json, '{"step": "finish"}']

    def chat(self, *a, **k):
        return self._replies.pop(0) if self._replies else '{"step": "finish"}'


@pytest.fixture
def loop_and_user(synced_deployment):
    generation = build_generation(
        synced_deployment.config_dir,
        synced_deployment.data_dir,
        synced_deployment.log_dir,
    )
    user = resolve_user_record(
        generation.config.users, USER_ID, generation.config.security_attribute
    )
    assert user.role_name is not None
    return generation.loop, user


def _search(value):
    import json
    return json.dumps({"step": "search_object", "object_type": "Transaction",
                       "filter": {"amount": value}})


@pytest.mark.parametrize("value", [
    "not a number",
    "",
    "$100",          # the one that found this
    "100 GBP",
    True,
    [1, 2],
    {"x": 1},
])
def test_a_bad_decimal_filter_is_a_mistake_not_a_crash(loop_and_user, value):
    """EVERY ONE OF THESE CRASHED /query BEFORE.

    They must become a recoverable mistake -- the model is told the
    step was not usable and gets another hop -- exactly as a bad date
    already did.
    """
    loop, user = loop_and_user
    loop.client = Once(_search(value))

    with contextlib.redirect_stdout(io.StringIO()):
        result = loop.run(user, "transactions over a hundred?")

    assert any(e.get("step") == "rejected_invalid_step" for e in result.gathered), (
        f"{value!r} did not become a recoverable mistake"
    )


def test_a_bad_date_filter_behaves_the_same_way(loop_and_user):
    """THE CONTROL FOR THE ASYMMETRY. A date field already did the
    right thing, via ValueError. If the two ever diverge again, this
    is what says so."""
    import json

    loop, user = loop_and_user
    loop.client = Once(json.dumps({
        "step": "search_object", "object_type": "Transaction",
        "filter": {"transaction_date": "yesterday"},
    }))

    with contextlib.redirect_stdout(io.StringIO()):
        result = loop.run(user, "recent transactions?")

    assert any(e.get("step") == "rejected_invalid_step" for e in result.gathered)


def test_a_good_decimal_filter_still_works(loop_and_user):
    """THE OPPOSITE DIRECTION, so the guard cannot be satisfied by
    rejecting every decimal filter."""
    import json

    loop, user = loop_and_user
    loop.client = Once(json.dumps({
        "step": "search_object", "object_type": "Transaction",
        "filter": {"amount": "199.00"},
    }))

    with contextlib.redirect_stdout(io.StringIO()):
        result = loop.run(user, "which transaction was 199?")

    searches = [e for e in result.gathered if e.get("step") == "search_object"]
    assert searches, "a valid decimal filter was rejected"
    assert searches[0]["result"], "a valid decimal filter found nothing"


def test_our_own_arithmetic_errors_are_not_swallowed(loop_and_user):
    """DecimalException, NOT ArithmeticError, and this is why.

    The wider family would also catch ZeroDivisionError and
    OverflowError raised by OUR code. Those are our bugs, and
    reporting one to the model as "that step was not usable" would
    hide it behind a retry until someone noticed the answers were
    wrong.

    ASSERTED ON THE except CLAUSE, NOT ON SUBCLASS RELATIONSHIPS, and
    a control is why. The first version checked that ZeroDivisionError
    is not a DecimalException -- true of Python, true regardless of
    what this code catches, and it passed happily with the clause
    widened to ArithmeticError. It tested the standard library.
    """
    loop, user = loop_and_user
    real_handler = loop._step_search_object

    def our_bug(*args, **kwargs):
        raise ZeroDivisionError("a bug in our own code, not the model's")

    loop._step_search_object = our_bug
    loop.client = Once(_search("199.00"))
    try:
        with pytest.raises(ZeroDivisionError):
            with contextlib.redirect_stdout(io.StringIO()):
                loop.run(user, "anything")
    finally:
        loop._step_search_object = real_handler


# ------------------------------- checked at the boundary, not three layers down


def test_the_model_is_told_which_field_and_why(loop_and_user):
    """CATCHING AN EXCEPTION IS NOT THE SAME AS PREVENTING ONE.

    Caught, the model learns "that step was not usable". Checked at
    the boundary, it learns "filter 'amount': '$100' is not a number,
    so it cannot be stored as a `decimal`" -- and can fix it.

    The economics are why this matters: one corrective model call is
    50-280 seconds on this hardware, so a message the model can act on
    is the difference between one retry and a wasted hop.
    """
    loop, user = loop_and_user
    loop.client = Once(_search("$100"))

    with contextlib.redirect_stdout(io.StringIO()):
        result = loop.run(user, "transactions over a hundred?")

    notes = [e["note"] for e in result.gathered
             if e.get("step") == "rejected_invalid_step"]
    assert notes, "no mistake was recorded"

    # ASSERTED ON THIS CHECK'S OWN PHRASING, and two controls are why.
    # The note ECHOES THE STEP, which already contains 'amount', and
    # the raw pyiceberg failure reads "<class
    # 'decimal.ConversionSyntax'>", which already contains "decimal".
    # So asserting those two words passed with the boundary check
    # deleted AND with the field name stripped from the message --
    # both satisfied by text this check never produced.
    assert "filter 'amount':" in notes[0], "does not name the field it checked"
    assert "is not a number" in notes[0], "not this check's explanation"


def test_a_field_the_caller_cannot_see_gets_no_type_error(loop_and_user):
    """AGAINST THE VISIBLE SCHEMA, NEVER THE CANONICAL ONE.

    The model can only satisfy the schema it was shown -- but the
    sharper reason here is disclosure. A type error about a field the
    caller has no grant for would CONFIRM that the field exists.
    Uniform denial requires "no such field" and "a field you may not
    see" to be the same answer, and this project holds that
    everywhere else.

    So a field outside the visible schema is left alone here and
    refused downstream as an unknown field -- the existing,
    deliberately uninformative path.
    """
    loop, user = loop_and_user
    visible = loop.mediator.visible_schema(user, for_agent=True)
    hidden = {
        "Transaction": {
            **visible["Transaction"],
            "fields": {f: spec for f, spec in visible["Transaction"]["fields"].items()
                       if f != "amount"},
        }
    }

    # Must not raise: it is not this check's business.
    loop._check_filter_types("Transaction", {"amount": "$100"}, hidden)


def test_a_valid_value_passes_the_check(loop_and_user):
    """The opposite direction, so the guard cannot be satisfied by
    refusing everything."""
    loop, user = loop_and_user
    visible = loop.mediator.visible_schema(user, for_agent=True)

    loop._check_filter_types("Transaction", {"amount": "199.00"}, visible)
    loop._check_filter_types("Transaction", {"category": "hardware"}, visible)


def test_a_link_filter_value_is_accepted(loop_and_user):
    """A link's value is another object's id.

    THERE IS NO SPECIAL CASE FOR LINKS, and a control is why. I wrote
    one -- skip link fields -- and then could not make any test
    distinguish it: a link declares no `data_type`, so it falls back
    to `string`, and coercing an id to a string always succeeds. Code
    no control can kill is code nobody can trust, so it went. This
    asserts the behaviour that remains.
    """
    loop, user = loop_and_user
    visible = loop.mediator.visible_schema(user, for_agent=True)

    loop._check_filter_types("Customer", {"transactions": "t_1"}, visible)
