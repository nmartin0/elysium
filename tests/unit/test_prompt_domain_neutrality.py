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

DELIBERATELY NOT COVERING the step prompt's few-shot examples. Those
hardcode Customer and Transaction too, but they teach SHAPE, and a
model generalises from a Customer example to a Ship. Replacing them
blind is the prompt-editing-before-measuring that IDEAS.md argues
against; they belong to the measurement session.
"""

import re

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
