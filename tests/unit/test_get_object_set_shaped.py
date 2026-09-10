"""
Tests for get_object reading several objects in one step.

THE PROBLEM THIS SOLVES is the N+1 pattern, measured on the CPU-only
deployment: a search returns [1, 2], then one hop per id to read one
field from each. A hop was ~193 seconds there, so two ids cost 6.4
minutes to read two numbers.

DataLoader -- the usual fix -- does not apply: it batches loads made
within one tick, invisibly, and our caller is a model that must emit
each read as its own round trip. So the vocabulary changes instead,
shaped after Palantir's ObjectSet: a set of ids plus a select of which
fields, with the single-object case as the special case.
"""

import pytest

from core.agent.agentic_loop import MAX_OBJECT_IDS, AgentLoop
from core.llm.agent_step_prompt import _build_system_prompt


class _FakeMediator:
    def __init__(self):
        self.calls = []

    def get_object(self, user_record, object_type, object_id, field_names):
        self.calls.append((object_type, object_id, tuple(field_names)))
        return {name: f"{object_id}-{name}" for name in field_names}


def _run(step):
    mediator = _FakeMediator()
    loop = AgentLoop.__new__(AgentLoop)
    loop.mediator = mediator
    gathered: list[dict] = []
    loop._step_get_object(step, "alice", {}, gathered)
    return mediator, gathered


def test_one_step_reads_every_named_object():
    mediator, gathered = _run({
        "step": "get_object", "object_type": "Transaction",
        "object_ids": [1, 2], "field_names": ["amount"],
    })

    assert [c[1] for c in mediator.calls] == [1, 2]
    assert [g["result"] for g in gathered] == ["1-amount", "2-amount"]


def test_every_object_and_field_is_recorded_as_its_own_get_field_entry():
    # Downstream -- synthesis, the trace, the prompt's own history --
    # must see the same shape whether a field was fetched singly or in
    # a batch. Two objects times two fields is four entries.
    _, gathered = _run({
        "step": "get_object", "object_type": "Transaction",
        "object_ids": [1, 2], "field_names": ["amount", "currency"],
    })

    assert len(gathered) == 4
    assert all(g["step"] == "get_field" for g in gathered)
    assert {(g["object_id"], g["field_name"]) for g in gathered} == {
        (1, "amount"), (1, "currency"), (2, "amount"), (2, "currency"),
    }


def test_the_single_object_form_still_works_unchanged():
    # Additive, not a migration: a step naming one object_id is the
    # common case and must keep working exactly as before.
    mediator, gathered = _run({
        "step": "get_object", "object_type": "Customer",
        "object_id": "cust_001", "field_names": ["name"],
    })

    assert mediator.calls == [("Customer", "cust_001", ("name",))]
    assert gathered[0]["object_id"] == "cust_001"


def test_authorization_is_not_batched_along_with_the_read():
    # "Batch read" invites the assumption that the checks were batched
    # too. They are not: mediator.get_object() is called once per
    # object, and it is itself a per-field loop running every RBAC,
    # MAC and audit check individually. The saving is round trips to
    # the MODEL, not work in the mediator.
    mediator, _ = _run({
        "step": "get_object", "object_type": "Transaction",
        "object_ids": [1, 2, 3], "field_names": ["amount"],
    })

    assert len(mediator.calls) == 3, "one mediator call per object, never one for the set"


def test_too_many_ids_is_a_named_refusal_not_a_short_read():
    # Never a silent truncation. Answering about some of a list and
    # quietly skipping the rest is the exact failure the prompt already
    # warns the model against, and Palantir errors with
    # ObjectsExceededLimit rather than returning a short page.
    with pytest.raises(ValueError, match="exceeds the limit"):
        _run({
            "step": "get_object", "object_type": "Transaction",
            "object_ids": list(range(MAX_OBJECT_IDS + 1)), "field_names": ["amount"],
        })


def test_exactly_the_limit_is_allowed():
    # The boundary, so the cap is off-by-one-proof in the direction
    # that would silently refuse legitimate work.
    mediator, _ = _run({
        "step": "get_object", "object_type": "Transaction",
        "object_ids": list(range(MAX_OBJECT_IDS)), "field_names": ["amount"],
    })

    assert len(mediator.calls) == MAX_OBJECT_IDS


@pytest.mark.parametrize("bad", [[], "not-a-list", {}, None])
def test_a_malformed_object_ids_is_rejected_rather_than_read_as_nothing(bad):
    with pytest.raises(ValueError, match="non-empty list"):
        _run({
            "step": "get_object", "object_type": "Transaction",
            "object_ids": bad, "field_names": ["amount"],
        })


def test_the_prompt_teaches_the_batched_shape_not_the_n_plus_1_one():
    # The prompt used to contain a worked example instructing one
    # get_field per id -- the model was doing exactly what it was told.
    # A vocabulary the prompt does not teach is a vocabulary the model
    # will not use.
    prompt = _build_system_prompt({}, [], False, {}, [])

    assert '"object_ids"' in prompt
    assert '{"step": "get_field", "object_type": "Transaction", "object_id": 1' not in prompt


# --- the parsing side ---
#
# The tests above call _step_get_object directly, which proves the loop
# reads what it is given but not that a model's JSON survives
# validation. These cover the other half.

from core.llm.agent_step_prompt import next_step  # noqa: E402


