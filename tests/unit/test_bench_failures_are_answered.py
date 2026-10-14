"""The three step-mode failures the bench measured, replayed through the
real loop, and what the model is told now.

THE BENCH, run on the deployment's own CPU model, 2026-10-11: four
cases passed three trials of three, and three failed three of three --
the same way every time, at temperature 0. Each failure is replayed
here step for step, from the bench's own log lines, so the test is the
trajectory the model really took rather than one imagined for it.

    link_fanout         found customer cust_001, then asked for
                        Transaction cust_001's amount. No such
                        Transaction; None; asked again; stopped.
    count_by_aggregate  asked get_object for a field "count", was
                        refused, asked get_field for it -- which was
                        NOT refused, returned None, twice; stopped.
    dependent_choice    told "1: ['category'], 2: ['amount',
                        'category']", re-read object 2, the complete
                        one; stopped.

WHAT THIS CAN AND CANNOT SHOW. It shows the loop now refuses each
wrong step and tells the model, in the next prompt, the step that would
have been right. Whether THIS model then takes it is a property of the
model, and only the bench on the deployment's own machine can answer
that. These tests make the bench's question worth asking again.

REAL MEDIATOR, as test_stop_reason_is_named.py insists and for its
reason: a spiral is the loop driving real reads.
"""

import contextlib
import io

import pytest

from core.agent.agentic_loop import _detect_asymmetry
from core.deployment_loader import build_generation
from core.intermediate_layer.auth import resolve_user_record

USER_ID = "user_alice"


class Script:
    """Says each reply in turn, and keeps every prompt it was shown."""

    max_concurrent_requests = 1

    def __init__(self, *replies):
        self.replies = iter(replies)
        self.shown: list[str] = []

    def chat(self, system_prompt, user_message, json_mode=False,
             temperature=None, *, deadline=None, usage=None, cancel=None):
        self.shown.append(user_message)
        return next(self.replies, '{"step": "finish"}')


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
    assert user.role_name is not None, "the fixture user has no role"
    return generation.loop, user


def _run(loop, user, question, *replies):
    script = Script(*replies)
    loop.client = script
    with contextlib.redirect_stdout(io.StringIO()):
        result = loop.run(user, question)
    return result, script


FIND_ADA = '{"step": "search_object", "object_type": "Customer", "filter": {"customer_id": "cust_001"}}'


class TestAnotherTypesId:
    def test_the_bench_s_wrong_step_is_refused_with_the_link_to_follow(self, loop_and_user):
        loop, user = loop_and_user
        _, script = _run(
            loop, user, "What are the amounts of all of Ada Okafor's transactions?",
            FIND_ADA,
            '{"step": "get_object", "object_type": "Transaction", "object_ids": ["cust_001"], '
            '"field_names": ["amount"]}',
        )

        # THE NOTE ARRIVES INSIDE `Gathered so far`, a JSON dump, so its
        # own quotes are escaped there; unescaped is what the model reads.
        told = script.shown[2].replace('\\"', '"')
        assert "'cust_001' is a Customer id, not a Transaction id" in told
        assert '"field_name": "transactions"' in told
        assert '"filter": {"customer_id": "cust_001"}' in told

    def test_taking_the_advice_reaches_the_answer(self, loop_and_user):
        """THE CONTROL that the guard is conservative: ids arriving
        through the link are Transaction ids, and the read goes ahead."""
        loop, user = loop_and_user
        result, _ = _run(
            loop, user, "What are the amounts of all of Ada Okafor's transactions?",
            FIND_ADA,
            '{"step": "get_object", "object_type": "Transaction", "object_ids": ["cust_001"], '
            '"field_names": ["amount"]}',
            '{"step": "get_field", "object_type": "Customer", "object_id": "cust_001", '
            '"field_name": "transactions"}',
            '{"step": "get_object", "object_type": "Transaction", "object_ids": [1, 2], '
            '"field_names": ["amount"]}',
        )

        amounts = {str(item["object_id"]): item["result"] for item in result.gathered
                   if item.get("field_name") == "amount" and "result" in item}
        assert set(amounts) == {"1", "2"}
        assert all(value is not None for value in amounts.values())

    def test_an_id_found_by_searching_this_type_is_never_refused(self, loop_and_user):
        loop, user = loop_and_user
        result, script = _run(
            loop, user, "What is transaction 1's amount?",
            '{"step": "search_object", "object_type": "Transaction", "filter": {"customer_id": "cust_001"}}',
            '{"step": "get_field", "object_type": "Transaction", "object_id": 1, "field_name": "amount"}',
        )

        assert "not a Transaction id" not in "".join(script.shown)


