"""Reminders: timers a person makes for themselves (17 October).

The first timers PEOPLE make (core/timers.py). Once at a moment, or
repeating -- every N minutes, or on weekdays at a time in their own time
zone (core/timer_rules.py). When one fires, its owner is notified. The
owner lists and cancels their own; nobody else sees them.

NO GRANT NEEDED, for the reason triggers needed none at first: a
reminder tells only the person who made it, and says only what they
wrote. Nothing is read, nothing crosses a boundary.

HOW LATE IS TOO LATE IS THE OWNER'S CHOICE. By default, an hour: a
reminder found more than an hour after it was due -- the server was
down -- is not delivered as if on time. The owner is told it was MISSED,
once, with how many later occurrences of a repeating one fell in the
same outage, and a repeating one carries on from its next occurrence.
Quartz calls the same choice a misfire instruction. "Deliver however
late" is the other answer, for a reminder that is still worth having.

EXACTLY ONCE, IN EFFECT: the notice is written with its occurrence's
key, so a firing delivered twice -- a server stopped mid-firing -- is
one notice.

BOUNDED. MAX_PER_PERSON reminders each, and repeats no more often than
every core/timer_rules.MIN_INTERVAL_MINUTES: a reminder every minute is
a flood.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core.timer_rules import RuleError, first_occurrence, instant, rule_from, zone

logger = logging.getLogger(__name__)

KIND = "reminder"
NOTIFICATION_KIND = "reminder"
MAX_PER_PERSON = 100
MAX_LABEL = 200
#: The default lateness policy: an hour, after which a reminder was
#: missed rather than late.
DEFAULT_LATE_AFTER_MINUTES = 60
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class ReminderError(ValueError):
    """A reminder that cannot be made, with the reason in words."""


@dataclass(frozen=True)
class ReminderSpec:
    label: str
    due_at: float
    timezone: str
    late_after: "float | None"
    repeat: "dict | None"


def parse(body: dict, now: datetime) -> ReminderSpec:
    """A request turned into what to store, or ReminderError saying why
    not. Everything is checked here, before anything is written."""
    label = body.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ReminderError("A reminder needs a label.")
    label = label.strip()
    if len(label) > MAX_LABEL:
        raise ReminderError(f"A label is at most {MAX_LABEL} characters.")
    timezone = body.get("timezone") or "UTC"
    try:
        zone(timezone)
    except RuleError as e:
        raise ReminderError(str(e)) from e

    late = body.get("late_after_minutes", DEFAULT_LATE_AFTER_MINUTES)
    if late is not None and (not isinstance(late, int) or isinstance(late, bool) or late < 1):
        raise ReminderError("How late is too late is a whole number of minutes, or none.")
    late_after = None if late is None else late * 60.0

    at, repeat = body.get("at"), body.get("repeat")
    try:
        start = None if at is None else instant(at)
        if repeat is None:
            if start is None:
                raise ReminderError("Say when: a time, or a repeat.")
            if start <= now:
                raise ReminderError("That time has already passed.")
            return ReminderSpec(label, start.timestamp(), timezone, late_after, None)
        rule = rule_from(repeat, timezone, body.get("until"))
        if start is not None and "every_minutes" not in rule:
            raise ReminderError("A weekday repeat starts at its own time; leave out the start.")
        if start is not None and start <= now:
            raise ReminderError("That start has already passed.")
        first = first_occurrence(rule, now, start)
    except RuleError as e:
        raise ReminderError(str(e)) from e
    if first is None:
        raise ReminderError("That repeat ends before it would first fire.")
    return ReminderSpec(label, first.timestamp(), timezone, late_after, rule)


def describe_repeat(rule: "dict | None") -> "str | None":
    """How the list says a repeat. None for a reminder that fires once."""
    if rule is None:
        return None
    if "every_minutes" in rule:
        minutes = rule["every_minutes"]
        every = (f"every {minutes // 60} hours" if minutes % 60 == 0 and minutes > 60
                 else "every hour" if minutes == 60 else f"every {minutes} minutes")
    else:
        days = sorted(rule["days"])
        named = ("every day" if len(days) == 7 else "weekdays" if days == [0, 1, 2, 3, 4]
                 else ", ".join(_WEEKDAYS[day] for day in days))
        every = f"{named} at {rule['time']} ({rule['timezone']})"
    if rule.get("until"):
        every += f", until {rule['until']}"
    return every


def _when(timestamp: float, timezone: str) -> str:
    local = datetime.fromtimestamp(timestamp, UTC).astimezone(zone(timezone))
    return f"{local:%a %d %b %H:%M} {timezone}"


def fire(store: Any, user_is_active, firing) -> None:
    """The timer service's handler for a reminder: notify its owner.

    RAISES IF THE NOTICE COULD NOT BE WRITTEN, so the timer service
    retries it -- a reminder that silently failed to remind is the one
    failure this exists to prevent. A retry is the same occurrence, with
    the same key, so it is still one notice.
    """
    timer = firing.timer
    owner = timer.owner_user_id
    if owner is None or not user_is_active(owner):
        # A REMOVED OR DISABLED ACCOUNT IS NOT REMINDED. Not an error:
        # nothing to retry, and the timer carries on or ends as it would.
        logger.info("reminder %s skipped: owner %r is not active", timer.key, owner)
        return
    label = timer.payload.get("label", "")
    timezone = timer.payload.get("timezone", "UTC")
    count = firing.also_missed
    occurrences = f"{count} {'occurrence' if count == 1 else 'occurrences'}"
    if firing.missed:
        # The stored occurrence is reported; any later ones in the same
        # outage are counted after it.
        summary = (f"Missed reminder: {label} -- due {_when(firing.at, timezone)}, "
                   f"while Elysium was not running.")
        if count:
            summary += f" {count} later {'one was' if count == 1 else 'ones were'} skipped too."
    elif count:
        # ON TIME: the most recent occurrence after an outage, still
        # inside the owner's policy, with the earlier ones counted.
        summary = (f"Reminder: {label}. {occurrences} before this "
                   f"{'was' if count == 1 else 'were'} missed while Elysium was not running.")
    else:
        summary = f"Reminder: {label}"
    written = store.notify(owner, NOTIFICATION_KIND, summary,
                           detail=describe_repeat(timer.repeat),
                           dedupe_key=firing.occurrence_key)
    if written is None:
        raise RuntimeError(f"could not write reminder {timer.key} for {owner}")
