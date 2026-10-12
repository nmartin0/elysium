"""An aggregate over a set the search stopped reading (R64).

THE GAP: the HTTP path learned (R39) to say when a set was cut at the
scan ceiling; the agent did not, so a truncated count reached the model
as a bare number it then stated as fact. Now a count says "at least N"
-- a lower bound is still true -- and any other aggregate is refused,
because a sum or an average over part of a set bounds nothing.

THE CEILING IS LOWERED TO 2 for these tests, through the module the
mediator reads it from at call time. The fixture user sees more than
two transactions, so every read below is genuinely cut short.
"""

import contextlib
import io

import pytest

import core.ontology.mediator as mediator_module
from core.deployment_loader import build_generation
from core.functions.ontology_access import OntologyAccess
from core.intermediate_layer.auth import resolve_user_record


class Script:
    max_concurrent_requests = 1

    def __init__(self, *replies):
        self.replies = iter(replies)

    def chat(self, *args, **kwargs):
        return next(self.replies, '{"step": "finish"}')


@pytest.fixture
def generation_and_user(synced_deployment):
    generation = build_generation(synced_deployment.config_dir, synced_deployment.data_dir,
                                  synced_deployment.log_dir)
    user = resolve_user_record(generation.config.users, "user_alice",
                               generation.config.security_attribute)
    return generation, user


def _lower_the_ceiling(monkeypatch):
    monkeypatch.setattr(mediator_module, "MAX_SEARCH_SCAN", 2)


def _gathered(generation, user, step):
    generation.loop.client = Script(step)
    with contextlib.redirect_stdout(io.StringIO()):
        return generation.loop.run(user, "How many transactions are there?").gathered


COUNT = '{"step": "aggregate_object", "object_type": "Transaction", "filter": {}, "aggregate": "count"}'
TOTAL = ('{"step": "aggregate_object", "object_type": "Transaction", "filter": {}, '
         '"aggregate": "sum", "field_name": "amount"}')


class TestTheAgent:
    def test_a_short_count_is_a_lower_bound(self, generation_and_user, monkeypatch):
        _lower_the_ceiling(monkeypatch)
        generation, user = generation_and_user

        (entry,) = [item for item in _gathered(generation, user, COUNT)
                    if item.get("step") == "aggregate_object"]

        assert str(entry["result"]).startswith("at least ")

    def test_a_short_sum_is_refused_with_what_to_do(self, generation_and_user, monkeypatch):
        _lower_the_ceiling(monkeypatch)
        generation, user = generation_and_user

        notes = [item["note"] for item in _gathered(generation, user, TOTAL)
                 if item.get("step") == "rejected_invalid_step"]

        assert notes and "could not be computed" in notes[0]
        assert "Add a filter" in notes[0]

    def test_a_whole_count_is_a_plain_number(self, generation_and_user):
        """THE CONTROL: with the real ceiling nothing is cut, and the
        count is the number it always was."""
        generation, user = generation_and_user

        (entry,) = [item for item in _gathered(generation, user, COUNT)
                    if item.get("step") == "aggregate_object"]

        assert isinstance(entry["result"], int) and entry["result"] > 2


class TestAFunction:
    def test_a_short_count_is_refused(self, generation_and_user, monkeypatch):
        _lower_the_ceiling(monkeypatch)
        """A function computes with the int it is given and has nowhere
        to put "at least", so it gets no number rather than a short one."""
        generation, user = generation_and_user
        access = OntologyAccess(generation.mediator, user, ["Transaction"])

        with pytest.raises(ValueError, match="would be short"):
            access.count("Transaction")
        with pytest.raises(ValueError, match="would be short"):
            access.aggregate("Transaction", "sum", field="amount")

    def test_a_whole_count_is_returned(self, generation_and_user):
        """THE CONTROL."""
        generation, user = generation_and_user
        access = OntologyAccess(generation.mediator, user, ["Transaction"])

        assert access.count("Transaction") > 2
