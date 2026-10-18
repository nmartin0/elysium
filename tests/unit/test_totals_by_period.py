"""Records counted or summed per day, week or month (core/periods.py),
and through the mediator, under the caller's own access."""

import datetime
import sqlite3

import pytest

from core.periods import MAX_PERIODS, period_start, periods_between, with_gaps_filled

D = datetime.date


class TestThePeriods:
    @pytest.mark.parametrize("value, period, start", [
        (D(2026, 10, 14), "day", D(2026, 10, 14)),
        (D(2026, 10, 14), "week", D(2026, 10, 12)),     # a Wednesday; the week began Monday
        (D(2026, 10, 12), "week", D(2026, 10, 12)),
        (D(2026, 10, 18), "week", D(2026, 10, 12)),     # Sunday ends it
        (D(2026, 10, 14), "month", D(2026, 10, 1)),
        ("2026-10-14", "week", D(2026, 10, 12)),
        ("2026-10-14T23:30:00", "day", D(2026, 10, 14)),
        # AN INSTANT IS ITS UTC DAY: 01:30 in Auckland is still the 13th in UTC.
        (datetime.datetime(2026, 10, 14, 1, 30,
                           tzinfo=datetime.timezone(datetime.timedelta(hours=13))),
         "day", D(2026, 10, 13)),
    ])
    def test_each_value_falls_in_the_period_it_starts(self, value, period, start):
        assert period_start(value, period) == start

    @pytest.mark.parametrize("value", [None, "", "not a date", 42])
    def test_what_is_not_a_date_is_in_no_period(self, value):
        assert period_start(value, "day") is None

    def test_months_roll_over_the_year(self):
        assert periods_between(D(2026, 11, 1), D(2027, 2, 1), "month") == [
            D(2026, 11, 1), D(2026, 12, 1), D(2027, 1, 1), D(2027, 2, 1)]

    def test_an_empty_period_is_zero_for_a_count_or_a_sum_and_absent_otherwise(self):
        totals = {D(2026, 10, 5): 3, D(2026, 10, 19): 1}
        assert with_gaps_filled(totals, "week", "count") == {
            D(2026, 10, 5): 3, D(2026, 10, 12): 0, D(2026, 10, 19): 1}
        assert with_gaps_filled(totals, "week", "avg") == totals

    def test_too_many_periods_is_refused_with_the_longer_one_to_ask_for(self):
        with pytest.raises(ValueError, match=f"more than {MAX_PERIODS} days.*by week"):
            periods_between(D(2020, 1, 1), D(2026, 1, 1), "day")


SCHEMA = {
    "Order": {
        "storage": {"silo": "s", "table": "orders", "id_column": "order_id"},
        "id_field": "order_id",
        "security": {"field": "region"},
        "fields": {
            "order_id": {"type": "data"},
            "region": {"type": "data"},
            "placed": {"type": "data", "data_type": "date"},
            "note": {"type": "data"},
            "amount": {"type": "data", "data_type": "number"},
        },
    },
}
ROWS = [  # (id, region, placed, amount)
    ("o1", "west", "2026-10-05", 10.0),
    ("o2", "west", "2026-10-07", 5.0),
    ("o3", "west", "2026-10-21", 2.5),
    ("o4", "east", "2026-10-14", 100.0),   # another compartment, in the empty week
    ("o5", "west", None, 1.0),             # no date: in no period
]


def _mediator(tmp_path, actions):
    from adapters.sqlite_adapter import SQLiteWriteAdapter
    from core.ontology.mediator import DataMediator

    db = tmp_path / "orders.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE orders (order_id TEXT PRIMARY KEY, region TEXT, placed TEXT, "
                     "note TEXT, amount REAL)")
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, 'x', ?)", ROWS)
    roles = {"r": {"allowed_actions": frozenset(actions)}}
    return DataMediator(SCHEMA, {"s": SQLiteWriteAdapter({"path": db})}, {"Order": "s"}, roles)


def _west():
    from core.intermediate_layer.auth import resolve_user_record

    return resolve_user_record({"w": {"org_id": "west", "role": "r"}}, "w", "org_id")


ALL = ["read:Order", "read:Order.order_id", "read:Order.region", "read:Order.placed",
       "read:Order.amount", "read:Order.note"]


class TestThroughTheMediator:
    def test_counted_by_week_with_the_empty_week_as_zero(self, tmp_path):
        totals = _mediator(tmp_path, ALL).aggregate_by_field(
            _west(), "Order", [], group_by="placed", aggregate="count", period="week")
        # o4 is east's: the west caller's empty week stays empty.
        assert totals == {D(2026, 10, 5): 2, D(2026, 10, 12): 0, D(2026, 10, 19): 1}

    def test_summed_by_month(self, tmp_path):
        totals = _mediator(tmp_path, ALL).aggregate_by_field(
            _west(), "Order", [], group_by="placed", aggregate="sum", field_name="amount",
            period="month")
        assert totals == {D(2026, 10, 1): 17.5}

    def test_without_read_on_the_date_nothing_is_in_any_period(self, tmp_path):
        mediator = _mediator(tmp_path, [a for a in ALL if a != "read:Order.placed"])
        assert mediator.aggregate_by_field(_west(), "Order", [], group_by="placed",
                                           aggregate="count", period="week") == {}

    @pytest.mark.parametrize("group_by, period, why", [
        ("note", "week", "must name a date"),
        (None, "week", "must name a date"),
        ("placed", "fortnight", "Unknown period"),
    ])
    def test_a_period_needs_a_date_and_a_known_period(self, tmp_path, group_by, period, why):
        with pytest.raises(ValueError, match=why):
            _mediator(tmp_path, ALL).aggregate_by_field(
                _west(), "Order", [], group_by=group_by, aggregate="count", period=period)
