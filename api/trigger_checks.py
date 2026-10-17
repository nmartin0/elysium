"""Checking triggers when something happens in the server (16 October).

TWO EVENTS, both of which change what a trigger would count without a
sync (core/trigger_runs.py has the whole account of when triggers are
checked):

- A CHANGE SAVED: the triggers watching the object types it wrote.
- A TRIGGER MADE: that one trigger, so "now watching" arrives at once.

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

    def _ask(self, types=frozenset(), ids=frozenset()) -> None:
        with self._lock:
            self._types |= set(types)
            self._ids |= set(ids)
            if self._running:
                # GATHERED for the run already going to take them.
                return
            self._running = True
        self._submit(self._drain)

    def _drain(self) -> None:
        while True:
            with self._lock:
                types, ids = self._types, self._ids
                self._types, self._ids = set(), set()
                if not types and not ids:
                    self._running = False
                    return
            try:
                self._check(types, ids)
            except Exception:  # noqa: BLE001 - see the module docstring
                logger.warning("could not check triggers after a change", exc_info=True)

    def _check(self, types: set, ids: set) -> None:
        from core.trigger_runs import run_triggers, watching

        app = self._app
        generation = app.state.generation
        moved = watching(types)
        fired = run_triggers(
            generation.config, app.state.runtime_paths.data_dir, generation.mediator,
            lambda: (generation.mediator, generation.write_mediator, app.state.pending_writes),
            include=lambda trigger, view: (
                getattr(trigger, "trigger_id", None) in ids or moved(trigger, view)),
        )
        if fired:
            logger.info("%d trigger(s) fired after a change", fired)
