"""
Three findings from the second audit batch: F-15, F-22 with F-23, and
F-14.

WHAT THEY HAVE IN COMMON is the failure mode, not the code: each is a
case where something outside Elysium behaves slightly unlike the happy
path -- a model answers with a bare string, a backend returns 500, an
author uses a parameter in a place the validator forgot to look -- and
Elysium turned it into a crash, a leak, or a wrong refusal.
"""

import logging

import pytest
import requests

from adapters.ollama_adapter import OllamaAdapter
from core.llm import synthesis_prompt
from core.llm.agent_step_prompt import UNPARSEABLE_REPLY, next_step
from core.llm.interface import LLMUnavailable
from core.ontology.action_types import validate_action_types

# A schema complete enough to build a real system prompt from. A
# MINIMAL ONE HIDES THE BUG: the first reproduction of F-15 used a
# two-key schema, which raised KeyError while BUILDING the prompt, was
# caught by the same handler, and returned finish for every input --
# so every shape looked fine and the crash looked fixed.
SCHEMA = {
    "Customer": {
        "display_name": "Customer",
        "plural_display_name": "Customers",
        "description": "A customer.",
        "id_field": "customer_id",
        "fields": {
            "region": {"type": "data", "display_name": "Region",
                        "visibility": "normal", "status": "active"},
        },
    },
}


class _Answering:
    """A model that answers with whatever it was given."""

    def __init__(self, payload):
        self.payload = payload

    def chat(self, *args, **kwargs):
        return self.payload

    def model_name(self):
        return "fake"


class TestF15ValidJsonThatIsNotAnObject:
    """`[1, 2]`, `"finish"`, `42`, `null` and `true` all parse, and the
    next line asked them for a key -- an AttributeError that became a
    500 and DISCARDED THE WHOLE RUN, including everything already
    gathered, because a model answered with a bare string."""

    @pytest.mark.parametrize("payload", ['[1, 2]', '"finish"', '42', 'null', 'true',
                                          '[{"step": "finish"}]'])
    def test_each_shape_finishes_instead_of_crashing(self, payload):
        step = next_step(_Answering(payload), "who?", SCHEMA, [], [], False, {})

        # NAMES ITS CAUSE (LB-3). Finishing here is right -- there may be
        # real gathered context -- but it used to be indistinguishable
        # from the model deciding it was done, so the caller was told a
        # complete answer had been produced from an unusable reply.
        assert step == {"step": "finish", "fallback": UNPARSEABLE_REPLY}

    def test_an_object_still_works(self):
        step = next_step(_Answering('{"step": "finish"}'), "who?", SCHEMA, [], [], False, {})

        assert step == {"step": "finish"}

    def test_what_was_gathered_is_not_discarded(self, caplog):
        """The cost of the crash was never the exception -- it was the
        run: a user's question, several reads already done, and a 500
        instead of an answer."""
        gathered = [{"step": "search_object", "result": ["cust_001"]}]

        with caplog.at_level(logging.WARNING):
            step = next_step(_Answering('"finish"'), "who?", SCHEMA, gathered, [], False, {})

        assert step == {"step": "finish", "fallback": UNPARSEABLE_REPLY}
        assert gathered == [{"step": "search_object", "result": ["cust_001"]}]


class _Response:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error")

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


@pytest.fixture
def adapter(monkeypatch):
    def answering(response):
        monkeypatch.setattr(requests, "post", lambda *args, **kwargs: response)
        return OllamaAdapter("m", {"base_url": "http://localhost:11434/api/chat"})
    return answering


class TestF22TheAdapterTranslatesAtItsBoundary:
    """A caller that handles LLMUnavailable should never meet
    requests.HTTPError, a KeyError, or a JSON parse error: those are
    facts about the library this adapter happens to use."""

    def test_an_http_error_becomes_LLMUnavailable(self, adapter):
        with pytest.raises(LLMUnavailable, match="answered 500"):
            adapter(_Response(500, {})).chat("system", "user")

    def test_a_missing_model_becomes_LLMUnavailable(self, adapter):
        """Ollama answers 200 with {"error": ...} for a model it cannot
        load, which used to raise KeyError('message') -- reading, to
        everything upstream, like a bug in Elysium."""
        response = _Response(200, {"error": "model 'llama9' not found"})

        with pytest.raises(LLMUnavailable, match="llama9"):
            adapter(response).chat("system", "user")

    def test_a_body_that_is_not_json_becomes_LLMUnavailable(self, adapter):
        """A proxy's error page, most often -- which is exactly when a
        deployment is already confused."""
        response = _Response(200, ValueError("Expecting value: line 1 column 1"))

        with pytest.raises(LLMUnavailable, match="not JSON"):
            adapter(response).chat("system", "user")

    def test_a_good_answer_is_returned(self, adapter):
        response = _Response(200, {"message": {"content": "hello"}})

        assert adapter(response).chat("system", "user") == "hello"

    def test_a_network_failure_still_becomes_LLMUnavailable(self, adapter, monkeypatch):
        def refuse(*args, **kwargs):
            raise requests.ConnectionError("connection refused")
        monkeypatch.setattr(requests, "post", refuse)

        with pytest.raises(LLMUnavailable, match="Could not reach"):
            OllamaAdapter("m", {"base_url": "http://x/api/chat"}).chat("system", "user")


