"""Checking triggers when something happens in the server (16 October).

FOUR EVENTS, each of which can change what a trigger would count
without a sync (core/trigger_runs.py has the whole account of when
triggers are checked):

- A CHANGE SAVED: the triggers watching the object types it wrote.
- A TRIGGER MADE: that one trigger, so "now watching" arrives at once.
- ITS TIMER: a date-filtered trigger's window crossing
  (core/trigger_windows.py) -- `window_timer` below, the handler the
  timer service calls.
- THE SERVER STARTING: every date-filtered trigger once, which catches
  crossings while it was down and sets each one's next timer.

IN THE BACKGROUND, NEVER IN THE REQUEST. Evaluating counts once per
recipient per trigger, which can take seconds; the person approving a
change is waiting for the change, not for everybody's alerts.

COALESCED. Twenty approvals in a minute are not twenty evaluations:
while one check runs, the types saved meanwhile are gathered, and ONE
more check runs for all of them when it ends. Nothing is dropped -- a
type saved during a check is always checked after it -- and at most one
check per process is ever waiting.

NEVER RAISES INTO THE SERVER. A failed check is logged; the change it
followed is saved either way, and the next sync checks everything.
"""

import logging
import threading

logger = logging.getLogger(__name__)


class TriggerChecks:
    """One per server process, on app.state.trigger_checks."""

    def __init__(self, app, submit=None):
        self._app = app
        self._lock = threading.Lock()
        self._types: set[str] = set()
        self._ids: set[str] = set()
        self._dated = False
        self._running = False
        # `submit(fn)` runs fn in the background. A thread by default;
        # a test passes one that runs it at once, to observe it.
        self._submit = submit or (
            lambda fn: threading.Thread(target=fn, name="trigger-checks", daemon=True).start())

    def after_change(self, object_types) -> None:
        """A change to these types was saved."""
        self._ask(types=set(object_types))

    def after_made(self, trigger_id: str) -> None:
        """This trigger was just made."""
        self._ask(ids={trigger_id})

    def after_start(self) -> None:
        """The server started: every date-filtered trigger."""
        self._ask(dated=True)

    def _ask(self, types=frozenset(), ids=frozenset(), dated=False) -> None:
        with self._lock:
            self._types |= set(types)
            self._ids |= set(ids)
            self._dated = self._dated or dated
            if self._running:
                # GATHERED for the run already going to take them.
                return
            self._running = True
        self._submit(self._drain)

    def _drain(self) -> None:
        while True:
            with self._lock:
                types, ids, dated = self._types, self._ids, self._dated
                self._types, self._ids, self._dated = set(), set(), False
                if not types and not ids and not dated:
                    self._running = False
                    return
            try:
                self._check(types, ids, dated)
            except Exception:  # noqa: BLE001 - see the module docstring
                logger.warning("could not check triggers after a change", exc_info=True)

    def _check(self, types: set, ids: set, dated: bool = False) -> None:
        from core.trigger_runs import reads_the_clock, watching

        moved = watching(types)
        fired = _run(self._app, lambda trigger, view: (
            getattr(trigger, "trigger_id", None) in ids
            or moved(trigger, view)
            or (dated and reads_the_clock(trigger, view))))
        if fired:
            logger.info("%d trigger(s) fired after a change", fired)


def window_timer(app, firing) -> None:
    """The timer service's handler for a date-filtered trigger's
    crossing: evaluate that trigger, which sets its next timer. A
    trigger deleted or disabled since is simply not found.

    NEVER TOO LATE, and needs no occurrence key: it re-checks CURRENT
    state, so running late or twice says what is true now (its timers
    are set with no lateness policy)."""
    from core.trigger_runs import only

    fired = _run(app, only(firing.key))
    if fired:
        logger.info("trigger %s fired at its window's edge", firing.key)


def hold_timer(app, firing) -> None:
    """A held trigger's hold has ended for its earliest waiting person:
    evaluate it, which fires for whoever has now held long enough and
    sets the next hold timer. Re-checks current state, so never too
    late and needs no key."""
    from core.trigger_runs import only

    _run(app, only(firing.key))


def schedule_timer(app, firing) -> None:
    """A scheduled trigger's check (core/trigger_states.py).

    ON TIME: evaluated as a scheduled check, which tells each person
    for whom it is true -- once per occurrence each, by the occurrence's
    key. MISSED (more than an hour late; the server was down): its
    owner is told the check did not happen, rather than shown a 09:00
    digest at 11:00. A trigger deleted or turned off since is not
    found, and its timer goes with it.
    """
    from core.notifications import NotificationStore
    from core.timers import TimerStore
    from core.trigger_runs import only
    from core.trigger_states import SCHEDULE_KIND
    from core.triggers import TriggerStore

    data_dir = app.state.runtime_paths.data_dir
    trigger = next((trigger for trigger in TriggerStore(data_dir / "triggers.db").all_enabled()
                    if trigger.trigger_id == firing.key), None)
    if trigger is None:
        TimerStore(data_dir).cancel(SCHEDULE_KIND, firing.key)
        return
    if firing.missed:
        from datetime import UTC, datetime

        when = datetime.fromtimestamp(firing.at, UTC).strftime("%a %d %b %H:%M UTC")
        written = NotificationStore(data_dir / "notifications.db").notify(
            trigger.owner_user_id, "trigger",
            f"{trigger.name}: the check due {when} was missed while Elysium was not running.",
            dedupe_key=firing.occurrence_key)
        if written is None:
            raise RuntimeError(f"could not tell {trigger.owner_user_id} of a missed check")
        return
    _run(app, only(firing.key), on_schedule=firing.occurrence_key)


def _run(app, include, on_schedule=None) -> int:
    from core.trigger_runs import run_triggers

    generation = app.state.generation
    return run_triggers(
        generation.config, app.state.runtime_paths.data_dir, generation.mediator,
        lambda: (generation.mediator, generation.write_mediator, app.state.pending_writes),
        include=include, on_schedule=on_schedule,
    )
