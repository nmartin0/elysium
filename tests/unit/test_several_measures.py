"""Several measures over one read (BLOCKING.md item 3's time-series reads,
part 4): a count, a total and a mean per week are one request, one scan,
and cannot disagree about which rows they saw. After Foundry's aggregate,
which takes a list of {type, field, name} and answers each group with its
metrics by name."""

import pytest

from tests.unit.test_totals_by_duration import ROWS, _mediator, _north


def _measures(*specs):
    return [{"name": n, "aggregate": a, "field": f} for n, a, f in specs]


def _ask(tmp_path, measures, rows=ROWS, **arguments):
    arguments.setdefault("group_by", "day")
    return _mediator(tmp_path, rows).aggregate_measures(
        _north(), "Reading", [], measures=measures, **arguments)


class TestOneRequest:
    def test_each_group_answers_each_measure_by_name(self, tmp_path):
        assert _ask(tmp_path, _measures(("n", "count", None), ("total", "sum", "value"),
                                        ("mean", "avg", "value"))) == {
            "2026-07-01": {"n": 2, "total": 10.0, "mean": 5.0},
            "2026-07-02": {"n": 1, "total": 1.0, "mean": 1.0},
        }

    def test_each_is_what_it_would_be_asked_alone(self, tmp_path):
        together = _ask(tmp_path, _measures(("a", "count", None), ("b", "max", "value"),
                                            ("c", "min", "value")))
        for name, aggregate, field in (("a", "count", None), ("b", "max", "value"),
                                       ("c", "min", "value")):
            alone = _mediator(tmp_path).aggregate_by_field(
                _north(), "Reading", [], group_by="day", aggregate=aggregate, field_name=field)
            assert {group: metrics[name] for group, metrics in together.items()} == alone

    def test_the_set_is_read_once_however_many_are_asked(self, tmp_path):
        mediator = _mediator(tmp_path)
        reads = []
        original = mediator._read_fields_for_ids
        mediator._read_fields_for_ids = lambda *a, **k: (reads.append(1), original(*a, **k))[1]
        mediator.aggregate_measures(
            _north(), "Reading", [], group_by="day",
            measures=_measures(("a", "count", None), ("b", "sum", "value"), ("c", "avg", "value")))
        assert len(reads) == 1

    def test_ungrouped_it_is_one_row_under_none(self, tmp_path):
        assert _ask(tmp_path, _measures(("n", "count", None), ("total", "sum", "value")),
                    group_by=None) == {None: {"n": 3, "total": 11.0}}

    def test_counts_alone_over_the_whole_set_need_no_read(self, tmp_path):
        assert _ask(tmp_path, _measures(("n", "count", None), ("m", "count", None)),
                    group_by=None) == {None: {"n": 3, "m": 3}}


class TestAGroupWithNoValueForOneMeasure:
    NULLS = [
        ("r1", "north", "2026-07-01T09:05:00+00:00", "2026-07-01", 4.0),
        ("r2", "north", "2026-07-01T09:20:00+00:00", "2026-07-02", None),
    ]

    def test_it_is_zero_for_a_count_or_a_sum_and_none_for_the_rest(self, tmp_path):
        # 2 July has a reading but no value: it is a group because the
        # count sees it, and there is no mean of nothing.
        assert _ask(tmp_path, _measures(("n", "count", None), ("total", "sum", "value"),
                                        ("mean", "avg", "value")), rows=self.NULLS) == {
            "2026-07-01": {"n": 1, "total": 4.0, "mean": 4.0},
            "2026-07-02": {"n": 1, "total": 0, "mean": None},
        }


class TestOverTime:
    def test_the_quarter_hours_are_every_one_between_for_every_measure(self, tmp_path):
        got = _ask(tmp_path, _measures(("high", "max", "value"), ("n", "count", None)),
                   group_by="taken", duration="PT15M", time_zone="Europe/London")
        # In time order though the first measure lacks the middle one.
        assert list(got) == sorted(got)
        assert {start.isoformat(): metrics for start, metrics in got.items()} == {
            "2026-07-01T10:00:00+01:00": {"n": 1, "high": 4.0},
            "2026-07-01T10:15:00+01:00": {"n": 1, "high": 6.0},
            "2026-07-01T10:30:00+01:00": {"n": 0, "high": None},
            "2026-07-01T10:45:00+01:00": {"n": 1, "high": 1.0},
        }

    def test_a_candlestick_is_one_request(self, tmp_path):
        got = _ask(tmp_path, _measures(("open", "first", "value"), ("high", "max", "value"),
                                       ("low", "min", "value"), ("close", "last", "value")),
                   group_by="taken", duration="PT1H")
        assert [metrics for metrics in got.values()] == [
            {"open": 4.0, "high": 6.0, "low": 1.0, "close": 1.0}]


class TestWhatIsRefused:
    @pytest.mark.parametrize("measures, said", [
        ([], "at least one measure"),
        (_measures(*[(f"m{i}", "count", None) for i in range(9)]), "At most 8"),
        (_measures(("a", "count", None), ("a", "sum", "value")), "same name"),
        (_measures(("Total", "sum", "value")), "must be lower-case"),
        (_measures(("1st", "sum", "value")), "must be lower-case"),
        (_measures(("", "sum", "value")), "must be lower-case"),
        (_measures(("a", "median", "value")), "Unknown aggregate"),
        (_measures(("a", "sum", None)), "requires a field_name"),
        (_measures(("a", "count", None), ("b", "first", "value")), "needs one"),
    ])
    def test_each_says_why(self, tmp_path, measures, said):
        with pytest.raises(ValueError, match=said):
            _ask(tmp_path, measures)

    def test_eight_are_allowed(self, tmp_path):
        got = _ask(tmp_path, _measures(*[(f"m{i}", "count", None) for i in range(8)]))
        assert len(next(iter(got.values()))) == 8