class _Says:
    """An LLMAdapter that returns one fixed response."""

    def __init__(self, content):
        self.content = content

    def chat(self, *args, **kwargs):
        return self.content


def _parse(content):
    return next_step(_Says(content), "q", {}, [], [], False, {})


def test_a_step_naming_object_ids_survives_validation():
    step = _parse('{"step": "get_object", "object_type": "Transaction", '
                  '"object_ids": [1, 2], "field_names": ["amount"]}')

    assert step["step"] == "get_object"
    assert step["object_ids"] == [1, 2]
    assert "object_id" not in step, "the singular key must not be invented alongside it"


def test_a_step_naming_one_object_id_still_survives_validation():
    step = _parse('{"step": "get_object", "object_type": "Customer", '
                  '"object_id": "cust_001", "field_names": ["name"]}')

    assert step["object_id"] == "cust_001"
    assert "object_ids" not in step


@pytest.mark.parametrize("bad", ["[]", '"cust_001"', "{}"])
def test_a_malformed_object_ids_fails_closed_to_finish(bad):
    # Fails CLOSED, like every other malformed step: the model gets the
    # same clear recovery signal rather than a confusing no-op. An
    # empty list would otherwise produce zero gathered entries.
    step = _parse('{"step": "get_object", "object_type": "Transaction", '
                  f'"object_ids": {bad}, "field_names": ["amount"]}}')

    assert step["step"] == "finish"


def test_object_ids_present_but_field_names_missing_fails_closed():
    step = _parse('{"step": "get_object", "object_type": "Transaction", '
                  '"object_ids": [1, 2]}')

    assert step["step"] == "finish"


# --- the whole loop, which is where this broke ---
#
# THE GAP THIS CLOSES. Everything above tests _step_get_object and the
# step parser. Nothing tested the path BETWEEN them -- run()'s own
# duplicate detection, which called step["object_id"] directly in two
# places. Both raised KeyError on the first real query:
#
#   File "core/agent/agentic_loop.py", line 124, in _step_signature
#     return ("get_object", step["object_type"], step["object_id"], ...)
#   KeyError: 'object_id'
#
# Two unit tests either side of a crash is not coverage of the thing
# between them.

from core.agent.agentic_loop import _object_ids_in, _step_signature  # noqa: E402


class _Scripted:
    """An LLMAdapter that returns each queued response in turn."""

    def __init__(self, *responses):
        self.responses = list(responses)

    def chat(self, *args, **kwargs):
        return self.responses.pop(0) if self.responses else '{"step": "finish"}'


def test_a_set_shaped_step_survives_a_whole_run():
    # The regression test proper. Goes through run(), so it exercises
    # signature building and duplicate recording, not just the handler.
    mediator = _FakeMediator()
    mediator.visible_schema = lambda user_record: {}
    loop = AgentLoop(
        client=_Scripted(
            '{"step": "get_object", "object_type": "Transaction",'
            ' "object_ids": [1, 2], "field_names": ["amount"]}',
            '{"step": "finish"}',
        ),
        mediator=mediator,
    )

    result = loop.run("alice", "what are the amounts?")

    assert len(result.gathered) == 2
    assert [g["object_id"] for g in result.gathered] == [1, 2]


def test_a_signature_can_be_built_for_either_form():
    # _step_signature must not care which key was used. It raised
    # KeyError on the set form.
    plural = _step_signature({
        "step": "get_object", "object_type": "T", "object_ids": [1, 2],
        "field_names": ["amount"],
    })
    singular = _step_signature({
        "step": "get_object", "object_type": "T", "object_id": 1,
        "field_names": ["amount"],
    })

    assert plural != singular
    assert hash(plural) and hash(singular), "signatures must stay hashable"


def test_naming_the_same_objects_in_a_different_order_is_the_same_request():
    # frozenset over ids for the same reason field_names already used
    # one: order is not part of what was asked.
    first = _step_signature({"step": "get_object", "object_type": "T",
                             "object_ids": [1, 2], "field_names": ["a"]})
    second = _step_signature({"step": "get_object", "object_type": "T",
                              "object_ids": [2, 1], "field_names": ["a"]})

    assert first == second


def test_a_later_get_field_on_an_already_batched_object_is_a_duplicate():
    # run() records a get_field-shaped signature per object per field,
    # so following a batch with a single read of one of those fields is
    # caught. Before the fix this recorded ONE entry for the whole set.
    mediator = _FakeMediator()
    mediator.visible_schema = lambda user_record: {}
    loop = AgentLoop(
        client=_Scripted(
            '{"step": "get_object", "object_type": "Transaction",'
            ' "object_ids": [1, 2], "field_names": ["amount"]}',
            '{"step": "get_field", "object_type": "Transaction",'
            ' "object_id": 2, "field_name": "amount"}',
            '{"step": "finish"}',
        ),
        mediator=mediator,
        max_consecutive_duplicates=1,
    )

    loop.run("alice", "amounts?")

    assert len(mediator.calls) == 2, "the repeated read must not reach the mediator a third time"


def test_the_id_helper_is_the_one_place_the_two_keys_are_resolved():
    assert _object_ids_in({"object_ids": [1, 2]}) == [1, 2]
    assert _object_ids_in({"object_id": "cust_001"}) == ["cust_001"]