class TestF23SynthesisCatchesWhatAdaptersRaise:
    """It caught requests.RequestException -- one adapter's library
    exception -- so once the adapters translated failures at their
    boundary, THE HANDLER BECAME UNREACHABLE and a real outage
    propagated out of synthesis as a 500. Correct, and dead."""

    class _Down:
        def chat(self, *args, **kwargs):
            raise LLMUnavailable("Could not reach the model at http://localhost:11434")

        def model_name(self):
            return "m"

    def test_an_outage_produces_an_answer_rather_than_an_exception(self):
        answer = synthesis_prompt.synthesize_insight(self._Down(), "who is Ada?", ["a record"])

        assert "could not be generated" in answer

    def test_and_does_not_leak_the_backend_address(self):
        """The reason the handler exists at all: a RequestException's
        own str() carries host and port straight to the frontend."""
        answer = synthesis_prompt.synthesize_insight(self._Down(), "who is Ada?", ["a record"])

        assert "11434" not in answer and "localhost" not in answer


TICKET_TYPES = {
    "Ticket": {
        "id_field": "ticket_id",
        "security": {"field": "region"},
        "storage": {"silo": "s", "table": "t", "id_column": "ticket_id"},
        "fields": {"ticket_id": {"type": "data"}, "status": {"type": "data"},
                    "region": {"type": "data"}},
    },
}


def _close_ticket(**extra):
    return {
        "close_ticket": {
            "display_name": "Close",
            "description": "Close a ticket.",
            "affected_object_types": ["Ticket"],
            "parameters": {
                "ticket": {"type": "object_reference", "object_type": "Ticket"},
                "expected_status": {"type": "string"},
            },
            "sub_writes": [{
                "operation": "update",
                "object_type": "Ticket",
                "object_id": "parameter.ticket",
                "mutations": [{"set": {"property": "status", "value": "closed"}}],
                **extra,
            }],
        },
    }


class TestF14AParameterUsedOnlyByACriterion:
    """The validator looked for parameter references in a sub-write's
    object_id and mutations, and for criteria it read the ACTION level
    -- one level above where WriteMediator reads them. A parameter used
    only by a criterion was therefore reported as declared-but-unused,
    so an author would delete the declaration and break the criterion,
    with the validator having told them to.

    ALREADY FIXED when these tests were written, and left untested,
    which is how a fix becomes a regression. These hold it.
    """

    def test_a_parameter_used_only_in_a_sub_write_criterion_is_accepted(self):
        actions = _close_ticket(submission_criteria=[
            {"property": "status", "operator": "equals", "value": "parameter.expected_status"},
        ])

        validate_action_types(actions, TICKET_TYPES)

    def test_a_parameter_used_only_in_an_ACTION_level_criterion_is_accepted(self):
        """Nothing forbids a deployment putting criteria there, and a
        validator that read only half the file would be its own version
        of this bug."""
        actions = _close_ticket()
        actions["close_ticket"]["submission_criteria"] = [
            {"property": "status", "operator": "equals", "value": "parameter.expected_status"},
        ]

        validate_action_types(actions, TICKET_TYPES)

    def test_a_parameter_used_in_a_mutation_value_is_accepted(self):
        actions = _close_ticket()
        actions["close_ticket"]["sub_writes"][0]["mutations"] = [
            {"set": {"property": "status", "value": "parameter.expected_status"}},
        ]

        validate_action_types(actions, TICKET_TYPES)

    def test_a_GENUINELY_unused_parameter_is_still_rejected(self):
        """The check has to keep working: a declared parameter nothing
        uses is usually a rename that happened on one side."""
        with pytest.raises(ValueError, match="declared but never referenced"):
            validate_action_types(_close_ticket(), TICKET_TYPES)
