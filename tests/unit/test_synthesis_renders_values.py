"""Synthesis shows the model a value, not a Python object.

LB-5: the step prompt has rendered values through prompt_values since
PA001-X2 and G12. This call was left behind, still building its
records with f"{record}" -- a dict repr. The two model calls in one
query therefore showed the same value two different ways:

    step prompt   {"amount": "49.99", "occurred_on": "2026-01-14"}
    synthesis     {'amount': Decimal('49.990000000'),
                   'occurred_on': datetime.date(2026, 1, 14)}

TWO SEPARATE PROBLEMS IN ONE LINE.

Python internals reached the model. `Decimal('49.990000000')` is not a
number a model should be asked to read, and the answer it produces is
the one a person sees -- copying that string into prose is a plausible
thing for a model to do with it.

And money arrived at the STORAGE scale rather than the declared one.
G12 is exactly this question (live path 10.50, mirror 10.500000000)
and prompt_values answered it once: `decimal_places` is what the
ontology says the value IS. Synthesis was showing nine places for a
field declared with two.

IT DID NOT CRASH, which is why it survived. PA001-X2 was the same
values reaching json.dumps, which raises TypeError -- loud, found,
fixed. An f-string renders anything, so the identical defect one
function away produced no error at all. The quiet half of a bug
outlives the loud half.

WHY THE CHECKS MOVED TOO. _has_only_verified_emails grounded the
answer against " ".join(str(record) ...) -- a SECOND rendering, which
happened to match the prompt only because both were repr. Rendering
one without the other would leave a check grepping a string the model
never saw, which can pass an invented value or reject a copied one.
Both now go through _tagged_records().
"""

import datetime
import decimal
import json

from core.llm.synthesis_prompt import _tagged_records, synthesize_insight

RECORDS = [
    {
        "object_type": "Transaction",
        "object_id": "1",
        # The scale a column stores, not the scale the ontology declares.
        "amount": decimal.Decimal("49.990000000"),
        "occurred_on": datetime.date(2026, 1, 14),
    }
]


class Recorder:
    max_concurrent_requests = 1

    def __init__(self, answer="Ada spent $49.99 [R1]."):
        self.answer = answer
        self.user_message = None

    def chat(self, system_prompt, user_message, json_mode=False,
             temperature=None, *, deadline=None, usage=None):
        self.user_message = user_message
        return self.answer


def test_no_python_repr_reaches_the_model():
    client = Recorder()
    synthesize_insight(client, "how much?", RECORDS)

    assert "Decimal(" not in client.user_message
    assert "datetime.date(" not in client.user_message


def test_a_decimal_is_shown_as_a_number_at_its_own_scale():
    client = Recorder()
    synthesize_insight(client, "how much?", RECORDS)

    assert "49.99" in client.user_message
    # NOT the storage scale. This is the assertion that fails if
    # someone renders with str() instead of prompt_values -- str() on
    # this Decimal gives 49.990000000.
    assert "49.990000000" not in client.user_message


def test_a_date_is_shown_as_a_date():
    client = Recorder()
    synthesize_insight(client, "when?", RECORDS)

    assert "2026-01-14" in client.user_message


def test_the_records_are_parseable_json():
    """Each [Rn] line carries a real JSON object.

    Not decoration: a dict repr uses single quotes and cannot be
    parsed by anything, so the model had no reliable structure to read
    field names out of.
    """
    for line in _tagged_records(RECORDS).splitlines():
        tag, _, payload = line.partition(" ")
        assert tag.startswith("[R")
        parsed = json.loads(payload)
        assert parsed["object_type"] == "Transaction"


def test_the_grounding_check_reads_exactly_what_the_model_read():
    """THE PROPERTY THAT STOPS THE TWO DRIFTING.

    If the prompt and the email check ever render records separately,
    one can contain a value the other does not. This asserts they come
    from the same function, by asserting the text is identical.
    """
    client = Recorder()
    synthesize_insight(client, "how much?", RECORDS)

    tagged = _tagged_records(RECORDS)
    assert tagged in client.user_message


def test_an_email_that_is_in_the_rendered_records_is_still_accepted():
    """The check must not have been narrowed by the new rendering."""
    records = [{"object_type": "Customer", "email": "ada@example.com"}]
    client = Recorder("Contact ada@example.com [R1].")

    out = synthesize_insight(client, "email?", records)

    assert "withheld" not in out
    assert "ada@example.com" in out


def test_an_invented_email_is_still_withheld():
    """And the opposite direction, so the test above cannot be
    satisfied by a check that accepts everything."""
    records = [{"object_type": "Customer", "email": "ada@example.com"}]
    client = Recorder("Contact ada@evil.example [R1].")

    assert "withheld" in synthesize_insight(client, "email?", records)
