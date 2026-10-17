"""When a date-filtered trigger's count can next change (16 October).

A view filtered "in the last N days" changes in two ways: data arrives
(a sync, a saved change -- core/trigger_runs.py checks then), or a
record crosses the edge of the window as time passes. The second is
predictable. A record dated T leaves "the last N days" at exactly T + N
days; a record dated T enters "more than N days ago" at T + N days --
and the same in hours. So
the next moment a count can change with no new data is

    min(T over records still inside that edge) + N

and the trigger sets a timer for that moment (core/timers.py) instead
of being polled. When it fires the trigger is evaluated -- re-checked,
never trusted -- and sets its next one. When data arrives the
evaluation that follows sets it again, because a new record may cross
sooner than any old one.

ASKED AS EACH RECIPIENT, with their own authority, through the same
aggregate every chart uses. Two people may see different records, so
each has their own next crossing, and the trigger wakes at the earliest.
Nothing about anybody's records is stored or shown -- only a time.

EARLY IS HARMLESS, LATE IS NOT. The question asked is slightly broader
than the view when it has to be -- each edge is asked about on its own,
and a `date` field crosses at midnight -- so a wake may find nothing
changed. That costs one evaluation. Nothing here can make one late.

AT MOST ONE WAKE A MINUTE (MIN_SPACING_SECONDS). A busy table can have
a record crossing every second; a trigger re-evaluated every second
would be a load, not a notice.
"""

import logging
from datetime import UTC, date, datetime
from typing import Any

logger = logging.getLogger(__name__)

#: The timer kind a date-filtered trigger registers.
KIND = "trigger.window"
#: The soonest a trigger is woken after it was last evaluated.
MIN_SPACING_SECONDS = 60.0


def now() -> datetime:
    """The present, in one place, so a test can pin it."""
    return datetime.now(UTC)


def next_crossing(mediator: Any, view: Any, recipients: list,
                  now: datetime) -> "datetime | None":
    """The earliest moment any recipient's count can change with no new
    data, or None if no record will ever cross an edge."""
    from core.filters import FieldFilter, relative_window

    conditions = [_as_filter(condition) for condition in (view.conditions or [])]
    soonest: datetime | None = None
    for index, condition in enumerate(conditions):
        if condition.operator != "relative_date":
            continue
        others = conditions[:index] + conditions[index + 1:]
        # IN WHATEVER UNIT IT COUNTS -- days or hours -- through the
        # one helper every reader of a relative date uses.
        for span in relative_window(condition.value or {}):
            if span is None:
                continue
            edge = now - span
            # Records at or after the edge are the ones still to cross it.
            still_to_cross = FieldFilter(condition.field, "date_range",
                                         {"start": edge.isoformat(), "end": None})
            for recipient in recipients:
                earliest = _earliest(mediator, recipient, view, condition.field,
                                     [*others, still_to_cross])
                if earliest is None:
                    continue
                crossing = earliest + span
                if soonest is None or crossing < soonest:
                    soonest = crossing
    return soonest


def schedule(timers: Any, trigger: Any, mediator: Any, view: Any,
             recipients: list, now: datetime) -> "float | None":
    """Sets (or clears) this trigger's wake. Returns the time set."""
    crossing = next_crossing(mediator, view, recipients, now)
    if crossing is None:
        # NOTHING LEFT TO CROSS. The next record that arrives comes
        # with an evaluation, and that evaluation schedules again.
        timers.cancel(KIND, trigger.trigger_id)
        return None
    due = max(crossing.timestamp(), now.timestamp() + MIN_SPACING_SECONDS)
    timers.set(KIND, trigger.trigger_id, due)
    return due


def _earliest(mediator, recipient, view, field: str, conditions: list) -> "datetime | None":
    try:
        result = mediator.aggregate_by_field(
            recipient, view.object_type, conditions, None, "min", field,
            query_text=view.query_text or "",
        )
    except Exception as e:  # noqa: BLE001 - one recipient costs only their own crossing
        logger.warning("could not find the next crossing of %r as %s: %s",
                       view.name, getattr(recipient, "user_id", "?"), e)
        return None
    return _instant(result.get(None)) if result else None


def _instant(value: Any) -> "datetime | None":
    """A stored date or time as an aware UTC datetime, or None.

    Stored as text in most silos (ISO 8601, with or without a time or an
    offset) and as a date or datetime in the mirror. A date is its
    midnight UTC, the same reading core/filters.resolved gives one. A
    value that is none of these cannot be scheduled from, and is
    skipped rather than guessed.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _as_filter(condition: Any):
    from core.filters import FieldFilter

    if isinstance(condition, dict):
        return FieldFilter(condition["field"], condition["operator"], condition.get("value"))
    return condition
