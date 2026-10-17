"""Timers: "call me back at this time" (the owner's decision, 16 October).

WHY ONE SERVICE. Anything in Elysium that must ACT at a moment -- not
merely be correct when somebody next looks -- registers a timer here
rather than growing its own loop. The first caller is a date-filtered
trigger, which wakes at the exact moment a record enters or leaves its
window (core/trigger_windows.py). The owner asked for the general
service from the start, so the next caller registers a kind and a
handler instead of writing a scheduler.

WHAT STAYS ON READ. Proposal expiry, session expiry and "the sync has
not run" are checked when somebody next looks, and are right to be:
nothing is lost by noticing them then. This is for the things where
being noticed late IS the failure.

THE SHAPE IS TEMPORAL'S DURABLE TIMER, at the size of one SQLite table.
"Timers are persisted, so even if your Worker or Temporal Service is
down when the time period completes", the callback runs once they are
back. So:

- PERSISTED. A timer is a row in timers.db. A server down when it came
  due fires it on start.
- KEYED. (kind, key) is unique: registering again MOVES the timer, it
  never adds a second. A trigger re-registering its next boundary
  replaces the last one.
- AT LEAST ONCE. A timer is deleted only after its handler returns, and
  only if nobody moved it meanwhile -- so a handler must re-check its
  condition rather than trust that the time alone means something.
  Every handler here does: a trigger is evaluated, not told it fired.
- RETRIED, THEN DROPPED. A handler that raises is tried again a few
  minutes later, up to MAX_ATTEMPTS, then the timer is removed and
  logged. A caller whose condition still matters registers again on
  its next ordinary evaluation.

THE LOOP THAT FIRES THEM is api/timer_service.py; this file is the
store, usable from any process -- the sync registers timers too.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.sqlite_connection import connection_with_schema

logger = logging.getLogger(__name__)

#: How many times a handler may fail before its timer is dropped.
MAX_ATTEMPTS = 5
#: How long after a failure the timer is tried again, in seconds.
RETRY_SECONDS = 300.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS timers (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    -- Seconds since the epoch, UTC. A number, so "what is due" is one
    -- indexed comparison and never a string format question.
    due_at REAL NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    attempts INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, key)
);
CREATE INDEX IF NOT EXISTS timers_due ON timers (due_at);
"""


@dataclass(frozen=True)
class Timer:
    kind: str
    key: str
    due_at: float
    payload: dict
    attempts: int


# WHO TO TELL WHEN A TIMER IS SET, in this process. The server's loop
# sleeps until the earliest timer; one set sooner than that wakes it.
# Another process's timers are found by the loop's own regular look.
_listeners: list[Callable[[float], object]] = []


def on_set(listener: Callable[[float], object]) -> Callable[[], None]:
    """Calls `listener(due_at)` whenever this process sets a timer.
    Returns the function that removes it."""
    _listeners.append(listener)
    return lambda: _listeners.remove(listener) if listener in _listeners else None


class TimerStore:
    def __init__(self, data_dir: Path):
        self._db_path = Path(data_dir) / "timers.db"

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def set(self, kind: str, key: str, due_at: float, payload: dict | None = None) -> None:
        """Calls back `kind` with `key` at `due_at`; moves it if set."""
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO timers (kind, key, due_at, payload, attempts) VALUES (?, ?, ?, ?, 0) "
                "ON CONFLICT (kind, key) DO UPDATE SET due_at = excluded.due_at, "
                "payload = excluded.payload, attempts = 0",
                (kind, key, float(due_at), json.dumps(payload or {})),
            )
            conn.commit()
        for listener in list(_listeners):
            try:
                listener(float(due_at))
            except Exception:  # noqa: BLE001 - a listener never fails a registration
                logger.warning("a timer listener failed", exc_info=True)

    def cancel(self, kind: str, key: str) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM timers WHERE kind = ? AND key = ?", (kind, key))
            conn.commit()

    def get(self, kind: str, key: str) -> "Timer | None":
        with self._connection() as conn:
            row = conn.execute(
                "SELECT kind, key, due_at, payload, attempts FROM timers WHERE kind = ? AND key = ?",
                (kind, key),
            ).fetchone()
        return None if row is None else _timer(row)

    def next_due(self) -> "float | None":
        with self._connection() as conn:
            row = conn.execute("SELECT MIN(due_at) FROM timers").fetchone()
        return None if row is None or row[0] is None else float(row[0])

    def due(self, now: float) -> list[Timer]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT kind, key, due_at, payload, attempts FROM timers "
                "WHERE due_at <= ? ORDER BY due_at", (now,),
            ).fetchall()
        return [_timer(row) for row in rows]

    def done(self, timer: Timer) -> None:
        """Removes a fired timer -- unless it was moved while firing,
        which is the handler registering its own next time."""
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM timers WHERE kind = ? AND key = ? AND due_at = ?",
                (timer.kind, timer.key, timer.due_at),
            )
            conn.commit()

    def failed(self, timer: Timer, now: float) -> bool:
        """Records a failed attempt. Returns whether it will be retried."""
        if timer.attempts + 1 >= MAX_ATTEMPTS:
            logger.error("timer %s/%s failed %d times and was dropped",
                         timer.kind, timer.key, MAX_ATTEMPTS)
            self.done(timer)
            return False
        with self._connection() as conn:
            conn.execute(
                "UPDATE timers SET due_at = ?, attempts = attempts + 1 "
                "WHERE kind = ? AND key = ? AND due_at = ?",
                (now + RETRY_SECONDS, timer.kind, timer.key, timer.due_at),
            )
            conn.commit()
        return True


def _timer(row) -> Timer:
    return Timer(kind=row[0], key=row[1], due_at=float(row[2]),
                 payload=json.loads(row[3] or "{}"), attempts=int(row[4]))
