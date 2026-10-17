"""Timers: "call me back at this time" (the owner's decision, 16 October;
once, repeating, owned and late-aware since 17 October).

WHY ONE SERVICE. Anything in Elysium that must ACT at a moment -- not
merely be correct when somebody next looks -- registers a timer here
rather than growing its own loop. Two callers today: a date-filtered
trigger, which wakes when a record crosses its window
(core/trigger_windows.py), and a person's own reminder
(core/reminders.py).

WHAT STAYS ON READ. Proposal expiry, session expiry and "the sync has
not run" are checked when somebody next looks, and are right to be:
nothing is lost by noticing them then. This is for the things where
being noticed late IS the failure.

THE SHAPE IS TEMPORAL'S DURABLE TIMER, at the size of one SQLite table,
with the scheduler's questions answered per timer:

- PERSISTED. A timer is a row in timers.db, so one due while the server
  was down is found when it starts.
- KEYED. (kind, key) is unique: setting again MOVES the timer.
- ONCE OR REPEATING (core/timer_rules.py). Only the next occurrence is
  stored; after each firing the next is worked out from the rule.
- HOW LATE IS TOO LATE, per timer (`late_after`). Quartz's "misfire
  instructions" and Kubernetes' startingDeadlineSeconds answer the same
  question: a reminder for the 09:00 meeting is worthless at 11:00, and
  a trigger re-checking current state is never too late. None means
  "fire however late"; a number means "past this, it was MISSED" -- the
  handler is told so instead of being run as if on time, and a
  repeating timer moves on to its next occurrence. A repeating timer
  CATCHES UP AT MOST ONCE, never replaying every occurrence it missed.
- EXACTLY ONCE, IN EFFECT. Delivery is at least once -- a timer is
  removed or advanced only after its handler returns, so a server
  stopped mid-firing fires it again. Each occurrence therefore carries a
  key (kind, key, occurrence) that the handler's own write uses to make
  the second delivery a no-op: a notification with the same key is not
  written twice (core/notifications.py, dedupe_key). A handler whose
  effect is a re-check of current state -- a trigger -- needs no key.
- OWNED, for the timers people make: listed and cancelled by their
  owner and nobody else. A timer Elysium derives for itself -- a
  trigger's next crossing -- has no owner; it would only be set again
  at the next evaluation, so it is controlled by turning off the
  trigger, not by cancelling the timer.
- RETRIED, THEN DROPPED. A handler that raises is tried again a few
  minutes later, up to MAX_ATTEMPTS, then dropped and logged. The
  occurrence it was for stays its key, so a retry is still the same
  firing.

THE LOOP THAT FIRES THEM is api/timer_service.py; this file is the
store, usable from any process -- the sync sets timers too.
"""

import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.sqlite_connection import add_column_if_missing, connection_with_schema

logger = logging.getLogger(__name__)

