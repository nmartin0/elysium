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

FIXED LENGTHS TOO, AS ISO 8601 DURATIONS (the owner's choice, 26
October, after Foundry): `PT15M`, `PT1H`, `P3D`. Foundry's aggregate
groups "according to a date or timestamp interval" written so, and
"Date properties only support grouping by days (e.g. `P3D` but not
`PT3H`)", which is the rule here. A week and a month are not fixed
lengths, so they stay periods; a duration naming either is refused with
the period to use.

ALIGNED AS TIMESCALEDB ALIGNS THEM: every bucket is counted from an
origin, by default "midnight on January 3, 2000" (a Monday), so a
three-day bucket starts on the same days whatever the data; a bucket is
named by its start.

IN A TIME ZONE, when one is asked for: TimescaleDB's buckets "are
realigned to start at midnight in the time zone you specify", and so are
these -- a day, a week, a month or a fixed length is counted on that
zone's clock. Around a change of clocks that makes a bucket irregular,
as TimescaleDB says of its own ("a 2-hour bucket may hold three hours
or one"): the repeated hour of an autumn night holds both, and the hour
a spring night skips is never offered, not even as an empty one. Only
an instant is moved into the zone. A date is its own day, and a time
with no zone (`timestamp`) is a wall-clock reading already, so neither
is converted.
"""

import datetime
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PERIODS = ("day", "week", "month")
TEMPORAL = frozenset({"date", "timestamp", "timestamptz"})
MAX_PERIODS = 1_000
#: Aggregates whose value for a period with no records is 0.
ZERO_WHEN_EMPTY = frozenset({"count", "sum"})
#: TimescaleDB's default origin for buckets shorter than a month.
ORIGIN = datetime.datetime(2000, 1, 3)
_DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?")


def parse_duration(text: str) -> datetime.timedelta:
    """An ISO 8601 duration of days, hours, minutes and seconds, as
    Foundry's aggregate takes one. Weeks, months and years are refused
    with the period to ask for: they are not fixed lengths."""
    cleaned = str(text).strip().upper()
    if re.fullmatch(r"P\d+[WMY]", cleaned):
        unit = {"W": "week", "M": "month", "Y": "year"}[cleaned[-1]]
        hint = f" -- ask by period {unit} instead" if unit != "year" else ""
        raise ValueError(f"A duration of {unit}s is not a fixed length{hint}.")
    match = _DURATION.fullmatch(cleaned)
    if match is None or cleaned in ("P", "PT") or cleaned.endswith("T"):
        raise ValueError(f"Duration {text!r} is not ISO 8601 days, hours, minutes and "
                         f"seconds, such as PT15M, PT1H or P3D.")
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    length = datetime.timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    if length <= datetime.timedelta(0):
        raise ValueError(f"Duration {text!r} is no time at all.")
    return length


def time_zone(name: "str | None") -> ZoneInfo:
    """An IANA zone, such as Europe/London; UTC when none is named."""
    if name is None or not str(name).strip():
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(str(name).strip())
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown time zone {name!r} -- give an IANA name such as "
                         f"Europe/London or America/New_York.") from None


@dataclass(frozen=True)
class Buckets:
    """How values are put into buckets: a named period, or a fixed
    length, on one zone's clock. `dated` is a date field's: whole days,
    and no zone to move it into."""

    period: "str | None" = None
    length: "datetime.timedelta | None" = None
    zone: ZoneInfo = ZoneInfo("UTC")
    dated: bool = False

    def __post_init__(self) -> None:
        if (self.period is None) == (self.length is None):
            raise ValueError("Group by a period or by a duration -- one of them, not both.")
        if self.period is not None and self.period not in PERIODS:
            raise ValueError(f"Unknown period {self.period!r} -- expected one of {list(PERIODS)}")
        if self.dated and self.length is not None and self.length % datetime.timedelta(days=1):
            raise ValueError("A date has no time of day, so it is grouped by whole days only "
                             "(P1D, P3D), not by hours, minutes or seconds.")

    def describe(self) -> str:
        return self.period or _spoken(self.length)

    def start(self, value: Any) -> "datetime.date | datetime.datetime | None":
        """The start of the bucket `value` falls in, or None when it is
        not a date or a time."""
        if self.period is not None:
            day = _day(value, self.zone)
            return None if day is None else period_start(day, self.period)
        moment = _moment(value)
        if moment is None:
            return None
        assert self.length is not None
        if self.dated or not isinstance(moment, datetime.datetime):
            day = moment.date() if isinstance(moment, datetime.datetime) else moment
            steps = (day - ORIGIN.date()).days // self.length.days
            return ORIGIN.date() + datetime.timedelta(days=steps * self.length.days)
        aware = moment.tzinfo is not None
        wall = moment.astimezone(self.zone).replace(tzinfo=None) if aware else moment
        steps = (wall - ORIGIN) // self.length
        start = ORIGIN + steps * self.length
        # fold=0: the earlier of an autumn night's two 01:00s names the
        # bucket both fall in, so they are one key, as TimescaleDB's are.
        return start.replace(tzinfo=self.zone) if aware else start

    def after(self, start: Any) -> Any:
        """The start of the next bucket. On a zone's clock, a start the
        clocks skip is passed over: no instant falls in it."""
        if self.period is not None:
            return next_period(start, self.period)
        assert self.length is not None
        if not isinstance(start, datetime.datetime):
            return start + self.length
        if start.tzinfo is None:
            return start + self.length
        wall = start.replace(tzinfo=None) + self.length
        while not _exists(wall, self.zone):
            wall += self.length
        return wall.replace(tzinfo=self.zone)


def _exists(wall: datetime.datetime, zone: ZoneInfo) -> bool:
    there = wall.replace(tzinfo=zone)
    return there.astimezone(datetime.UTC).astimezone(zone).replace(tzinfo=None) == wall


def _spoken(length: "datetime.timedelta | None") -> str:
    assert length is not None
    seconds = int(length.total_seconds())
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds % size == 0:
            count = seconds // size
            return f"{count}-{unit}" if count != 1 else unit
    return f"{seconds}-second"


def buckets(period: "str | Buckets") -> Buckets:
    return period if isinstance(period, Buckets) else Buckets(period=period)


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


def _day(value: Any, zone: "ZoneInfo | None" = None) -> "datetime.date | None":
    moment = _moment(value)
    if isinstance(moment, datetime.datetime):
        if moment.tzinfo is not None:
            moment = moment.astimezone(zone or datetime.UTC)
        return moment.date()
    return moment


def _moment(value: Any) -> "datetime.date | datetime.datetime | None":
    """A date or a time, from what an adapter hands back. Text is read
    as ISO 8601, which is how an adapter that does not type dates hands
    them back."""
    if isinstance(value, datetime.datetime | datetime.date):
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            parsed = datetime.datetime.fromisoformat(text)
        except ValueError:
            try:
                return datetime.date.fromisoformat(text[:10])
            except ValueError:
                return None
        # A date written alone is a date, not midnight.
        return parsed.date() if len(text) == 10 else parsed
    return None


def moment_order(value: Any) -> tuple:
    """A key putting moments in time order within one bucket: an instant
    by its UTC time, a wall-clock reading or a date as itself. Values
    that are no moment at all are never in a bucket, so never reach here."""
    moment = _moment(value)
    if isinstance(moment, datetime.datetime):
        if moment.tzinfo is not None:
            return (moment.astimezone(datetime.UTC).replace(tzinfo=None),)
        return (moment,)
    assert moment is not None
    return (datetime.datetime.combine(moment, datetime.time()),)


def next_period(start: datetime.date, period: str) -> datetime.date:
    if period == "day":
        return start + datetime.timedelta(days=1)
    if period == "week":
        return start + datetime.timedelta(days=7)
    if start.month == 12:
        return start.replace(year=start.year + 1, month=1)
    return start.replace(month=start.month + 1)


def periods_between(first: Any, last: Any, period: "str | Buckets") -> list:
    """Every period start from `first` to `last`, both included. Refused
    past MAX_PERIODS, naming the longer period to use instead."""
    chosen = buckets(period)
    out: list = []
    current = first
    while current <= last:
        out.append(current)
        if len(out) > MAX_PERIODS:
            name = chosen.describe()
            longer = {"day": "week", "week": "month"}.get(name)
            hint = (f" Ask by {longer} instead." if longer
                    else " Ask with a longer duration." if chosen.length is not None else "")
            raise ValueError(f"That is more than {MAX_PERIODS} {name}s of records.{hint}")
        current = chosen.after(current)
    return out


def with_gaps_filled(totals: dict, period: "str | Buckets", aggregate: str) -> dict:
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


def by_period(rows: Iterable[tuple[Any, Any]], period: "str | Buckets") -> dict:
    """[(date value, value)] -> {period start: [values]}; rows whose date
    is not a date are left out, as a null group is."""
    chosen = buckets(period)
    grouped: dict = {}
    for when, value in rows:
        start = chosen.start(when)
        if start is not None:
            grouped.setdefault(start, []).append(value)
    return grouped
