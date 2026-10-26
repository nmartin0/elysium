"""Totals by a fixed length, on a zone's clock (core/periods.py, BLOCKING.md
item 3's time-series reads; the owner's choice of ISO 8601 durations,
26 October, after Foundry's aggregate).

Europe/London's clocks went forward at 01:00 UTC on 29 March 2026 and
back at 01:00 UTC on 25 October 2026 -- the two nights these use."""

import datetime
import sqlite3

import pytest

from core.periods import MAX_PERIODS, Buckets, by_period, parse_duration, time_zone, with_gaps_filled

D = datetime.date
UTC = datetime.UTC
LONDON = time_zone("Europe/London")


def at(text: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(text)


class TestTheDuration:
    @pytest.mark.parametrize("text, length", [
        ("PT15M", datetime.timedelta(minutes=15)),
        ("PT1H", datetime.timedelta(hours=1)),
        ("P3D", datetime.timedelta(days=3)),
        ("P1DT12H", datetime.timedelta(days=1, hours=12)),
        ("PT30S", datetime.timedelta(seconds=30)),
        ("pt5m", datetime.timedelta(minutes=5)),
    ])
    def test_days_hours_minutes_and_seconds(self, text, length):
        assert parse_duration(text) == length

    @pytest.mark.parametrize("text, said", [
        ("P1W", "ask by period week"),
        ("P1M", "ask by period month"),
        ("P1Y", "not a fixed length"),
        ("15m", "not ISO 8601"),
        ("P", "not ISO 8601"),
        ("PT", "not ISO 8601"),
        ("P1DT", "not ISO 8601"),
        ("PT0S", "no time at all"),
    ])
    def test_what_is_not_a_fixed_length_is_refused_saying_why(self, text, said):
        with pytest.raises(ValueError, match=said):
            parse_duration(text)

    def test_an_unknown_zone_is_refused_with_an_example(self):
        with pytest.raises(ValueError, match="IANA name such as Europe/London"):
            time_zone("Mars/Olympus")


class TestTheBuckets:
    def test_a_quarter_hour_starts_on_the_quarter(self):
        quarter = Buckets(length=parse_duration("PT15M"))
        assert quarter.start(at("2026-10-14T10:07:00+00:00")) == at("2026-10-14T10:00:00+00:00")
        assert quarter.start(at("2026-10-14T10:15:00+00:00")) == at("2026-10-14T10:15:00+00:00")

    def test_days_are_counted_from_timescales_origin(self):
        # Monday 3 January 2000: three-day buckets begin on the 3rd, the
        # 6th, the 9th, whatever the data.
        three = Buckets(length=parse_duration("P3D"), dated=True)
        assert three.start(D(2000, 1, 8)) == D(2000, 1, 6)
        assert three.start(D(2000, 1, 9)) == D(2000, 1, 9)
        assert three.start(D(1999, 12, 31)) == D(1999, 12, 31)   # before it, too
        # Seven days begin on a Monday, as the origin did; five on the
        # 3rd and the 8th. (Three alone cannot tell this origin from the
        # Unix epoch: the days between them divide by three.)
        assert Buckets(length=parse_duration("P7D"), dated=True).start(D(2026, 10, 18)) == D(2026, 10, 12)
        assert Buckets(length=parse_duration("P5D"), dated=True).start(D(2000, 1, 7)) == D(2000, 1, 3)

    def test_a_day_is_the_zones_day(self):
        # 23:30 UTC on the 14th is 00:30 on the 15th in London's summer.
        late = at("2026-10-14T23:30:00+00:00")
        assert Buckets(period="day").start(late) == D(2026, 10, 14)
        assert Buckets(period="day", zone=LONDON).start(late) == D(2026, 10, 15)

    def test_an_hour_is_named_on_the_zones_clock(self):
        start = Buckets(length=parse_duration("PT1H"), zone=LONDON).start(at("2026-07-01T12:30:00+00:00"))
        assert start.isoformat() == "2026-07-01T13:00:00+01:00"

    def test_a_time_with_no_zone_is_not_moved_into_one(self):
        # A wall-clock reading already: 10:07 is 10:00's, in any zone.
        hour = Buckets(length=parse_duration("PT1H"), zone=LONDON)
        assert hour.start(at("2026-07-01T10:07:00")) == at("2026-07-01T10:00:00")

    def test_a_date_is_grouped_by_whole_days_only(self):
        with pytest.raises(ValueError, match="whole days only"):
            Buckets(length=parse_duration("PT1H"), dated=True)
        with pytest.raises(ValueError, match="whole days only"):
            Buckets(length=parse_duration("P1DT12H"), dated=True)


class TestTheClocksChanging:
    HOUR = Buckets(length=parse_duration("PT1H"), zone=LONDON)

    def test_the_repeated_autumn_hour_holds_both(self):
        # 00:30 UTC is 01:30 BST; 01:30 UTC is 01:30 GMT. One bucket, two.
        rows = [(at("2026-10-25T00:30:00+00:00"), "a"), (at("2026-10-25T01:30:00+00:00"), "b")]
        grouped = by_period(rows, self.HOUR)
        assert list(grouped.values()) == [["a", "b"]]
        assert [start.isoformat() for start in grouped] == ["2026-10-25T01:00:00+01:00"]

    def test_the_hour_spring_skips_is_never_offered_even_empty(self):
        # 00:30 UTC is 00:30 GMT; 01:30 UTC is 02:30 BST. 01:00 never was.
        rows = [(at("2026-03-29T00:30:00+00:00"), 1), (at("2026-03-29T01:30:00+00:00"), 1)]
        per = by_period(rows, self.HOUR)
        filled = with_gaps_filled({start: len(values) for start, values in per.items()},
                                  self.HOUR, "count")
        assert [start.isoformat() for start in filled] == [
            "2026-03-29T00:00:00+00:00", "2026-03-29T02:00:00+01:00"]

    def test_an_empty_hour_between_two_is_zero(self):
        rows = [(at("2026-07-01T09:10:00+00:00"), 1), (at("2026-07-01T11:10:00+00:00"), 1)]
        per = by_period(rows, Buckets(length=parse_duration("PT1H")))
        filled = with_gaps_filled({s: len(v) for s, v in per.items()},
                                  Buckets(length=parse_duration("PT1H")), "count")
        assert list(filled.values()) == [1, 0, 1]

    def test_too_many_buckets_asks_for_a_longer_duration(self):
        minute = Buckets(length=parse_duration("PT1M"))
        totals = {at("2026-07-01T00:00:00+00:00"): 1, at("2026-07-02T00:00:00+00:00"): 1}
        with pytest.raises(ValueError, match=f"more than {MAX_PERIODS} minutes.*longer duration"):
            with_gaps_filled(totals, minute, "count")


# -- through the mediator, under the caller's own access ------------------

SCHEMA = {
    "Reading": {
        "storage": {"silo": "s", "table": "readings", "id_column": "reading_id"},
        "id_field": "reading_id",
        "security": {"field": "site"},
        "fields": {
            "reading_id": {"type": "data"},
            "site": {"type": "data"},
            "taken": {"type": "data", "data_type": "timestamptz"},
            "day": {"type": "data", "data_type": "date"},
            "value": {"type": "data", "data_type": "number"},
        },
    },
}
ROWS = [  # (id, site, taken, day, value)
    ("r1", "north", "2026-07-01T09:05:00+00:00", "2026-07-01", 4.0),
    ("r2", "north", "2026-07-01T09:20:00+00:00", "2026-07-01", 6.0),
    ("r3", "north", "2026-07-01T09:50:00+00:00", "2026-07-02", 1.0),
    ("r4", "south", "2026-07-01T09:25:00+00:00", "2026-07-02", 50.0),  # not north's
]
ALL = ["read:Reading", "read:Reading.reading_id", "read:Reading.site", "read:Reading.taken",
       "read:Reading.day", "read:Reading.value"]


def _mediator(tmp_path, rows=ROWS):
    from adapters.sqlite_adapter import SQLiteWriteAdapter
    from core.ontology.mediator import DataMediator

    # One file per call: a test may build two, to compare them.
    db = tmp_path / f"readings-{len(list(tmp_path.glob('*.db')))}.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE readings (reading_id TEXT PRIMARY KEY, site TEXT, taken TEXT, "
                     "day TEXT, value REAL)")
        conn.executemany("INSERT INTO readings VALUES (?, ?, ?, ?, ?)", rows)
    roles = {"r": {"allowed_actions": frozenset(ALL)}}
    return DataMediator(SCHEMA, {"s": SQLiteWriteAdapter({"path": db})}, {"Reading": "s"}, roles)


