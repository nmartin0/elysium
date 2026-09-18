"""
The synthesis prompt teaches shape, not a particular domain's nouns.

AUDITED AND FOUND BREAKING. The engine is domain-neutral and holds well
-- FIELD_DATA_TYPES is string/integer/number/boolean with no `email` or
`currency`, MAC is fully parameterised, and the step vocabulary
describes ontology STRUCTURE. Every apparent domain noun in core/ was a
false positive: "account" meaning a user account, "transaction" meaning
a database transaction.

The synthesis prompt was the exception, and it was DOMAIN LOGIC rather
than an example:

    if the data contains transactions, treat those as the answer to
    "recent transactions" rather than looking for a field named
    "recent"

A logistics deployment got an instruction about a noun its ontology
does not contain, and no equivalent help for its own. The underlying
insight is generic -- a plural in the question may name an object type
rather than a field -- and it had been written domain-specifically.

THE STEP PROMPT IS COVERED TOO, and the change there was made
carefully. Its few-shot examples hardcoded Customer, Transaction and
cust_001. They now use PLACEHOLDER names -- ExampleType, RelatedType,
ex_001 -- and the prompt says so explicitly, which also removes the
risk the audit flagged: a small model could plausibly treat `Customer`
as an available object type and spend a whole hop on it.

WHAT THEY TEACH IS BYTE-IDENTICAL IN STRUCTURE. The three lessons --
do not re-request a field, batch multiple fields into one get_object,
batch multiple ids after following a link -- are unchanged. That is why
this does not prejudge the measurement session, which asks whether the
examples teach the RIGHT things, not what their nouns are.
"""

import re

from core.llm.agent_step_prompt import _build_system_prompt
from core.llm.synthesis_prompt import SYSTEM_PROMPT

# Nouns from THIS deployment's ontology. A prompt naming them is
# teaching one deployment's domain to every deployment.
DOMAIN_NOUNS = ("customer", "transaction", "invoice", "shipment", "ticket")


def test_the_synthesis_prompt_names_no_ontology_noun():
    found = [noun for noun in DOMAIN_NOUNS if noun in SYSTEM_PROMPT.lower()]

    assert found == [], (
        f"the synthesis prompt teaches {found} to every deployment, including "
        f"ones whose ontology has no such object type"
    )


def test_it_still_teaches_the_generic_insight():
    # THE POINT OF THE RULE SURVIVES. Removing the noun must not remove
    # the guidance: a plural in the question may name an object type
    # rather than a field, and "recent" is not a field name.
    lowered = SYSTEM_PROMPT.lower()

    assert "recent" in lowered
    assert "plural" in lowered


def test_it_still_forbids_denying_an_object_that_appears():
    # The other passage generalised here carried the same nouns in its
    # examples. Its rule is the more important one -- denying an
    # object's existence because a field is missing is worse than
    # reporting it incompletely -- and must not have been lost with
    # them.
    lowered = SYSTEM_PROMPT.lower()

    assert "exists" in lowered
    assert "missing" in lowered


def test_no_currency_or_field_shaped_example_remains():
    # A dollar figure is as domain-bound as a noun: it assumes money,
    # and a deployment tracking vessel positions has none.
    assert not re.search(r"\$\d", SYSTEM_PROMPT), (
        "a currency example assumes the deployment's data is money"
    )


# --- the step prompt, whose examples were the other half ---

def _step_prompt():
    """The step prompt as a deployment with NO domain nouns would see it.

    An empty visible_schema deliberately: anything the prompt says with
    no ontology to describe is something it says about ITSELF, which is
    exactly what a domain noun here would be.
    """
    return _build_system_prompt({}, [], False, {}, [])


def test_the_step_prompt_names_no_ontology_noun():
    found = [noun for noun in DOMAIN_NOUNS if noun in _step_prompt().lower()]

    assert found == [], (
        f"the step prompt's examples teach {found} to every deployment, and a "
        f"small model may spend a hop trying to use one"
    )


def test_its_examples_are_marked_as_placeholders():
    # THE RISK THE AUDIT FLAGGED. A model treating an example's object
    # type as available costs a whole hop -- ~190 seconds on this
    # hardware -- and the mediator's denial is the only thing that
    # stops it.
    prompt = _step_prompt()

    assert "PLACEHOLDER" in prompt
    assert "not object types you can use" in prompt


def test_it_still_teaches_all_three_lessons():
    # THE CONTROL, and the reason this does not prejudge the
    # measurement session: what the examples TEACH is unchanged, only
    # their nouns. A rewrite that lost a lesson would pass a neutrality
    # check and quietly make the agent worse.
    prompt = _step_prompt()

    assert "do NOT request" in prompt                    # no re-fetching
    assert "ONE get_object call instead of two" in prompt  # batch fields
    assert "BOTH ids in ONE step" in prompt              # batch ids
