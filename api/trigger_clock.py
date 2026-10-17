"""The server's clock for DATE-FILTERED triggers (revised 16 October).

ONLY THOSE. A trigger's count changes when the data under it changes --
checked at the end of a sync and straight after a change is saved
(core/trigger_runs.py) -- or when the clock moves under a date filter.
This loop is for the second, and nothing else: the first version
checked every trigger every fifteen minutes, which for a trigger with
no date filter could never find anything a sync or a saved change had
not already found.

WHY MINUTES AND NOT A DAY. `relative_date` is resolved against the
moment of the query (core/filters.py), not against midnight, so a
record leaves "the last 30 days" at whatever minute it turns 30 days
old. How late anybody hears is the interval. Foundry cannot monitor
"relative time conditions" live either; they fall back to its
"scheduled monitoring", which it warns "can result in high compute
usage" when frequent -- a count per date-filtered trigger is the light
end of that.

WHY THE SERVER, when INSTALL.md says Elysium has "no scheduler of its
own": that sentence is about the SYNC, which copies whole tables and
would compete with users for the CPU, so the operator schedules it.
Counting what a saved view matches is what the server does for every
request already. `check_date_triggers_every_minutes: 0` turns it off.

ONE CHECK PER INTERVAL, HOWEVER MANY WORKERS. Each worker runs this
loop; the first to find the interval elapsed takes a file lock in the
data directory, records the time, and checks. The others find the lock
taken, or the time recent, and do nothing.

NEVER RAISES INTO THE SERVER, and one failed check costs one check.
"""

import asyncio
import fcntl
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

#: How often each worker looks whether a check is due. A minute is fine
#: grain for an interval measured in quarter hours.
TICK_SECONDS = 60
_LOCK = "trigger_clock.lock"
_LAST = "trigger_clock.last"


def check_if_due(app, clock=time.time) -> bool:
    """Checks the date-filtered triggers if the interval has passed
    since the last check by any worker. Returns whether this call
    checked."""
    from core.trigger_runs import reads_the_clock, run_triggers

    generation = app.state.generation
    minutes = generation.config.check_date_triggers_every_minutes
    if minutes <= 0:
        return False
    data_dir = Path(app.state.runtime_paths.data_dir)
    with open(data_dir / _LOCK, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        last_file = data_dir / _LAST
        try:
            last = float(last_file.read_text().strip() or 0)
        except (FileNotFoundError, ValueError):
            last = 0.0
        now = clock()
        if now - last < minutes * 60:
            return False
        # RECORDED BEFORE THE CHECK, so a check that raises is not
        # retried every minute by every worker until it stops raising.
        last_file.write_text(f"{now}\n")
        try:
            fired = run_triggers(
                generation.config, data_dir, generation.mediator,
                lambda: (generation.mediator, generation.write_mediator,
                         app.state.pending_writes),
                include=reads_the_clock)
            if fired:
                logger.info("trigger clock: %d trigger(s) fired", fired)
        except Exception:  # noqa: BLE001 - see the module docstring
            logger.warning("trigger clock: the check failed", exc_info=True)
        return True


async def run_trigger_clock(app, tick: float = TICK_SECONDS) -> None:
    """The loop, started and cancelled by the app's lifespan. The check
    runs in a thread: it searches, and the event loop serves requests."""
    while True:
        await asyncio.sleep(tick)
        try:
            await asyncio.to_thread(check_if_due, app)
        except Exception:  # noqa: BLE001 - see the module docstring
            logger.warning("trigger clock: could not run", exc_info=True)
