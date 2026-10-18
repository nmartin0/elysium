"""Where a total per period is heading (R68): a forecast, tested before it
is shown.

The series is a count or a sum per day, week or month (core/periods.py),
of the records the viewer may see -- so a forecast is computed per
request from that viewer's own totals, never stored, and crosses no
compartment (the owner, 18 October: no approval, because nothing is
served as data).

EXPONENTIAL SMOOTHING (statsmodels' ETS), THE FORM CHOSEN BY AICc: no
trend, a trend, or a DAMPED trend -- one that fades rather than running
on forever, which is why it does so well in forecasting competitions
(Gardner & McKenzie, "Why the damped trend works", Journal of the
Operational Research Society, 2011) -- each with a season or without.
Choosing among them by AICc on the whole history is what Hyndman's own
automatic ets() does. A single fixed form was tried first and failed on a
slowly rising weekly series: the damped trend flattened too soon and
missed by more than carrying the last week on (3.97 against 3.41),
where the AICc's choice, a plain trend, missed by 2.81. A SEASON is a
candidate only when there are at least two full ones to learn it from --
a week for days, a year for weeks or months -- the rule Datadog's
seasonal forecasts state: "at least two seasons of history".

TESTED THE WAY IT WILL BE USED, NEVER ON THE DATA IT FITTED. From each of
several past points in time (a rolling origin, the time-series
cross-validation Hyndman describes), the model is fitted on what came
before and asked for the next
periods; its misses are compared with the NAIVE FORECAST's -- the last
value carried on, or the same period one season back. "A model that fits
the data well does not necessarily forecast well" (Hyndman, on measuring
forecast accuracy). A forecast that misses
by as much as the naive one is not drawn: it says so instead.

THE PERIOD STILL RUNNING IS LEFT OUT: this week's count on a Wednesday is
half a week's, and fitted as a whole one it would read as a fall.

THE BAND is the 80% prediction interval: wide enough to be honest,
narrow enough to read; a judgement, and stated on the chart. A count's
band never goes below zero.
"""

import datetime
import hashlib
import json
import math
import warnings
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from core.periods import next_period

#: Fewer finished periods than this and nothing is forecast.
MIN_PERIODS = 12
#: How far ahead, per period -- two weeks of days, two months of weeks,
#: half a year of months -- and never more than a third of the history.
HORIZON = {"day": 14, "week": 8, "month": 6}
#: A season, and the history it needs: two full seasons.
SEASON = {"day": 7, "week": 52, "month": 12}
#: Past points in time the forecast is tested from.
ORIGINS = 4
#: The band: an 80% prediction interval.
BAND = 0.8
#: Forecasts kept in memory, by the series they were made from.
CACHE_SIZE = 256


@dataclass(frozen=True)
class Forecast:
    """A forecast, or why there is none."""
    points: list          # [{start, value, low, high}] for the periods ahead
    season: "int | None"  # periods per season, None for none
    backtest: dict        # {origins, horizon, typical_miss, naive_miss, share}
    refusal: "str | None" = None

    def as_dict(self) -> dict:
        return {"points": self.points, "season": self.season, "backtest": self.backtest,
                "refusal": self.refusal}


#: The forms tried: (trend, damped). Additive throughout -- a count can
#: be zero, and a multiplicative form cannot take one.
FORMS = ((None, False), ("add", True), ("add", False))


@dataclass(frozen=True)
class Form:
    trend: "str | None"
    damped: bool
    season: "int | None"

    def describe(self) -> str:
        """In words, for the chart: what shape the history was read as."""
        if self.trend is None:
            shape = "a steady level"
        else:
            shape = "a fading trend" if self.damped else "a trend"
        return shape + (f" with a season of {self.season}" if self.season else "")


def _fit(values: Sequence[float], form: Form):
    import pandas as pd
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel

    # A PANDAS SERIES, NEVER A BARE ARRAY: statsmodels 0.15 with pandas 3
    # fails on arrays in prediction ("'numpy.ndarray' object has no
    # attribute 'index'"), measured 18 October.
    series = pd.Series(np.asarray(values, dtype=float))
    with warnings.catch_warnings():
        # Convergence chatter, said per fit and about nothing a reader
        # can act on; the backtest is what says whether it forecasts.
        warnings.simplefilter("ignore")
        return ETSModel(series, error="add", trend=form.trend, damped_trend=form.damped,
                        seasonal="add" if form.season else None,
                        seasonal_periods=form.season).fit(disp=False)


def _choose(values: Sequence[float], season: "int | None"):
    """(form, its fit on the whole history) with the lowest AICc; a form
    that will not fit is not a candidate. The fit is kept: it is the one
    the forecast is made from, and a second would cost as much again."""
    best, best_fit, best_aicc = None, None, math.inf
    for trend, damped in FORMS:
        for seasonal in ((season, None) if season else (None,)):
            form = Form(trend, damped, seasonal)
            try:
                fitted = _fit(values, form)
                aicc = float(fitted.aicc)
            except Exception:  # noqa: BLE001 - a form that cannot fit is not chosen
                continue
            if math.isfinite(aicc) and aicc < best_aicc:
                best, best_fit, best_aicc = form, fitted, aicc
    if best is None:
        raise ValueError("no form of the model fits this history")
    return best, best_fit


def _naive(history: Sequence[float], horizon: int, season: "int | None") -> np.ndarray:
    """The last value carried on, or the same period a season back."""
    if season and len(history) >= season:
        last = list(history[-season:])
        return np.asarray([last[index % season] for index in range(horizon)], dtype=float)
    return np.full(horizon, float(history[-1]))