def _north():
    from core.intermediate_layer.auth import resolve_user_record

    return resolve_user_record({"n": {"org_id": "north", "role": "r"}}, "n", "org_id")


class TestThroughTheMediator:
    def test_summed_by_the_quarter_hour_in_the_callers_zone(self, tmp_path):
        totals = _mediator(tmp_path).aggregate_by_field(
            _north(), "Reading", [], group_by="taken", aggregate="sum", field_name="value",
            duration="PT15M", time_zone="Europe/London")
        assert {start.isoformat(): total for start, total in totals.items()} == {
            "2026-07-01T10:00:00+01:00": 4.0,
            "2026-07-01T10:15:00+01:00": 6.0,
            "2026-07-01T10:30:00+01:00": 0,
            "2026-07-01T10:45:00+01:00": 1.0,
        }

    def test_a_date_by_whole_days(self, tmp_path):
        totals = _mediator(tmp_path).aggregate_by_field(
            _north(), "Reading", [], group_by="day", aggregate="count", duration="P1D")
        assert totals == {D(2026, 7, 1): 2, D(2026, 7, 2): 1}

    @pytest.mark.parametrize("arguments, said", [
        ({"group_by": "day", "duration": "PT1H"}, "whole days only"),
        ({"group_by": "taken", "duration": "PT1H", "period": "day"}, "one of them, not both"),
        ({"group_by": "taken", "time_zone": "Europe/London"}, "ask for a period or a duration"),
        ({"group_by": "site", "duration": "PT1H"}, "must name a date"),
        ({"group_by": "taken", "duration": "PT1H", "time_zone": "Nowhere/At_All"}, "Unknown time zone"),
    ])
    def test_what_cannot_be_bucketed_says_why(self, tmp_path, arguments, said):
        with pytest.raises(ValueError, match=said):
            _mediator(tmp_path).aggregate_by_field(_north(), "Reading", [], aggregate="count",
                                                   **arguments)


