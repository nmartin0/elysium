"""The schema tells the model what each field actually is.

LB-2's enabling half. Every field was rendered `name (data)` -- the
same word for money, for a date and for free text -- so the model
could not tell a number from a string in the schema it was reasoning
over.

ALREADY INCONSISTENT WITH F-17, which is what makes this a correction
rather than a feature. `_describe_actions()` states an action
parameter's type in prose (`new_from_balance (number, required)`)
while an object field said nothing. One prompt, two answers to the
same question.

NOTHING NEW BECOMES POSSIBLE. The agent's filters are still
equality-only; widening those is the rest of LB-2 and is the owner's
call under F-18. This only stops the schema lying by omission.

PRECEDENT: text-to-SQL is the closest studied analogue -- a question,
a schema in the prompt, a structured query out -- and every standard
description of a schema block includes types: "the schema of a
database defines the tables, columns, COLUMN TYPES and foreign key
connections". Worked examples annotate every column. The usual
counter-argument is about PRUNING huge schemas to avoid noise; ours is
two object types and nine fields, already cut down by MAC and RBAC
before the model sees it.

MEASURED: +13 characters on a 4,966-character system prompt. Worth
stating because AL-3 found that prompt is re-sent every hop, and I had
been adding to it without measuring.
"""

from core.llm.agent_step_prompt import _describe_schema
from core.ontology.field_types import DEFAULT_FIELD_DATA_TYPE

SCHEMA = {
    "Transaction": {
        "id_field": "transaction_id",
        "fields": {
            # Declared types, of three different shapes.
            "amount": {"type": "data", "data_type": "decimal"},
            "occurred_on": {"type": "data", "data_type": "date"},
            "settled": {"type": "data", "data_type": "boolean"},
            # NO declared type -- the common case in the shipped
            # deployment, where only two of nine fields declare one.
            "category": {"type": "data"},
            "customer_id": {"type": "link", "target": "Customer"},
        },
    }
}


def test_a_declared_type_is_shown():
    rendered = _describe_schema(SCHEMA)

    assert "amount (decimal)" in rendered
    assert "occurred_on (date)" in rendered
    assert "settled (boolean)" in rendered


def test_the_word_data_no_longer_stands_in_for_a_type():
    """THE DEFECT ITSELF. `amount (data)` and `occurred_on (data)` said
    the same thing about money and about a date."""
    rendered = _describe_schema(SCHEMA)

    assert "(data)" not in rendered


def test_an_undeclared_field_is_shown_as_what_the_system_treats_it_as():
    """AN UNDECLARED FIELD IS A STRING, everywhere else already.

    `core/ontology/constraints.py` does exactly `field_def.get(
    "data_type") or DEFAULT_FIELD_DATA_TYPE`, and the mirror uses the
    same default for a column with no declared type. Rendering the
    word "data" here instead would be the same lie by omission this
    change removes -- and would leave the prompt mixing `amount
    (decimal)` with `category (data)`, which is worse than the uniform
    ignorance it replaced.
    """
    rendered = _describe_schema(SCHEMA)

    assert f"category ({DEFAULT_FIELD_DATA_TYPE})" in rendered


def test_the_default_is_the_system_s_own_constant_not_a_literal():
    """Hardcoding "string" here would let this drift from the value the
    mediator and the mirror use. The constant is the contract."""
    assert DEFAULT_FIELD_DATA_TYPE == "string"
    assert f"category ({DEFAULT_FIELD_DATA_TYPE})" in _describe_schema(SCHEMA)


def test_a_link_still_names_its_target_rather_than_a_type():
    """A link field's value is another object's id. Its useful
    description is what it points AT, not that it holds a string."""
    rendered = _describe_schema(SCHEMA)

    assert "customer_id (link -> Customer)" in rendered


def test_the_type_is_stated_as_compactly_as_possible():
    """THE BUDGET GUARD, and it took a rewrite to make it mean
    anything.

    The first version measured this rendering against a schema with
    the types stripped out -- but the fallback renders those as
    `string`, so it was comparing the new code with itself and the
    difference was always zero. Measuring the OLD behaviour is a
    control's job, not a test's.

    What IS testable is the shape: a field costs its name, a space,
    and the type in brackets, and nothing else. AL-3 found the system
    prompt is re-sent every hop and AR-2 recovered about nine points
    of prefix reuse, so `amount (a decimal number)` or `amount (type:
    decimal)` would spend that back for no information. The other half
    of LB-2 measured +504 characters; this stays two orders of
    magnitude below it.
    """
    rendered = _describe_schema(SCHEMA)

    for field, declared in (("amount", "decimal"), ("occurred_on", "date"),
                            ("settled", "boolean")):
        assert f"{field} ({declared})" in rendered
        # Nothing between the name and the bracket, and nothing inside
        # it but the type.
        assert f"{field} (type: " not in rendered
        assert f"{field} (a " not in rendered


def test_the_searchable_list_is_unchanged():
    """A guard against scope creep. Naming a field's type must not
    quietly change WHICH fields the model may search -- that is the
    rest of LB-2, and it is the owner's call."""
    rendered = _describe_schema(SCHEMA)

    assert "'transaction_id', 'amount', 'occurred_on'" in rendered
