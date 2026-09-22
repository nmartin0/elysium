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


@dataclass
class TokenUsage:
    """What the provider REPORTED it consumed, summed over calls (E-11).

    chat() returns only text, so the counts every provider sends back
    were dropped. A caller that wants them passes one of these, and each
    adapter adds what its provider reported. `unreported` counts calls
    whose provider reported nothing -- so "no tokens" is never mistaken
    for "not told".

    Thread-safe: one query's calls may run on more than one thread.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    unreported: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, input_tokens: int | None, output_tokens: int | None) -> None:
        with self._lock:
            self.calls += 1
            if input_tokens is None and output_tokens is None:
                self.unreported += 1
                return
            self.input_tokens += input_tokens or 0
            self.output_tokens += output_tokens or 0



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
