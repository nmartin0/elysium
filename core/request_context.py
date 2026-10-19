"""What request a piece of work belongs to.

ONE OBJECT, THREADED EXPLICITLY, rather than a context variable. That
choice was made against the grain of the usual advice -- "manually
passing a trace id through every call is a significant anti-pattern"
-- and for a reason specific to how Elysium runs.

Elysium is SYNCHRONOUS Python on an explicit ThreadPoolExecutor, not
asyncio. A pooled worker thread keeps whatever context it was last
left with, so a task landing on a worker without setting one inherits
the previous request's. In an audit log that is not a bug, it is one
user's reads attributed to another, and it fails SILENTLY.

Forgetting an explicit parameter raises TypeError. For a system whose
value rests on a trustworthy audit trail, "will not start" beats
"quietly attributes reads to the wrong person".

That argument gets stronger, not weaker, as Elysium parallelises.
Multi-silo reads and mirror sync fan-out are both thread-pool
submissions INSIDE a request; each would need copy_context() at every
submit site, and forgetting one gives an empty or wrong trail with no
error. Contextvars would trade a parameter for a discipline, and the
discipline is unenforceable.

FROZEN, following the shape the field has settled on for exactly this
-- "an immutable frozen dataclass ... maintaining immutability and
thread safety", and the general rule to "treat context data as
immutable wherever possible". An object shared across threads that
nobody can mutate needs no lock and cannot be half-updated.

TYPED FIELDS, NOT A DICT. "Avoid generic map or any types" is the
usual guidance and it matters here: a dict would let any caller stash
anything, and this object is threaded through the authorization path,
where the set of things travelling is exactly what should be
reviewable.

WHY AN OBJECT RATHER THAN A BARE ID. Two other planned features need
request-scoped data at the same depth -- a wall-clock deadline for the
agent loop, and token accounting from the LLM adapter. Go's own
context carries cancellation, deadlines and request-scoped values
together for the same reason. One channel built once beats three
separate ones, each needing its own propagation.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CallRecord:
    """One model call, as far as its provider said, and how long it took.

    WHERE A QUESTION'S SECONDS GO, which nothing recorded until 19
    October: the bench timed whole calls and never the answer, and a
    query logged token totals. On a CPU the two halves of a call cost
    very differently -- the deployment's own measurements are about 5.4
    tokens a second READING a prompt and 1.5 WRITING a reply -- so "a
    call took 50 s" cannot say which to make smaller.

    READING is the provider's prompt evaluation (prefill), WRITING its
    generation, LOADING the model coming into memory. Each is None when
    the provider did not say: Ollama reports all three, llama-server
    reports reading and writing, an OpenAI-style server neither, and
    `seconds` -- timed here, around the request -- is then all there
    is. `cached_input_tokens` is what the provider says it did NOT
    re-read (Ollama's prompt_eval_cached_count, llama-server's cache_n).
    """

    #: Which part of a question: "step", "plan", "answer", or "other".
    part: str
    input_tokens: int | None
    output_tokens: int | None
    seconds: float
    cached_input_tokens: int | None = None
    reading_seconds: float | None = None
    writing_seconds: float | None = None
    loading_seconds: float | None = None
    #: True when the provider says it stopped at the length it was
    #: allowed (Ollama's done_reason, OpenAI's finish_reason, "length"):
    #: the reply is cut short. None when it did not say.
    stopped_at_limit: bool | None = None


@dataclass
class TokenUsage:
    """What the provider REPORTED it consumed, summed over calls (E-11).

    chat() returns only text, so the counts every provider sends back
    were dropped. A caller that wants them passes one of these, and each
    adapter adds what its provider reported. `unreported` counts calls
    whose provider reported nothing -- so "no tokens" is never mistaken
    for "not told".

    AND EACH CALL, with its timings (`records`): a caller names the part
    of the question its calls are for with `for_part("answer")`, which
    returns a view that records into this one under that name.

    Thread-safe: one query's calls may run on more than one thread.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    unreported: int = 0
    records: list[CallRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    #: For a view from for_part(): where its calls are recorded, and as what.
    _parent: TokenUsage | None = field(default=None, repr=False, compare=False)
    _part: str = field(default="other", repr=False, compare=False)

    def for_part(self, part: str) -> TokenUsage:
        """A view recording this tally's calls as `part`."""
        root = self._parent or self
        return TokenUsage(_parent=root, _part=part)

    def add(self, input_tokens: int | None, output_tokens: int | None, *,
            seconds: float | None = None, cached_input_tokens: int | None = None,
            reading_seconds: float | None = None, writing_seconds: float | None = None,
            loading_seconds: float | None = None, stopped_at_limit: bool | None = None) -> None:
        if self._parent is not None:
            self._parent._add(self._part, input_tokens, output_tokens, seconds,
                              cached_input_tokens, reading_seconds, writing_seconds,
                              loading_seconds, stopped_at_limit)
            return
        self._add(self._part, input_tokens, output_tokens, seconds, cached_input_tokens,
                  reading_seconds, writing_seconds, loading_seconds, stopped_at_limit)

    def _add(self, part, input_tokens, output_tokens, seconds, cached_input_tokens,
             reading_seconds, writing_seconds, loading_seconds, stopped_at_limit) -> None:
        with self._lock:
            self.calls += 1
            if seconds is not None:
                self.records.append(CallRecord(
                    part, input_tokens, output_tokens, seconds, cached_input_tokens,
                    reading_seconds, writing_seconds, loading_seconds, stopped_at_limit))
            if input_tokens is None and output_tokens is None:
                self.unreported += 1
                return
            self.input_tokens += input_tokens or 0
            self.output_tokens += output_tokens or 0

    def last(self, part: str) -> CallRecord | None:
        """The most recent timed call of `part`, or None."""
        root = self._parent or self
        with root._lock:
            return next((record for record in reversed(root.records) if record.part == part), None)

    def by_part(self) -> dict[str, dict]:
        """{part: totals} over the timed calls, in the order parts first
        appeared. A sum is None when no call of the part reported it, so
        "not told" stays apart from zero."""
        root = self._parent or self
        with root._lock:
            records = list(root.records)
        totals: dict[str, dict] = {}
        for record in records:
            into = totals.setdefault(record.part, {
                "calls": 0, "seconds": 0.0, "input_tokens": None, "cached_input_tokens": None,
                "output_tokens": None, "reading_seconds": None, "writing_seconds": None,
                "loading_seconds": None})
            into["calls"] += 1
            into["seconds"] += record.seconds
            for key in ("input_tokens", "cached_input_tokens", "output_tokens",
                        "reading_seconds", "writing_seconds", "loading_seconds"):
                value = getattr(record, key)
                if value is not None:
                    into[key] = (into[key] or 0) + value
        return totals

    def describe(self) -> str:
        """Where the time went, in a line: per part, its calls and
        seconds, then reading and writing where the provider said."""
        parts = []
        for part, totals in self.by_part().items():
            calls = totals["calls"]
            text = f"{part} {calls} call{'s' if calls != 1 else ''} {totals['seconds']:.1f}s"
            detail = []
            if totals["reading_seconds"] is not None:
                detail.append(f"reading {totals['reading_seconds']:.1f}s")
            if totals["writing_seconds"] is not None:
                written = totals["output_tokens"]
                rate = (f" at {written / totals['writing_seconds']:.1f}/s"
                        if written and totals["writing_seconds"] else "")
                detail.append(f"writing {totals['writing_seconds']:.1f}s"
                              + (f" for {written} tokens{rate}" if written is not None else ""))
            elif totals["output_tokens"] is not None:
                detail.append(f"{totals['output_tokens']} tokens written")
            if totals["loading_seconds"]:
                detail.append(f"loading {totals['loading_seconds']:.1f}s")
            parts.append(text + (f" ({', '.join(detail)})" if detail else ""))
        return "; ".join(parts) if parts else "no timed model calls"


@dataclass(frozen=True)
class RequestContext:
    """The unit of work a read or write belongs to.

    `request_id` correlates every access decision made while serving
    one query, which is what lets a user be shown what was read on
    their behalf.

    FIELDS ARE ADDED HERE, not passed alongside. A deadline and a token
    count are the two already planned; both are request-scoped, both
    are needed at the same depth, and both would otherwise become a
    second and third parameter on every signature this one already
    travels through.
    """

    request_id: str
    # E-11: when the request must be done by (a time.monotonic() value),
    # and what the model providers reported it consumed. The two fields
    # this docstring always planned.
    deadline: float | None = None
    token_usage: TokenUsage | None = None

    @classmethod
    def new(cls, deadline_seconds: float | None = None) -> RequestContext:
        """A context for a request that has just arrived.

        uuid4 rather than a counter: a counter needs shared state,
        which is the thing this design exists to avoid, and it would
        leak how many requests a deployment has served.
        """
        return cls(
            request_id=str(uuid.uuid4()),
            deadline=None if deadline_seconds is None else time.monotonic() + deadline_seconds,
            token_usage=TokenUsage(),
        )
