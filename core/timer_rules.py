"""When a repeating timer next fires (17 October).

TWO SHAPES, the two every scheduler offers:

- AN INTERVAL: every N minutes, anchored to the first occurrence, so
  "every 2 hours from 09:00" stays on 09:00, 11:00, 13:00 however late
  any one firing ran.
- A CALENDAR RULE: on these weekdays at HH:MM, in a named time zone.

IN THE OWNER'S TIME ZONE, because "09:00 on weekdays" means nine on the
owner's clock, and a rule kept in UTC drifts by an hour twice a year
wherever the clocks change. zoneinfo does the arithmetic:

- A TIME THAT DOES NOT EXIST that day -- the clocks jump from 02:00 to
  03:00 -- fires at the first moment that does, which is how Python
  reads a non-existent wall time (the offset before the change).
- A TIME THAT HAPPENS TWICE -- the clocks fall back -- fires once, at
  the first of them (fold=0).

ONLY THE NEXT OCCURRENCE IS EVER STORED. After each firing the next is
worked out from the rule and the present, so a server down for a week
does not come back to a week of occurrences -- what happens to the ones
it missed is the timer's lateness policy, not this file's.

OPTIONALLY UNTIL A MOMENT, after which there is no next occurrence and
the timer ends.

Pure: no storage, no clock of its own. Every function takes the
present as an argument, so a test pins it.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: The shortest interval a repeating timer may have. A person's
#: reminder every minute is a notification flood, not a reminder.
MIN_INTERVAL_MINUTES = 5
#: The longest: a year. Past that, a calendar rule says it better.
MAX_INTERVAL_MINUTES = 525_600


class RuleError(ValueError):
    """A repeat rule that cannot be scheduled -- said, never guessed."""


def validate(rule: dict) -> None:
    """Refuses a rule that is not one of the two shapes, exactly."""
    if not isinstance(rule, dict):
        raise RuleError("A repeat is an interval or a set of weekdays and a time.")
    keys = set(rule) - {"until"}
    if keys == {"every_minutes"}:
        minutes = rule["every_minutes"]
        if not isinstance(minutes, int) or isinstance(minutes, bool) \
                or not MIN_INTERVAL_MINUTES <= minutes <= MAX_INTERVAL_MINUTES:
            raise RuleError(
                f"Repeat every {MIN_INTERVAL_MINUTES} minutes to {MAX_INTERVAL_MINUTES} "
                f"minutes (a year), as a whole number.")
    elif keys == {"days", "time", "timezone"}:
        days = rule["days"]
        if not isinstance(days, list) or not days or any(
                not isinstance(day, int) or isinstance(day, bool) or not 0 <= day <= 6
                for day in days):
            raise RuleError("Days are weekday numbers, Monday 0 to Sunday 6, at least one.")
        _time_of_day(rule["time"])
        zone(rule["timezone"])
    else:
        raise RuleError(
            "A repeat is either every_minutes, or days with a time and a timezone.")
    if rule.get("until") is not None:
        instant(rule["until"])


def next_occurrence(rule: dict, after: datetime, anchor: datetime) -> "datetime | None":
    """The first occurrence strictly after `after`, or None once past
    `until`. `anchor` is the first occurrence, which an interval keeps
    to. All three in and out are aware datetimes; the result is UTC."""
    after = after.astimezone(UTC)
    if "every_minutes" in rule:
        step = timedelta(minutes=rule["every_minutes"])
        anchor = anchor.astimezone(UTC)
        if anchor > after:
            candidate = anchor
        else:
            periods = (after - anchor) // step + 1
            candidate = anchor + periods * step
    else:
        candidate = _next_on_days(rule, after)
    until = rule.get("until")
    if until is not None and candidate > instant(until):
        return None
    return candidate


def first_occurrence(rule: dict, now: datetime, start: "datetime | None" = None) -> "datetime | None":
    """Where a new repeating timer begins: `start` for an interval when
    given (it must be in the future), else the first occurrence after
    now."""
    if "every_minutes" in rule:
        begin = start if start is not None else now + timedelta(minutes=rule["every_minutes"])
        return next_occurrence(rule, now, begin)
    return next_occurrence(rule, now, now)


def _next_on_days(rule: dict, after: datetime) -> datetime:
    tz = zone(rule["timezone"])
    at = _time_of_day(rule["time"])
    days = set(rule["days"])
    local_day = after.astimezone(tz).date()
    # Eight days covers every weekday at least once, from today.
    for offset in range(8):
        day: date = local_day + timedelta(days=offset)
        if day.weekday() not in days:
            continue
        candidate = datetime.combine(day, at, tzinfo=tz).astimezone(UTC)
        if candidate > after:
            return candidate
    raise RuleError("No weekday in the rule.")  # unreachable once validated


def zone(name) -> ZoneInfo:
    if not isinstance(name, str) or not name:
        raise RuleError("A time zone is an IANA name, such as Europe/London.")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise RuleError(f"{name!r} is not a time zone Elysium knows.") from e


def instant(value) -> datetime:
    """An ISO 8601 moment WITH an offset. One without is refused rather
    than read as UTC or as the server's local time, either of which
    would be a guess about what the person meant."""
    if not isinstance(value, str):
        raise RuleError("A moment is an ISO 8601 date and time with an offset.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise RuleError(f"{value!r} is not an ISO 8601 date and time.") from e
    if parsed.tzinfo is None:
        raise RuleError(f"{value!r} has no offset -- say which time zone it is in.")
    return parsed.astimezone(UTC)


def _time_of_day(value) -> time:
    if not isinstance(value, str):
        raise RuleError("A time of day is HH:MM.")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as e:
        raise RuleError(f"{value!r} is not a time of day (HH:MM).") from e
    return parsed.replace(second=0, microsecond=0, tzinfo=None)
