"""Records counted or summed per day, week or month (R68's ground).

A total over time is the series a forecast extends, and a chart over
time is the first thing anyone asks of a date. Before this the aggregate
grouped by a date field's EXACT value -- one bar per distinct date, no
gaps -- which is a list of dates, not a series.

THREE PERIODS, the ones people say: a day, an ISO week (Monday to
Sunday, ISO 8601 -- the definition every calendar library shares), and
a calendar month. Each period is named by the date it starts on, so the
keys sort and parse as dates.

IN UTC. A timestamp is bucketed by the UTC day it falls on: a
`timestamptz` is stored as an instant in UTC (field_types), and this
deployment has no zone of its own to prefer. A `date` has no zone and is
its own day.

GAPS ARE ZERO -- for a count or a sum, and only between the first and
last period that has a record. A week with no records had none; that is
a fact, and leaving it out would draw a line straight across it and
teach a forecast that nothing happened slowly. An average, a minimum or
a maximum of nothing is not zero, so those keep their gaps.

A CEILING ON PERIODS: a day-by-day series over decades is a chart nobody
can read and a forecast nobody should fit. Asking for more than
MAX_PERIODS is refused with the longer period to ask for instead.
"""

import datetime
from collections.abc import Iterable
from typing import Any

PERIODS = ("day", "week", "month")
TEMPORAL = frozenset({"date", "timestamp", "timestamptz"})
MAX_PERIODS = 1_000
#: Aggregates whose value for a period with no records is 0.
ZERO_WHEN_EMPTY = frozenset({"count", "sum"})


def period_start(value: Any, period: str) -> "datetime.date | None":
    """The first day of the period `value` falls in, or None when it is
    not a date. Text is read as ISO 8601, which is how an adapter that
    does not type dates hands them back."""
    day = _day(value)
    if day is None:
        return None
    if period == "day":
        return day
    if period == "week":
        return day - datetime.timedelta(days=day.weekday())
    if period == "month":
        return day.replace(day=1)
    raise ValueError(f"Unknown period {period!r} -- expected one of {list(PERIODS)}")


def _day(value: Any) -> "datetime.date | None":
    if isinstance(value, datetime.datetime):
        if value.tzinfo is not None:
            value = value.astimezone(datetime.UTC)
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            return _day(datetime.datetime.fromisoformat(text))
        except ValueError:
            try:
                return datetime.date.fromisoformat(text[:10])
            except ValueError:
                return None
    return None


def next_period(start: datetime.date, period: str) -> datetime.date:
    if period == "day":
        return start + datetime.timedelta(days=1)
    if period == "week":
        return start + datetime.timedelta(days=7)
    if start.month == 12:
        return start.replace(year=start.year + 1, month=1)
    return start.replace(month=start.month + 1)


def periods_between(first: datetime.date, last: datetime.date, period: str) -> list[datetime.date]:
    """Every period start from `first` to `last`, both included. Refused
    past MAX_PERIODS, naming the longer period to use instead."""
    out: list[datetime.date] = []
    current = first
    while current <= last:
        out.append(current)
        if len(out) > MAX_PERIODS:
            longer = {"day": "week", "week": "month"}.get(period)
            hint = f" Ask by {longer} instead." if longer else ""
            raise ValueError(f"That is more than {MAX_PERIODS} {period}s of records.{hint}")
        current = next_period(current, period)
    return out


def with_gaps_filled(totals: dict, period: str, aggregate: str) -> dict:
    """{period start: total} with every empty period between the first and
    the last present -- as 0 for a count or a sum, absent otherwise."""
    if not totals:
        return {}
    starts = sorted(totals)
    if aggregate not in ZERO_WHEN_EMPTY:
        # Still bounded: a min over two dates decades apart has only two
        # keys, but a caller drawing it will lay out every period.
        periods_between(starts[0], starts[-1], period)
        return {start: totals[start] for start in starts}
    return {start: totals.get(start, 0) for start in periods_between(starts[0], starts[-1], period)}


def by_period(rows: Iterable[tuple[Any, Any]], period: str) -> dict:
    """[(date value, value)] -> {period start: [values]}; rows whose date
    is not a date are left out, as a null group is."""
    grouped: dict = {}
    for when, value in rows:
        start = period_start(when, period)
        if start is not None:
            grouped.setdefault(start, []).append(value)
    return grouped
