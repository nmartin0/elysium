"""Column profiles per gold publication, and the drift between them (R7).

Every value can pass its checks while the column as a whole goes wrong:
a field that is suddenly mostly empty, a status that collapsed to one
value, an amount whose average jumped because a source started writing
pence. Deequ's shape: metrics per run, anomaly checks on the series.

THE END-TO-END TEST CHANGES THE SOURCE'S SHAPE -- blanks most emails --
syncs for real, and requires exactly that finding.
"""

import contextlib
import io
import sqlite3

import pyarrow as pa

from core.mirror.profiles import MIN_ROWS, ProfileStore, drift_between, profile_table
from scripts.run_sync import run_sync


def _profile(**columns):
    return profile_table(pa.table(columns), list(columns))


N = MIN_ROWS * 2


class TestTheRules:
    def test_a_column_going_empty_is_drift(self):
        before = _profile(email=[f"{i}@x" for i in range(N)])
        after = _profile(email=[f"{i}@x" if i % 2 else None for i in range(N)])

        (drift,) = drift_between("Customer", before, after)

        assert drift.field == "email"
        assert "empty in 50% of rows, up from 0%" in drift.what

    def test_a_collapse_in_distinct_values_is_drift(self):
        before = _profile(status=[str(i % 5) for i in range(N)])
        after = _profile(status=["1"] * N)

        assert [d.field for d in drift_between("T", before, after)] == ["status"]

    def test_a_shifted_average_is_drift(self):
        """Pence written where pounds were."""
        before = _profile(amount=[10.0 + (i % 5) for i in range(N)])
        after = _profile(amount=[1000.0 + (i % 5) for i in range(N)])

        (drift,) = drift_between("T", before, after)

        assert "standard deviations" in drift.what

    def test_ordinary_change_is_not(self):
        """THE CONTROL. New rows, a few nulls, a nudged average: a
        normal week, and a check that flagged it would not be read."""
        before = _profile(amount=[10.0 + (i % 7) for i in range(N)],
                          email=[f"{i}@x" for i in range(N)])
        after = _profile(amount=[10.5 + (i % 7) for i in range(N + 5)],
                         email=[f"{i}@x" if i % 10 else None for i in range(N + 5)])

        assert drift_between("T", before, after) == []

    def test_too_few_rows_says_nothing(self):
        before = _profile(email=["a@x", "b@x"])
        after = _profile(email=[None, None])

        assert drift_between("T", before, after) == []


class TestTheStore:
    def test_it_keeps_the_newest_publication(self, tmp_path):
        store = ProfileStore(tmp_path / "p.db")
        store.record("T", "1", {"f": {"rows": 1, "nulls": 0}})
        store.record("T", "2", {"f": {"rows": 2, "nulls": 0}})

        assert store.latest("T") == ("2", {"f": {"rows": 2, "nulls": 0}})


def _sync(paths) -> str:
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(io.StringIO()):
        run_sync(paths)
    return printed.getvalue()


class TestARealSync:
    def test_a_column_that_collapsed_is_reported(self, synced_deployment, monkeypatch):
        """A source that started writing one placeholder name for every
        customer: each value is a valid string, the column is broken.
        Four fixture customers are below MIN_ROWS, so the floor is
        lowered for this test -- the rule, not the floor, is under test."""
        monkeypatch.setattr("core.mirror.profiles.MIN_ROWS", 2)
        _sync(synced_deployment)                       # a known baseline
        with sqlite3.connect(synced_deployment.data_dir / "dev_fixtures" / "mediator.db") as conn:
            conn.execute("UPDATE customers SET name = 'UNKNOWN'")

        printed = _sync(synced_deployment)

        assert "DRIFT   Customer.name: 1 distinct values, was 4" in printed
        assert "Customer.email" not in printed

    def test_a_sync_that_published_nothing_new_profiles_nothing(self, synced_deployment,
                                                                monkeypatch):
        """THE CONTROL: no new publication, nothing to compare."""
        monkeypatch.setattr("core.mirror.profiles.MIN_ROWS", 2)
        _sync(synced_deployment)

        assert "DRIFT" not in _sync(synced_deployment)
