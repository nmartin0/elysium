"""Forecasts of totals per period (R68): made, tested against the naive
forecast, and refused when they do not beat it -- on synthetic series
whose shape is known."""

import datetime

import numpy as np
import pytest

import core.forecasts as forecasts
from core.forecasts import (
    HORIZON,
    MIN_PERIODS,
    cached_forecast,
    finished_series,
    forecast,
)
from core.periods import next_period

D = datetime.date


def _starts(first, period, count):
    starts = [first]
    while len(starts) < count:
        starts.append(next_period(starts[-1], period))
    return starts


def _weekly_trend(count=60, seed=0):
    rng = np.random.default_rng(seed)
    return list(30 + 0.4 * np.arange(count) + rng.normal(0, 2, count))


class TestTheSeries:
    def test_carried_on_to_today_with_zeros_and_the_running_period_apart(self):
        totals = {D(2026, 9, 7): 4, D(2026, 9, 14): 0, D(2026, 9, 21): 2}
        series = finished_series(totals, "week", D(2026, 10, 14))
        assert series.starts == [D(2026, 9, 7), D(2026, 9, 14), D(2026, 9, 21), D(2026, 9, 28),
                                 D(2026, 10, 5)]
        assert series.values == [4, 0, 2, 0, 0], "three weeks of none since are history too"
        assert series.running == (D(2026, 10, 12), 0)

    def test_a_record_dated_after_today_is_not_history(self):
        totals = {D(2026, 10, 5): 3, D(2026, 10, 12): 1, D(2026, 11, 2): 9}
        series = finished_series(totals, "week", D(2026, 10, 14))
        assert series.starts == [D(2026, 10, 5)] and series.running == (D(2026, 10, 12), 1)
        assert 9 not in series.values

    def test_the_first_period_is_shown_but_not_fitted(self):
        # The records begin part-way through it, nearly always, so its
        # total is a part one; core/forecasts.py has the measurement.
        totals = {D(2026, 9, 7): 1, D(2026, 9, 14): 30, D(2026, 9, 21): 31}
        series = finished_series(totals, "week", D(2026, 9, 30))
        assert series.values == [1, 30, 31]
        assert series.to_fit == ([D(2026, 9, 14), D(2026, 9, 21)], [30, 31])

    def test_nothing_yet_is_nothing(self):
        assert finished_series({}, "week", D(2026, 10, 14)).starts == []
        assert finished_series({D(2027, 1, 4): 2}, "week", D(2026, 10, 14)).starts == []


class TestForecasting:
    def test_a_trend_is_carried_forward_with_a_band_and_beats_the_naive_forecast(self):
        values = _weekly_trend()
        made = forecast(values, _starts(D(2025, 9, 1), "week", 60), "week", count=True)
        assert made.refusal is None
        assert len(made.points) == HORIZON["week"]
        backtest = made.backtest
        assert backtest["origins"] == forecasts.ORIGINS
        assert backtest["typical_miss"] < backtest["naive_miss"]
        assert made.points[0]["start"] == next_period(_starts(D(2025, 9, 1), "week", 60)[-1],
                                                       "week").isoformat()
        assert all(point["low"] <= point["value"] <= point["high"] for point in made.points)
        # STILL RISING, BUT DAMPED: ahead of the last values, never at the
        # full undamped slope for eight weeks.
        assert values[-1] - 5 < made.points[0]["value"]
        assert made.points[-1]["value"] < values[-1] + 0.4 * 8 + 5

    def test_a_weekly_season_is_learned_from_days_with_two_full_seasons(self):
        rng = np.random.default_rng(1)
        starts = _starts(D(2026, 1, 1), "day", 120)
        values = [max(0.0, 10 + (4 if day.weekday() < 5 else -6) + rng.normal(0, 1))
                  for day in starts]
        made = forecast(values, starts, "day", count=True)
        assert made.season == 7 and made.refusal is None
        weekday_of = [datetime.date.fromisoformat(point["start"]).weekday()
                      for point in made.points]
        weekend = [p["value"] for p, day in zip(made.points, weekday_of, strict=True) if day >= 5]
        weekday = [p["value"] for p, day in zip(made.points, weekday_of, strict=True) if day < 5]
        assert max(weekend) < min(weekday)

    def test_no_season_without_two_full_ones(self):
        made = forecast(_weekly_trend(60), _starts(D(2025, 9, 1), "week", 60), "week",
                        count=True)
        assert made.season is None, "60 weeks is not two years"

    def test_a_season_only_when_every_test_sees_two_full_ones(self):
        """30 days hold four weeks, but the earliest test point sees ten
        days: a season chosen anyway cannot be fitted there, and nothing
        would be drawn at all."""
        rng = np.random.default_rng(2)
        starts = _starts(D(2026, 3, 2), "day", 30)
        values = [10 + (3 if day.weekday() < 5 else -3) + rng.normal(0, 1) for day in starts]
        made = forecast(values, starts, "day", count=True)
        assert made.season is None and made.points, made.refusal

    def test_too_little_history_is_refused_and_said(self):
        made = forecast([1.0] * (MIN_PERIODS - 1), _starts(D(2026, 1, 5), "week",
                                                         MIN_PERIODS - 1), "week", count=True)
        assert made.points == [] and f"at least {MIN_PERIODS}" in made.refusal

    def test_a_forecast_no_better_than_the_naive_one_is_not_drawn(self, monkeypatch):
        class Wild:
            aicc = 0.0

            def forecast(self, steps):
                return np.full(steps, 1_000.0)

        monkeypatch.setattr(forecasts, "_fit", lambda values, form: Wild())
        made = forecast(_weekly_trend(), _starts(D(2025, 9, 1), "week", 60), "week", count=True)
        assert made.points == []
        assert "missed by as much as simply carrying the last week on" in made.refusal
        assert made.backtest["typical_miss"] > made.backtest["naive_miss"]

    def test_a_steady_series_is_drawn_though_the_naive_one_is_as_good(self):
        made = forecast([5.0] * 30, _starts(D(2026, 1, 5), "week", 30), "week", count=True)
        assert made.refusal is None and made.points

    def test_a_count_never_goes_below_zero(self):
        values = list(np.maximum(0, 60 - 2.5 * np.arange(26)))
        made = forecast(values, _starts(D(2026, 1, 5), "week", 26), "week", count=True)
        assert made.points and all(point["low"] >= 0 and point["value"] >= 0
                                   for point in made.points)

    def test_a_sum_may(self):
        values = list(10 - 3.0 * np.arange(30))
        made = forecast(values, _starts(D(2026, 1, 5), "week", 30), "week", count=False)
        assert made.points and min(point["low"] for point in made.points) < 0

    def test_the_same_series_is_forecast_once(self, monkeypatch):
        values, starts = _weekly_trend(40, seed=5), _starts(D(2025, 9, 1), "week", 40)
        first = cached_forecast(values, starts, "week", True)
        monkeypatch.setattr(forecasts, "forecast", lambda *a, **k: pytest.fail("not cached"))
        assert cached_forecast(values, starts, "week", True) is first