class TestACountIsNotAField:
    def test_get_object_names_the_step_that_counts(self, loop_and_user):
        loop, user = loop_and_user
        _, script = _run(
            loop, user, "How many transactions does Ada Okafor have?",
            '{"step": "get_object", "object_type": "Transaction", "object_ids": [1, 2], '
            '"field_names": ["count"]}',
        )

        told = script.shown[1].replace('\\"', '"')
        assert '"step": "aggregate_object", "object_type": "Transaction"' in told

    def test_get_field_is_refused_too_rather_than_answering_none(self, loop_and_user):
        """The bench's second move. get_object refused "count";
        get_field did not, and returned None, which reads as an empty
        field rather than a mistake."""
        loop, user = loop_and_user
        _, script = _run(
            loop, user, "How many transactions does Ada Okafor have?",
            '{"step": "get_field", "object_type": "Transaction", "object_id": 1, '
            '"field_name": "count"}',
        )

        assert "has no field(s) 'count'" in script.shown[1]
        assert "aggregate_object" in script.shown[1]

    def test_an_unknown_field_that_is_not_a_count_gets_no_count_advice(self, loop_and_user):
        """THE CONTROL: the hint is for the belief "count is a field",
        not for every typo."""
        loop, user = loop_and_user
        _, script = _run(
            loop, user, "What is transaction 1's colour?",
            '{"step": "get_field", "object_type": "Transaction", "object_id": 1, '
            '"field_name": "colour"}',
        )

        assert "has no field(s) 'colour'" in script.shown[1]
        assert "To count or total" not in script.shown[1]


class TestTheNudgeSaysWhatIsMissing:
    GATHERED = [
        {"step": "get_field", "object_type": "Transaction", "object_id": 1,
         "field_name": "category", "result": "books"},
        {"step": "get_field", "object_type": "Transaction", "object_id": 2,
         "field_name": "amount", "result": 199},
        {"step": "get_field", "object_type": "Transaction", "object_id": 2,
         "field_name": "category", "result": "hardware"},
    ]

    def test_it_names_the_object_and_the_field(self):
        assert "Missing: 1 lacks amount" in _detect_asymmetry(self.GATHERED)

    def test_it_gives_the_one_step_that_fills_it(self):
        assert ('{"step": "get_object", "object_type": "Transaction", "object_ids": [1], '
                '"field_names": ["amount"]}') in _detect_asymmetry(self.GATHERED)

    def test_the_complete_object_is_not_named_as_missing_anything(self):
        """THE BENCH'S MISTAKE was re-reading object 2."""
        assert "2 lacks" not in _detect_asymmetry(self.GATHERED)

    def test_objects_missing_the_same_fields_share_one_step(self):
        gathered = [
            {"step": "get_field", "object_type": "T", "object_id": i,
             "field_name": "a", "result": 1} for i in (1, 2, 3)
        ] + [{"step": "get_field", "object_type": "T", "object_id": 3,
              "field_name": "b", "result": 1}]

        message = _detect_asymmetry(gathered)

        assert "1, 2 lacks b" in message
        assert message.count('"step": "get_object"') == 1


class TestTheIdGuardIsConservative:
    """Integer ids collide across types: SupportTicket 1 and Transaction
    1 both exist. An id that ALSO arrived some way that could make it
    this type's must never be refused."""

    SCHEMA = {"Transaction": {"fields": {}}, "SupportTicket": {"fields": {}},
              "Customer": {"fields": {}}}

    def _check(self, gathered, ids=(1,)):
        from core.agent.agentic_loop import _reject_ids_of_another_type

        _reject_ids_of_another_type("Transaction", list(ids), gathered, self.SCHEMA)

    def test_an_id_also_seen_in_a_link_result_is_allowed(self):
        self._check([
            {"step": "search_object", "object_type": "SupportTicket", "result": [1]},
            {"step": "get_field", "object_type": "Customer", "object_id": "c",
             "field_name": "transactions", "result": [1]},
        ])

    def test_an_id_already_read_as_this_type_is_allowed(self):
        self._check([
            {"step": "search_object", "object_type": "SupportTicket", "result": [1]},
            {"step": "get_field", "object_type": "Transaction", "object_id": 1,
             "field_name": "amount", "result": 5},
        ])

    def test_an_id_seen_only_as_another_type_is_refused(self):
        """THE CONTROL for the two above."""
        with pytest.raises(ValueError, match="is a SupportTicket id"):
            self._check([
                {"step": "search_object", "object_type": "SupportTicket", "result": [1]},
            ])

    def test_an_id_never_seen_at_all_is_left_to_the_mediator(self):
        """Not this guard's business: it knows only what the run holds."""
        self._check([])


