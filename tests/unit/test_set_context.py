"""
The set on screen, said in words for the agent (DEV_UI 5.4).

Browse used to send "About the 404 Transaction objects matching 2
filters:" -- the count of the filters and not what they were. Now it
sends the set, and core/agent/set_context.py says it in the ontology's
own names, after checking the asker could have built it.
"""

import pytest

from core.agent.set_context import (
    MAX_VALUES_LISTED,
    SetContextError,
    describe_set,
    question_about,
)

SCHEMA = {
    "Transaction": {"fields": {
        "category": {"type": "data", "display_name": "Category"},
        "amount": {"type": "data", "data_type": "decimal"},
        "transaction_date": {"type": "data", "data_type": "date"},
    }},
}


def test_a_type_alone():
    assert describe_set(SCHEMA, "Transaction") == \
        "This question is about the Transaction objects."


def test_each_condition_in_the_ontologys_own_names():
    sentence = describe_set(SCHEMA, "Transaction", [
        {"field": "category", "operator": "in", "value": ["refund", "hardware"]},
        {"field": "amount", "operator": "range", "value": {"min": 100}},
    ])

    assert sentence == ("This question is about the Transaction objects whose Category is one "
                        "of refund, hardware and whose Amount is at least 100.")


@pytest.mark.parametrize("condition, words", [
    ({"field": "category", "operator": "equals", "value": "refund"}, "whose Category is refund"),
    ({"field": "category", "operator": "not_in", "value": ["refund"]}, "is none of refund"),
    ({"field": "category", "operator": "contains", "value": "ref"}, "contains 'ref'"),
    ({"field": "amount", "operator": "range", "value": {"min": 1, "max": 9}}, "between 1 and 9"),
    ({"field": "amount", "operator": "range", "value": {"max": 9}}, "is at most 9"),
    ({"field": "transaction_date", "operator": "date_range", "value": {"start": "2026-01-01"}},
     "Transaction date is at least 2026-01-01"),
    ({"field": "transaction_date", "operator": "relative_date", "value": {"since_days_ago": 7}},
     "within the last 7 days"),
])
def test_every_operator_has_words(condition, words):
    assert words in describe_set(SCHEMA, "Transaction", [condition])


def test_the_text_search_is_part_of_the_set():
    assert "matching the search 'Feldman'" in describe_set(SCHEMA, "Transaction", [], "Feldman")


def test_a_long_list_is_counted_not_read_out():
    values = [f"v{n}" for n in range(MAX_VALUES_LISTED + 5)]
    sentence = describe_set(SCHEMA, "Transaction",
                            [{"field": "category", "operator": "in", "value": values}])

    assert "and 5 more" in sentence and f"v{MAX_VALUES_LISTED}" not in sentence


class TestRefused:
    def test_a_type_the_asker_cannot_see(self):
        with pytest.raises(SetContextError, match="Unknown set"):
            describe_set(SCHEMA, "Salary")

    def test_a_field_the_asker_cannot_read_reads_as_unknown(self):
        """Uniform denial: absent and hidden give the same answer."""
        with pytest.raises(SetContextError, match="Unknown set"):
            describe_set(SCHEMA, "Transaction",
                         [{"field": "salary", "operator": "equals", "value": 1}])

    def test_a_malformed_condition(self):
        with pytest.raises(SetContextError):
            describe_set(SCHEMA, "Transaction",
                         [{"field": "amount", "operator": "range", "value": {"min": "lots"}}])


def test_the_askers_words_come_first_and_are_not_rewritten():
    assert question_about("Which are largest?  ", "This question is about X.") == \
        "Which are largest?\n\nThis question is about X."