class TestTheGroupsTheRouteWrites:
    def test_a_buckets_start_is_iso_8601_with_its_offset(self):
        from api.routes import _aggregate_group

        assert _aggregate_group(at("2026-07-01T10:15:00+01:00")) == "2026-07-01T10:15:00+01:00"
        assert _aggregate_group(D(2026, 7, 1)) == "2026-07-01"

    def test_anything_else_is_left_as_it_is(self):
        from api.routes import _aggregate_group

        assert _aggregate_group(2026) == 2026
        assert _aggregate_group("north") == "north"


class TestFirstAndLast:
    """The value at the earliest and the latest moment of each bucket --
    TimescaleDB's first() and last() -- which with max and min make a
    candlestick."""

    def _per_hour(self, tmp_path, aggregate, rows=ROWS):
        totals = _mediator(tmp_path, rows).aggregate_by_field(
            _north(), "Reading", [], group_by="taken", aggregate=aggregate, field_name="value",
            duration="PT1H")
        return {start.isoformat(): value for start, value in totals.items()}

    def test_an_hours_open_high_low_and_close(self, tmp_path):
        # North's 09:05 4.0, 09:20 6.0, 09:50 1.0 -- not in that order by
        # id or by value, so neither can stand in for time.
        hour = "2026-07-01T09:00:00+00:00"
        assert [self._per_hour(tmp_path, a)[hour] for a in ("first", "max", "min", "last")] == \
            [4.0, 6.0, 1.0, 1.0]

    def test_read_in_any_order_the_answer_is_the_same(self, tmp_path):
        backwards = list(reversed(ROWS))
        assert self._per_hour(tmp_path, "first", backwards) == self._per_hour(tmp_path, "first")
        assert self._per_hour(tmp_path, "last", backwards) == self._per_hour(tmp_path, "last")

    def test_two_at_one_moment_are_told_apart_by_id(self, tmp_path):
        tied = [*ROWS, ("r0", "north", "2026-07-01T09:05:00+00:00", "2026-07-01", 9.0),
                ("r9", "north", "2026-07-01T09:50:00+00:00", "2026-07-01", 7.0)]
        hour = "2026-07-01T09:00:00+00:00"
        assert self._per_hour(tmp_path, "first", tied)[hour] == 9.0    # r0 before r1
        assert self._per_hour(tmp_path, "last", tied)[hour] == 7.0     # r9 after r3

    def test_an_empty_bucket_has_no_first_rather_than_a_zero(self, tmp_path):
        later = [*ROWS, ("r5", "north", "2026-07-01T11:30:00+00:00", "2026-07-01", 3.0)]
        assert self._per_hour(tmp_path, "first", later) == {
            "2026-07-01T09:00:00+00:00": 4.0, "2026-07-01T11:00:00+00:00": 3.0}

    def test_a_null_value_is_never_the_first(self, tmp_path):
        early_null = [*ROWS, ("r0", "north", "2026-07-01T09:01:00+00:00", "2026-07-01", None)]
        assert self._per_hour(tmp_path, "first", early_null)["2026-07-01T09:00:00+00:00"] == 4.0

    @pytest.mark.parametrize("aggregate", ["first", "last"])
    def test_without_time_buckets_there_is_no_first_or_last(self, tmp_path, aggregate):
        with pytest.raises(ValueError, match="needs one: group_by a date or timestamp field"):
            _mediator(tmp_path).aggregate_by_field(_north(), "Reading", [], group_by="site",
                                                   aggregate=aggregate, field_name="value")

    def test_moments_written_in_other_offsets_are_ordered_as_instants(self, tmp_path):
        # 10:04 at +01:00 is 09:04 UTC: a minute before r1, though it
        # sorts after it as text.
        offset = [*ROWS, ("r0", "north", "2026-07-01T10:04:00+01:00", "2026-07-01", 8.0)]
        assert self._per_hour(tmp_path, "first", offset)["2026-07-01T09:00:00+00:00"] == 8.0

    def test_the_tie_is_broken_by_id_and_not_by_the_order_read(self):
        # Directly: the database hands rows back in id order, which would
        # hide a rule that only took the first one it was given.
        from core.ontology.mediator import _ORDERED

        moment = (at("2026-07-01T09:05:00"),)
        timed = [(moment, "r5", "five"), (moment, "r1", "one"), (moment, "r9", "nine")]
        assert _ORDERED["first"](timed) == "one"
        assert _ORDERED["last"](timed) == "nine"