class TestARefusedStepIsNotAlreadyHad:
    """THE SECOND BENCH RUN: refused `transaction_id` (no such field), the
    model sent the same step twice more and was told both times "You
    already have this" -- false; a refused step gathered nothing."""

    ASK_FOR_THE_ID = ('{"step": "get_object", "object_type": "Transaction", "object_ids": [1, 2], '
                      '"field_names": ["transaction_id"]}')

    def test_the_repeat_is_refused_with_its_reason_not_called_a_duplicate(self, loop_and_user):
        loop, user = loop_and_user
        result, script = _run(loop, user, "How many transactions does Ada Okafor have?",
                              self.ASK_FOR_THE_ID, self.ASK_FOR_THE_ID)

        assert "You already have this" not in "".join(script.shown)
        assert result.stop_reason == "invalid_steps"

    def test_a_step_that_DID_gather_is_still_a_duplicate(self, loop_and_user):
        """THE CONTROL: only refusals are forgotten."""
        loop, user = loop_and_user
        read = ('{"step": "get_field", "object_type": "Transaction", "object_id": 1, '
                '"field_name": "amount"}')
        _, script = _run(loop, user, "What is transaction 1's amount?", read, read)

        assert "You already have this" in script.shown[2]

    def test_asking_for_the_id_field_says_the_ids_are_already_in_hand(self, loop_and_user):
        loop, user = loop_and_user
        _, script = _run(loop, user, "How many transactions does Ada Okafor have?",
                         self.ASK_FOR_THE_ID)

        told = script.shown[1].replace('\\"', '"')
        assert "'transaction_id' is the id itself" in told
        assert '"aggregate": "count"' in told


class TestTheBenchCanShowItsSteps:
    def test_each_entry_is_one_line_with_notes_where_they_happened(self):
        from scripts.llm_bench import describe_gathered

        lines = describe_gathered([
            {"step": "search_object", "object_type": "Customer",
             "filter": {"name": "Ada"}, "result": ["cust_001"]},
            {"step": "rejected_duplicate", "note": "You already have this"},
            {"step": "get_field", "object_type": "Transaction", "object_id": 1,
             "field_name": "amount", "result": 49.99},
        ])

        assert lines == [
            "search_object Customer {'name': 'Ada'} -> ['cust_001']",
            "rejected_duplicate: You already have this",
            "get_field Transaction 1 amount -> 49.99",
        ]


class TestThePostponedFinish:
    """THE THIRD BENCH RUN, with --show-steps: dependent_choice tried to
    finish, was nudged "1 lacks amount", read exactly that -- then read
    it AGAIN, was refused as a duplicate, and ran out of hops holding a
    complete answer. Replayed from its printed steps."""

    BENCH = (
        '{"step": "search_object", "object_type": "Customer", "filter": {"customer_id": "cust_001"}}',
        '{"step": "get_field", "object_type": "Customer", "object_id": "cust_001", "field_name": "transactions"}',
        '{"step": "get_field", "object_type": "Transaction", "object_id": 1, "field_name": "category"}',
        '{"step": "get_field", "object_type": "Transaction", "object_id": 2, "field_name": "category"}',
        '{"step": "get_field", "object_type": "Transaction", "object_id": 2, "field_name": "amount"}',
        '{"step": "finish"}',
        '{"step": "get_field", "object_type": "Transaction", "object_id": 1, "field_name": "amount"}',
        # What the model sent next. It must never be asked for it.
        '{"step": "get_field", "object_type": "Transaction", "object_id": 1, "field_name": "amount"}',
    )

    def test_the_finish_it_asked_for_is_granted_once_the_gap_is_closed(self, loop_and_user):
        loop, user = loop_and_user
        result, script = _run(loop, user, "What category was Ada Okafor's largest transaction?",
                              *self.BENCH)

        assert result.stop_reason == "finished"
        assert len(script.shown) == 7
        notes = [item["note"] for item in result.gathered if item.get("step") == "completeness_check"]
        assert notes == ["Gap filled; everything is gathered."]

    def test_a_finish_fabricated_from_an_unusable_reply_is_not_resumed(self, loop_and_user):
        """THE CONTROL: the model never decided to finish, so closing
        the gap does not decide it for it."""
        loop, user = loop_and_user
        replies = list(self.BENCH[:5]) + ['{"step": "teleport_object"}', self.BENCH[6]]
        _, script = _run(loop, user, "What category was Ada Okafor's largest transaction?",
                         *replies)

        assert len(script.shown) > 7