def _season_for(period: str, count: int) -> "int | None":
    season = SEASON[period]
    # TWO FULL SEASONS IN EVERY TEST, not only in the whole history: the
    # earliest origin must still see two.
    return season if count - ORIGINS * HORIZON[period] >= 2 * season else None


def forecast(values: Sequence[float], starts: Sequence[datetime.date], period: str,
             count: bool) -> Forecast:
    """The next periods after `starts[-1]`, tested from ORIGINS past points.
    `values` are FINISHED periods only, oldest first, gaps already zero.
    `count`: the totals are counts, so neither the line nor the band goes
    below zero."""
    n = len(values)
    horizon = min(HORIZON[period], n // 3)
    if n < MIN_PERIODS:
        return Forecast([], None, {}, refusal=(
            f"Only {n} finished {period}s of records; a forecast needs at least {MIN_PERIODS}."))
    season = _season_for(period, n)
    try:
        form, fitted = _choose(values, season)
    except ValueError:
        return Forecast([], season, {}, refusal="The forecast could not be fitted to this "
                        "history.")
    misses, naive_misses = [], []
    for k in range(ORIGINS, 0, -1):
        origin = n - k * horizon
        if origin < MIN_PERIODS - horizon:
            continue
        train, actual = values[:origin], np.asarray(values[origin:origin + horizon], dtype=float)
        try:
            guess = np.asarray(_fit(train, form).forecast(len(actual)), dtype=float)
        except Exception:  # noqa: BLE001 - a fit that fails is a test it failed
            return Forecast([], season, {}, refusal="The forecast could not be fitted to this "
                            "history.")
        if count:
            guess = np.clip(guess, 0, None)
        misses.append(np.abs(guess - actual))
        naive_misses.append(np.abs(_naive(train, len(actual), form.season) - actual))
    if not misses:
        return Forecast([], season, {}, refusal=f"Too little history to test a forecast "
                        f"{horizon} {period}s ahead.")
    typical = float(np.mean(np.concatenate(misses)))
    naive = float(np.mean(np.concatenate(naive_misses)))
    level = float(np.mean(np.abs(values)))
    backtest = {"form": form.describe(), "origins": len(misses), "horizon": horizon,
                "typical_miss": round(typical, 4),
                "naive_miss": round(naive, 4),
                "share": round(typical / level, 4) if level > 0 else None}
    # NOT DRAWN when it misses by as much as the naive forecast -- except
    # when neither misses at all: a perfectly steady series is forecast
    # exactly by both, and is no less worth drawing for that.
    # Within a rounding error, which a fit of a steady series leaves.
    tolerance = 1e-9 * max(1.0, level)
    if typical >= naive - tolerance and naive > tolerance:
        return Forecast([], form.season, backtest, refusal=(
            f"Tested from {len(misses)} past points, it missed by as much as simply carrying "
            f"the last {period} on" + (" (the same period a season back)" if form.season else "")
            + ", so it is not drawn."))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            frame = fitted.get_prediction(start=n, end=n + horizon - 1).summary_frame(
                alpha=1 - BAND)
    except Exception:  # noqa: BLE001
        return Forecast([], form.season, backtest, refusal="The forecast could not be "
                        "fitted to this history.")
    points, start = [], starts[-1]
    for mean, low, high in zip(frame["mean"], frame["pi_lower"], frame["pi_upper"], strict=True):
        start = next_period(start, period)
        if count:
            mean, low, high = max(mean, 0.0), max(low, 0.0), max(high, 0.0)
        points.append({"start": start.isoformat(), "value": _round(mean), "low": _round(low),
                       "high": _round(high)})
    return Forecast(points, form.season, backtest)


@dataclass(frozen=True)
class Series:
    """A total per period ready to forecast: the FINISHED periods, oldest
    first, and the one still running, if any, apart."""
    starts: list
    values: list
    running: "tuple[datetime.date, float] | None"


def finished_series(totals: dict, period: str, today: datetime.date) -> Series:
    """{period start: total} -- gaps already zero (core/periods) -- as the
    finished periods, CARRIED ON TO TODAY with zeros: a count whose last
    record was three weeks ago has had three weeks of none, and a series
    that stopped at the last record would forecast from before them. The
    period containing `today` is set apart: it is not over."""
    from core.periods import period_start, periods_between

    if not totals:
        return Series([], [], None)
    current = period_start(today, period)
    assert current is not None
    starts = sorted(totals)
    if starts[0] > current:
        return Series([], [], None)
    # ONLY WHAT HAS HAPPENED: a record dated after today -- a booking, a
    # due date -- is not history, and is not fitted.
    every = periods_between(starts[0], current, period)[:-1]
    running = (current, float(totals.get(current, 0)))
    return Series(every, [float(totals.get(start, 0)) for start in every], running)


def _round(value: float) -> float:
    return float(round(value, 4)) if math.isfinite(value) else 0.0


_CACHE: "OrderedDict[str, Forecast]" = OrderedDict()


def cached_forecast(values: Sequence[float], starts: Sequence[datetime.date], period: str,
                    count: bool) -> Forecast:
    """forecast(), remembered by the exact series: the same totals give the
    same forecast, and a chart is redrawn far more often than its data
    changes. Bounded; the least recently asked is forgotten first."""
    key = hashlib.sha256(json.dumps([list(map(float, values)), [s.isoformat() for s in starts],
                                     period, count]).encode()).hexdigest()
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    made = forecast(values, starts, period, count)
    _CACHE[key] = made
    while len(_CACHE) > CACHE_SIZE:
        _CACHE.popitem(last=False)
    return made
