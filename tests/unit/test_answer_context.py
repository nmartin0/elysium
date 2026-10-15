"""The read-back, doors and follow-on questions that come with an answer.

Entries are shaped as AgentLoop records them -- {**step, "result": ...},
search results carrying "titles" beside the ids, get_object expanded to
one get_field entry per field -- and passed through filter_real_data
first, as the route does.
"""

from core.agent.agentic_loop import AgentLoop
from core.agent.answer_context import (
    MAX_READ_BACK,
    doors,
    follow_ons,
    read_back,
)

SCHEMA = {
    "Customer": {
        "display_name": "Customer", "plural_display_name": "Customers",
        "id_field": "customer_id", "title_field": "name",
        "fields": {
            "customer_id": {"type": "data", "display_name": "Customer id"},
            "name": {"type": "data", "display_name": "Name"},
            "region": {"type": "data", "display_name": "Region"},
            "transactions": {"type": "link", "target": "Transaction", "cardinality": "many",
                             "display_name": "Transactions"},
            "support_tickets": {"type": "link", "target": "SupportTicket", "cardinality": "many",
                                "display_name": "Support tickets"},
            "account_manager": {"type": "link", "target": "Customer", "cardinality": "one",
                                "display_name": "Account manager"},
        },
    },
    "Transaction": {
        "display_name": "Transaction", "plural_display_name": "Transactions",
        "id_field": "transaction_id",
        "fields": {
            "transaction_id": {"type": "data"},
            "amount": {"type": "data", "data_type": "number", "display_name": "Amount"},
            "category": {"type": "data", "data_type": "string", "display_name": "Category"},
            "customer_id": {"type": "data", "display_name": "Customer"},
        },
    },
    "SupportTicket": {"display_name": "Support ticket", "plural_display_name": "Support tickets",
                      "fields": {"subject": {"type": "data"}}},
}

FOUND_ADA = {"step": "search_object", "object_type": "Customer", "filter": {"name": "Ada Okafor"},
             "result": ["cust_001"], "titles": {"cust_001": "Ada Okafor"}}
COUNTED = {"step": "aggregate_object", "object_type": "Transaction",
           "filter": {"customer_id": "cust_001"}, "aggregate": "count", "result": 202}


def _real(*entries):
    return AgentLoop.filter_real_data(list(entries))


class TestReadBack:
    def test_says_what_was_done_in_the_ontologys_words(self):
        assert read_back(_real(FOUND_ADA, COUNTED), SCHEMA) == [
            "Found 1 Customer whose Name is Ada Okafor",
            "Counted Transactions whose Customer is cust_001",
        ]

    def test_reads_of_one_object_are_one_sentence_by_its_name(self):
        entries = _real(FOUND_ADA,
                        {"step": "get_field", "object_type": "Customer", "object_id": "cust_001",
                         "field_name": "region", "result": "us-west"},
                        {"step": "get_field", "object_type": "Customer", "object_id": "cust_001",
                         "field_name": "name", "result": "Ada Okafor"})
        assert read_back(entries, SCHEMA)[-1] == "Read Region and Name of Customer Ada Okafor"

    def test_a_DENIED_read_is_not_read_back(self):
        """A refused field arrives as None, like a null one; filter_real_data
        strips both. Saying "Read Email" would tell them a refused field
        was asked for -- the trace's job, for their own request, not this."""
        denied = {"step": "get_field", "object_type": "Customer", "object_id": "cust_001",
                  "field_name": "region", "result": None}
        assert read_back(_real(FOUND_ADA, denied), SCHEMA) == ["Found 1 Customer whose Name is Ada Okafor"]

    def test_finding_nothing_says_so(self):
        none = {**FOUND_ADA, "result": [], "titles": {}}
        assert read_back(_real(none), SCHEMA) == ["Found no Customers whose Name is Ada Okafor"]

    def test_a_capped_search_reports_the_true_total(self):
        many = {"step": "search_object", "object_type": "Transaction", "filter": {"category": "refund"},
                "result": ["1", "2"], "total": 81}
        assert read_back(_real(many), SCHEMA) == ["Found 81 Transactions whose Category is refund"]

    def test_following_a_link_names_both_ends(self):
        around = {"step": "search_around", "object_type": "Customer", "filter": {"name": "Ada Okafor"},
                  "link_field": "support_tickets", "result": ["t1", "t2"]}
        assert read_back(_real(around), SCHEMA) == [
            "Followed Support tickets from the Customers whose Name is Ada Okafor to 2 Support tickets",
        ]

    def test_an_aggregate_names_its_measure_and_grouping(self):
        summed = {"step": "aggregate_object", "object_type": "Transaction", "filter": {},
                  "aggregate": "sum", "field_name": "amount", "group_by": "category",
                  "result": {"refund": 10}}
        assert read_back(_real(summed), SCHEMA) == ["Added up Amount across Transactions, by Category"]

    def test_a_plan_handle_is_not_described_as_a_literal(self):
        planned = {**COUNTED, "filter": {"customer_id": "$a"}}
        assert read_back(_real(planned), SCHEMA) == ["Counted Transactions"]

    def test_bookkeeping_is_not_a_step(self):
        noise = {"step": "rejected_duplicate", "note": "x"}
        assert read_back(_real(noise, FOUND_ADA), SCHEMA) == ["Found 1 Customer whose Name is Ada Okafor"]

    def test_a_long_path_is_cut_with_a_count(self):
        entries = [{"step": "search_object", "object_type": "Customer", "filter": {"region": f"r{i}"},
                    "result": []} for i in range(MAX_READ_BACK + 3)]
        sentences = read_back(_real(*entries), SCHEMA)
        assert len(sentences) == MAX_READ_BACK
        assert sentences[-1] == "and 4 more steps"


