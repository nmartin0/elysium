"""The loop that fires timers (core/timers.py), in the server.

A STANDING LOOP IN THE API PROCESS, decided by the owner 16 October --
which this project had refused twice for RARE work (api/reload.py, the
metrics sweep; core/mirror/health_condition.py records both). This is
the one place that decision was reversed, and why: some things must
happen AT a time, not when somebody next looks, and one loop serving
every caller is the alternative to each caller growing its own. It
replaces the fifteen-minute trigger clock, which was exactly that.

SLEEPS UNTIL THE EARLIEST TIMER, never longer than LOOK_SECONDS. The
cap is how timers set by ANOTHER process -- the sync -- are found;
a timer set in THIS process wakes the loop at once (core/timers.on_set).

ONE FIRER, HOWEVER MANY WORKERS. Each worker runs the loop; whoever
takes the file lock fires what is due, and the rest skip that round.

HANDLERS BY KIND. `handlers` maps a timer's kind to a function of
(app, Firing), run in a thread. The Firing says whether the occurrence
is on time or MISSED under the timer's own lateness policy, and carries
the occurrence key that makes a second delivery a no-op. A kind with no handler -- a
caller removed since its timers were set -- is logged and dropped,
never retried forever.

NEVER RAISES INTO THE SERVER.
"""

import asyncio
import fcntl
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.timers import ON_TIME_SECONDS, Timer, TimerStore, on_set

logger = logging.getLogger(__name__)

#: The longest the loop sleeps without looking, in seconds.
LOOK_SECONDS = 60.0
#: The shortest. A timer due now that ANOTHER worker is firing stays
#: due until it finishes; without a floor this worker would spin.
MIN_SLEEP_SECONDS = 1.0
_LOCK = "timers.lock"

@dataclass(frozen=True)
class Firing:
    """What a handler is told: which timer, which occurrence, and whether
    it is ON TIME or MISSED (core/timers.py, late_after)."""

    timer: Timer
    now: float
    #: Later than the timer's own policy allows: the handler should say
    #: it was missed, not act as if on time.
    missed: bool = False
    #: Occurrences of a repeating timer that fell inside an outage and
    #: are NOT being delivered -- counted so the handler can say so.
    #: Never replayed: a repeating timer catches up at most once.
    also_missed: int = 0
    #: Which occurrence this firing is for. The stored one, unless a
    #: repeating timer came back with a LATER occurrence still inside its
    #: policy -- then that one is delivered, and the earlier ones are
    #: `also_missed`.
    occurrence_at: "float | None" = None

    @property
    def key(self) -> str:
        return self.timer.key

    @property
    def payload(self) -> dict:
        return self.timer.payload

    @property
    def at(self) -> float:
        return self.timer.occurrence_at if self.occurrence_at is None else self.occurrence_at

    @property
    def occurrence_key(self) -> str:
        """What makes a second delivery of this firing a no-op."""
        return f"timer/{self.timer.kind}/{self.timer.key}/{self.at!r}"


Handler = Callable[[Any, Firing], None]


def fire_due(app, handlers: dict[str, Handler], clock=time.time) -> int:
    """Fires every timer due now, if this worker takes the lock.
    Returns how many handlers ran."""
    data_dir = Path(app.state.runtime_paths.data_dir)
    store = TimerStore(data_dir)
    with open(data_dir / _LOCK, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        ran = 0
        for timer in store.due(clock()):
            handler = handlers.get(timer.kind)
            if handler is None:
                logger.warning("no handler for timer kind %r; dropping %r", timer.kind, timer.key)
                store.done(timer)
                continue
            now = clock()
            firing = _firing(timer, now)
            try:
                handler(app, firing)
            except Exception:  # noqa: BLE001 - see the module docstring
                logger.warning("timer %s/%s failed", timer.kind, timer.key, exc_info=True)
                store.failed(timer, clock())
                continue
            ran += 1
            # ONCE: removed. REPEATING: on to the first occurrence AFTER
            # NOW -- whatever it missed was told once, above, and is not
            # replayed.
            following = _following(timer, now)
            if following is None:
                store.done(timer)
            else:
                store.advance(timer, following)
        return ran


def _firing(timer: Timer, now: float) -> Firing:
    """On time, or missed -- and for a repeating timer back from an
    outage, WHICH occurrence: the most recent, if it is still inside the
    policy, with the earlier ones counted as missed; otherwise the
    stored one, reported missed, with the rest counted."""
    since = _occurrences_after(timer, now)
    if timer.late_after is None:
        # FIRE HOWEVER LATE, once: the most recent occurrence, with any
        # earlier ones it stands for counted rather than replayed.
        latest = since[-1] if since else timer.occurrence_at
        return Firing(timer, now, also_missed=len(since), occurrence_at=latest)
    threshold = max(timer.late_after, ON_TIME_SECONDS)
    latest = since[-1] if since else timer.occurrence_at
    if now - latest <= threshold:
        return Firing(timer, now, also_missed=len(since), occurrence_at=latest)
    return Firing(timer, now, missed=True, also_missed=len(since))


def _following(timer: Timer, now: float) -> "float | None":
    if timer.repeat is None:
        return None
    from core.timer_rules import next_occurrence

    anchor = datetime.fromtimestamp(timer.occurrence_at, UTC)
    after = datetime.fromtimestamp(now, UTC)
    following = next_occurrence(timer.repeat, after, anchor)
    return None if following is None else following.timestamp()


def _occurrences_after(timer: Timer, now: float) -> list[float]:
    """The occurrences of a repeating timer after the stored one and no
    later than now -- the ones an outage swallowed. Empty for a one-off.
    Bounded: a five-minute reminder down for a year is 105,120 of them,
    and a thousand says enough."""
    if timer.repeat is None:
        return []
    from core.timer_rules import next_occurrence

    anchor = datetime.fromtimestamp(timer.occurrence_at, UTC)
    cursor = anchor
    found: list[float] = []
    while len(found) < 1000:
        following = next_occurrence(timer.repeat, cursor, anchor)
        if following is None or following.timestamp() > now:
            break
        found.append(following.timestamp())
        cursor = following
    return found


def seconds_until_next(app, clock=time.time) -> float:
    """How long to sleep: until the earliest timer, between
    MIN_SLEEP_SECONDS and LOOK_SECONDS."""
    upcoming = TimerStore(Path(app.state.runtime_paths.data_dir)).next_due()
    if upcoming is None:
        return LOOK_SECONDS
    return max(MIN_SLEEP_SECONDS, min(LOOK_SECONDS, upcoming - clock()))


async def run_timer_service(app, handlers: dict[str, Handler]) -> None:
    """The loop, started and cancelled by the app's lifespan."""
    loop = asyncio.get_running_loop()
    woken = asyncio.Event()
    # A TIMER SET HERE, possibly from a request thread, wakes the sleep
    # so it can be recomputed -- the new one may be the earliest.
    remove = on_set(lambda due_at: loop.call_soon_threadsafe(woken.set))
    try:
        while True:
            try:
                wait = await asyncio.to_thread(seconds_until_next, app)
            except Exception:  # noqa: BLE001
                logger.warning("timers: could not read the next due time", exc_info=True)
                wait = LOOK_SECONDS
            try:
                await asyncio.wait_for(woken.wait(), timeout=wait)
            except TimeoutError:
                pass
            woken.clear()
            try:
                await asyncio.to_thread(fire_due, app, handlers)
            except Exception:  # noqa: BLE001 - see the module docstring
                logger.warning("timers: could not fire", exc_info=True)
    finally:
        remove()