#: How many times a handler may fail before its timer is dropped.
MAX_ATTEMPTS = 5
#: How long after a failure the timer is tried again, in seconds.
RETRY_SECONDS = 300.0
#: Late by less than this is ON TIME, whatever the policy -- Quartz's
#: misfireThreshold, and its default: one minute. A loop that wakes on
#: the minute must not call its own ordinary lateness a miss.
ON_TIME_SECONDS = 60.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS timers (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    -- Seconds since the epoch, UTC. A number, so "what is due" is one
    -- indexed comparison and never a string format question. A retry
    -- moves this and nothing else.
    due_at REAL NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    attempts INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, key)
);
CREATE INDEX IF NOT EXISTS timers_due ON timers (due_at);
"""

_MIGRATIONS = (
    # THE SCHEDULED MOMENT this firing is for. Equal to due_at except
    # while retrying, when due_at moves on and this does not -- so a
    # retry is the same occurrence, with the same key.
    add_column_if_missing("timers", "occurrence_at", "REAL"),
    # WHO MADE IT, for timers people make; NULL for derived ones.
    add_column_if_missing("timers", "owner_user_id", "TEXT"),
    # HOW LATE IS TOO LATE, in seconds; NULL is "fire however late".
    add_column_if_missing("timers", "late_after", "REAL"),
    # THE REPEAT RULE as JSON (core/timer_rules.py); NULL is once.
    add_column_if_missing("timers", "repeat", "TEXT"),
    add_column_if_missing("timers", "created_at", "REAL"),
)


@dataclass(frozen=True)
class Timer:
    kind: str
    key: str
    due_at: float
    payload: dict
    attempts: int
    occurrence_at: float = 0.0
    owner_user_id: "str | None" = None
    late_after: "float | None" = None
    repeat: "dict | None" = None
    created_at: "float | None" = None

    @property
    def occurrence_key(self) -> str:
        """What makes a second delivery of this firing a no-op."""
        return f"timer/{self.kind}/{self.key}/{self.occurrence_at!r}"


# WHO TO TELL WHEN A TIMER IS SET, in this process. The server's loop
# sleeps until the earliest timer; one set sooner than that wakes it.
# Another process's timers are found by the loop's own regular look.
_listeners: list[Callable[[float], object]] = []


def on_set(listener: Callable[[float], object]) -> Callable[[], None]:
    """Calls `listener(due_at)` whenever this process sets a timer.
    Returns the function that removes it."""
    _listeners.append(listener)
    return lambda: _listeners.remove(listener) if listener in _listeners else None


_COLUMNS = ("kind, key, due_at, payload, attempts, occurrence_at, owner_user_id, "
            "late_after, repeat, created_at")


class TimerStore:
    def __init__(self, data_dir: Path):
        self._db_path = Path(data_dir) / "timers.db"

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA, migrations=_MIGRATIONS)

    def set(self, kind: str, key: str, due_at: float, payload: dict | None = None,
            owner_user_id: "str | None" = None, late_after: "float | None" = None,
            repeat: "dict | None" = None, now: "float | None" = None) -> None:
        """Calls back `kind` with `key` at `due_at`; moves it if set."""
        with self._connection() as conn:
            conn.execute(
                f"INSERT INTO timers ({_COLUMNS}) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?) "  # noqa: S608 - constants
                "ON CONFLICT (kind, key) DO UPDATE SET due_at = excluded.due_at, "
                "occurrence_at = excluded.occurrence_at, payload = excluded.payload, "
                "owner_user_id = excluded.owner_user_id, late_after = excluded.late_after, "
                "repeat = excluded.repeat, attempts = 0",
                (kind, key, float(due_at), json.dumps(payload or {}), float(due_at),
                 owner_user_id, late_after, None if repeat is None else json.dumps(repeat),
                 now if now is not None else time.time()),
            )
            conn.commit()
        for listener in list(_listeners):
            try:
                listener(float(due_at))
            except Exception:  # noqa: BLE001 - a listener never fails a registration
                logger.warning("a timer listener failed", exc_info=True)

    def create_owned(self, kind: str, owner_user_id: str, due_at: float, payload: dict,
                     late_after: "float | None", repeat: "dict | None",
                     now: "float | None" = None) -> str:
        """A new timer a person made. Returns its key."""
        key = str(uuid.uuid4())
        self.set(kind, key, due_at, payload, owner_user_id=owner_user_id,
                 late_after=late_after, repeat=repeat, now=now)
        return key

    def cancel(self, kind: str, key: str) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM timers WHERE kind = ? AND key = ?", (kind, key))
            conn.commit()

    def cancel_owned(self, kind: str, key: str, owner_user_id: str) -> bool:
        """Cancels one of this person's timers. False for one that is not
        theirs or does not exist -- the same answer, deliberately."""
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM timers WHERE kind = ? AND key = ? AND owner_user_id = ?",
                (kind, key, owner_user_id))
            conn.commit()
            return cursor.rowcount > 0

    def owned_by(self, owner_user_id: str, kind: str) -> list[Timer]:
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM timers WHERE owner_user_id = ? AND kind = ? "  # noqa: S608
                "ORDER BY due_at", (owner_user_id, kind)).fetchall()
        return [_timer(row) for row in rows]

    def keys_of(self, kind: str) -> list[str]:
        """Every key set for one kind -- for a caller tidying its own."""
        with self._connection() as conn:
            rows = conn.execute("SELECT key FROM timers WHERE kind = ?", (kind,)).fetchall()
        return [row[0] for row in rows]

    def get(self, kind: str, key: str) -> "Timer | None":
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM timers WHERE kind = ? AND key = ?",  # noqa: S608
                (kind, key)).fetchone()
        return None if row is None else _timer(row)

    def next_due(self) -> "float | None":
        with self._connection() as conn:
            row = conn.execute("SELECT MIN(due_at) FROM timers").fetchone()
        return None if row is None or row[0] is None else float(row[0])

    def due(self, now: float) -> list[Timer]:
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM timers WHERE due_at <= ? ORDER BY due_at",  # noqa: S608
                (now,)).fetchall()
        return [_timer(row) for row in rows]

    def done(self, timer: Timer) -> None:
        """Removes a fired timer -- unless it was moved while firing,
        which is the handler setting its own next time."""
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM timers WHERE kind = ? AND key = ? AND due_at = ?",
                (timer.kind, timer.key, timer.due_at),
            )
            conn.commit()

    def advance(self, timer: Timer, next_at: float) -> None:
        """A repeating timer's next occurrence -- unless it was moved or
        cancelled while firing."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE timers SET due_at = ?, occurrence_at = ?, attempts = 0 "
                "WHERE kind = ? AND key = ? AND due_at = ?",
                (next_at, next_at, timer.kind, timer.key, timer.due_at),
            )
            conn.commit()

    def failed(self, timer: Timer, now: float) -> bool:
        """Records a failed attempt. Returns whether it will be retried.
        The OCCURRENCE does not move, so the retry is the same firing."""
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
    return Timer(
        kind=row[0], key=row[1], due_at=float(row[2]),
        payload=json.loads(row[3] or "{}"), attempts=int(row[4]),
        # A ROW FROM BEFORE THE COLUMN is its own occurrence.
        occurrence_at=float(row[5]) if row[5] is not None else float(row[2]),
        owner_user_id=row[6],
        late_after=None if row[7] is None else float(row[7]),
        repeat=None if row[8] is None else json.loads(row[8]),
        created_at=None if row[9] is None else float(row[9]),
    )