class TestDoors:
    def test_the_object_the_answer_is_about(self):
        assert doors(_real(FOUND_ADA), SCHEMA)[0] == {
            "kind": "object", "object_type": "Customer", "object_id": "cust_001", "label": "Ada Okafor"}

    def test_a_counted_set_opens_in_browse_when_browse_can_say_it_exactly(self):
        assert doors(_real(COUNTED), SCHEMA) == [{
            "kind": "set", "object_type": "Transaction", "label": "The Transactions counted",
            "filters": [{"field": "customer_id", "values": ["cust_001"], "mode": "keep"}]}]

    def test_a_range_gets_NO_door_rather_than_a_door_to_a_different_set(self):
        ranged = {**COUNTED, "filter": {"amount": {"min": 100}}}
        assert doors(_real(ranged), SCHEMA) == []

    def test_around_titles_belong_to_the_target_type(self):
        around = {"step": "search_around", "object_type": "Customer", "filter": {"name": "Ada Okafor"},
                  "link_field": "support_tickets", "result": ["t1"], "titles": {"t1": "Card declined"}}
        assert doors(_real(around), SCHEMA) == [{
            "kind": "object", "object_type": "SupportTicket", "object_id": "t1", "label": "Card declined"}]


class TestFollowOns:
    def test_the_links_not_yet_followed_from_the_named_object(self):
        asked = follow_ons("How many transactions does Ada Okafor have?", _real(FOUND_ADA), SCHEMA)
        assert asked[:2] == [
            "What is the account manager of Ada Okafor?",
            "What support tickets does Ada Okafor have?",
        ]

    def test_not_a_link_the_agent_already_followed(self):
        around = {"step": "search_around", "object_type": "Customer", "filter": {"name": "Ada Okafor"},
                  "link_field": "support_tickets", "result": ["t1"]}
        asked = follow_ons("q", _real(FOUND_ADA, around), SCHEMA)
        assert not any("support tickets" in question for question in asked)

    def test_each_one_is_whole_never_a_fragment_of_a_thread(self):
        asked = follow_ons("How many transactions does Ada Okafor have?", _real(FOUND_ADA, COUNTED), SCHEMA)
        assert asked[-1] == "How many transactions does Ada Okafor have, broken down by category?"
        assert len(asked) <= 3

    def test_nothing_named_nothing_suggested_about_it(self):
        """'What tickets does cust_001 have?' reads as a database query."""
        anonymous = {**FOUND_ADA, "titles": {}}
        assert follow_ons("q", _real(anonymous), SCHEMA) == []
