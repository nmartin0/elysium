"""A transient failure is retried. Nothing else is.

AL-5: no retries anywhere in the adapters -- a single refused
connection ended a whole query, discarding every hop already paid for.

THE RISK IN FIXING IT is retrying the wrong thing. LLMUnavailable
covers four events and only one is worth another attempt, so most of
this file is about what must NOT be retried:

    transport failure       retried
    deadline already passed NOT -- there is no time to retry in, and
                            a retry loop reports the wrong cause
    unparseable response    NOT -- temperature 0 returns the same bytes
    HTTP 4xx                NOT -- the request is wrong, not unlucky

A test suite for a retry that only proves "it retries" is how a retry
of a 4xx ships.
"""

import pytest

from core.llm.interface import LLMUnavailable
from core.llm.retrying_adapter import RetryingLLMAdapter


class Scripted:
    """Raises what it is told to, then answers."""

    max_concurrent_requests = 4

    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0
        self.seen = []

    def chat(self, system_prompt, user_message, json_mode=False,
             temperature=None, *, deadline=None, usage=None):
        self.calls += 1
        self.seen.append(
            {"system_prompt": system_prompt, "user_message": user_message,
             "json_mode": json_mode, "temperature": temperature,
             "deadline": deadline, "usage": usage}
        )
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _transport(msg="connection refused"):
    return LLMUnavailable(msg, retryable=True)


def _terminal(msg="deadline passed"):
    return LLMUnavailable(msg)


def _retrying(wrapped, **kw):
    kw.setdefault("sleep", lambda _: None)
    return RetryingLLMAdapter(wrapped, **kw)


def test_a_transient_failure_is_retried_and_the_answer_returned():
    backend = Scripted(_transport(), "the answer")

    assert _retrying(backend).chat("sys", "user") == "the answer"
    assert backend.calls == 2


def test_it_gives_up_after_the_configured_attempts():
    backend = Scripted(_transport(), _transport(), _transport())

    with pytest.raises(LLMUnavailable):
        _retrying(backend, attempts=3).chat("sys", "user")
    assert backend.calls == 3


def test_a_passed_deadline_is_not_retried():
    """THE TRAP THIS ITEM MOST EASILY FALLS INTO.

    call_timeout() raises LLMUnavailable the moment the deadline has
    gone, before anything is sent. Retrying that burns what is left of
    a budget that is already spent, and the caller is finally told
    about the last attempt rather than about the deadline.
    """
    backend = Scripted(_terminal("The request's deadline passed"))

    with pytest.raises(LLMUnavailable, match="deadline"):
        _retrying(backend).chat("sys", "user")
    assert backend.calls == 1, "a passed deadline was retried"


def test_an_unparseable_response_is_not_retried():
    """Calls are made at temperature 0, so the same prompt returns the
    same unusable bytes. Retrying is a slower way to fail."""
    backend = Scripted(_terminal("model returned invalid JSON"))

    with pytest.raises(LLMUnavailable):
        _retrying(backend).chat("sys", "user")
    assert backend.calls == 1


def test_the_original_cause_survives_the_retries():
    """Not replaced with "failed after N attempts", which would hide
    which of four failures happened."""
    backend = Scripted(_transport("connection refused by 127.0.0.1"),
                       _transport("connection refused by 127.0.0.1"))

    with pytest.raises(LLMUnavailable, match="connection refused by 127.0.0.1"):
        _retrying(backend, attempts=2).chat("sys", "user")


def test_every_argument_is_passed_through_unchanged_on_a_retry():
    """A retry must send the SAME request.

    The wrapper re-invokes with its own locals, so a mis-ordered
    positional would quietly send json_mode where temperature belongs
    -- and only on the retry path, which no happy-path test reaches.
    """
    backend = Scripted(_transport(), "ok")
    usage = object()

    _retrying(backend).chat("sys", "user", True, 0.0,
                            deadline=123.0, usage=usage)

    assert backend.calls == 2
    assert backend.seen[0] == backend.seen[1]
    assert backend.seen[1] == {
        "system_prompt": "sys", "user_message": "user", "json_mode": True,
        "temperature": 0.0, "deadline": 123.0, "usage": usage,
    }


def test_a_successful_call_is_not_slept_on():
    """Backoff must not be paid by the requests that are working."""
    slept = []
    backend = Scripted("immediate")

    RetryingLLMAdapter(backend, sleep=slept.append).chat("sys", "user")

    assert slept == []


def test_backoff_is_slept_once_per_retry():
    slept = []
    backend = Scripted(_transport(), _transport(), "ok")

    RetryingLLMAdapter(backend, attempts=3, backoff_seconds=0.25,
                       sleep=slept.append).chat("sys", "user")

    assert slept == [0.25, 0.25]


def test_no_sleep_after_the_final_failure():
    """A wrapper that sleeps then raises makes the caller wait for
    nothing -- and on the deadline path, wait past it."""
    slept = []
    backend = Scripted(_transport(), _transport())

    with pytest.raises(LLMUnavailable):
        RetryingLLMAdapter(backend, attempts=2, sleep=slept.append).chat("s", "u")

    assert len(slept) == 1, "slept after the last attempt"


def test_it_declares_the_wrapped_adapters_concurrency():
    """The Protocol requires the attribute, and this class is itself
    used as an LLMAdapter -- including as something the concurrency
    wrapper may wrap."""
    assert _retrying(Scripted("ok")).max_concurrent_requests == 4


def test_zero_attempts_is_refused_at_construction():
    """Rather than silently never calling the model at all."""
    with pytest.raises(ValueError):
        RetryingLLMAdapter(Scripted("ok"), attempts=0)


def test_a_plain_LLMUnavailable_is_not_retryable():
    """The DEFAULT is what protects every raise site that has not
    thought about this -- including any added later, and the two in
    the Claude SDK adapter which are not transport failures."""
    assert LLMUnavailable("anything").retryable is False
