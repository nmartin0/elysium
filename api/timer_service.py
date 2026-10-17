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
(app, key, payload), run in a thread. A kind with no handler -- a
caller removed since its timers were set -- is logged and dropped,
never retried forever.

NEVER RAISES INTO THE SERVER.
"""

import asyncio
import fcntl
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.timers import TimerStore, on_set

logger = logging.getLogger(__name__)

#: The longest the loop sleeps without looking, in seconds.
LOOK_SECONDS = 60.0
#: The shortest. A timer due now that ANOTHER worker is firing stays
#: due until it finishes; without a floor this worker would spin.
MIN_SLEEP_SECONDS = 1.0
_LOCK = "timers.lock"

Handler = Callable[[Any, str, dict], None]


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
            try:
                handler(app, timer.key, timer.payload)
            except Exception:  # noqa: BLE001 - see the module docstring
                logger.warning("timer %s/%s failed", timer.kind, timer.key, exc_info=True)
                store.failed(timer, clock())
                continue
            ran += 1
            store.done(timer)
        return ran


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
