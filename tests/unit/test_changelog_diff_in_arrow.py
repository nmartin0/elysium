"""
diff_snapshot_tables gives diff_snapshots' answer, without the dicts (R5).

The changelog diff is the one step that compares two WHOLE snapshots,
and it ran on every re-sync of a live table. diff_snapshots builds a
dict per row of both; on 200,000 rows with one row changed the re-sync
peaked at 880 MB. diff_snapshot_tables compares Arrow columns and
builds dicts only for the rows that changed: 510-590 MB across runs.

A REWRITE OF SOMETHING THAT WRITES HISTORY must not differ from it in
any case, because a changelog cannot be un-written. So this does not
pick cases; it generates them -- repeated ids, nulls, ints beside
strings of the same digits, added and dropped columns, mass deletions
on both sides of the guard -- and demands the identical ChangeSet.
"""

import random

import pyarrow as pa
import pytest

from core.mirror.changelog import (
    MAX_DELETED_FRACTION,
    diff_snapshot_tables,
    diff_snapshots,
)

VALUES = [None, "a", "b", "1", "", "x y"]


def _snapshot(rng, ids, columns):
    rows = []
    for _ in range(rng.randint(0, 12)):
        row = {"id": rng.choice(ids)}
        for column in columns:
            row[column] = rng.choice(VALUES)
        rows.append(row)
    return rows


def _table(rows, columns):
    names = ["id", *columns]
    return pa.table({name: pa.array([row[name] for row in rows], pa.string()) for name in names})


@pytest.mark.parametrize("accept_deletions", [False, True])
@pytest.mark.parametrize("before_images", [False, True])
def test_randomised_snapshots_give_the_same_changes(accept_deletions, before_images):
    rng = random.Random(f"{accept_deletions}{before_images}")
    for trial in range(400):
        ids = [f"k{i}" for i in range(rng.randint(1, 8))] + [None]
        old_columns = rng.choice([["a"], ["a", "b"]])
        # One trial in five adds or drops a column between the syncs.
        new_columns = old_columns if rng.random() > 0.2 else rng.choice([["a"], ["a", "b"], ["b"]])
        previous, current = _snapshot(rng, ids, old_columns), _snapshot(rng, ids, new_columns)

        expected = diff_snapshots(previous, current, "id", accept_deletions=accept_deletions,
                                  before_images=before_images)
        actual = diff_snapshot_tables(_table(previous, old_columns), _table(current, new_columns),
                                      "id", accept_deletions=accept_deletions,
                                      before_images=before_images)

        assert actual == expected, f"trial {trial}: {previous} -> {current}"


def test_an_integer_id_pairs_with_its_string():
    """Bronze is all strings and silver is typed; pairing is by str(id)
    in both functions."""
    previous = [{"id": 1, "a": "x"}, {"id": 2, "a": "y"}]
    current = [{"id": 1, "a": "x"}, {"id": 2, "a": "z"}]
    as_table = lambda rows: pa.table({"id": [r["id"] for r in rows], "a": [r["a"] for r in rows]})  # noqa: E731

    assert diff_snapshot_tables(as_table(previous), as_table(current), "id") == \
        diff_snapshots(previous, current, "id")


def test_a_mass_deletion_is_held_back_the_same_way():
    previous = [{"id": f"k{i}", "a": "x"} for i in range(10)]
    current = previous[: int(10 * (1 - MAX_DELETED_FRACTION)) - 1]
    result = diff_snapshot_tables(_table(previous, ["a"]), _table(current, ["a"]), "id")

    assert result.suspected_partial_read and result.rows == []
    assert result == diff_snapshots(previous, current, "id")


def test_one_change_in_many_builds_one_change():
    previous = [{"id": f"k{i}", "a": "x"} for i in range(5_000)]
    current = [dict(row) for row in previous]
    current[2_500]["a"] = "y"

    result = diff_snapshot_tables(_table(previous, ["a"]), _table(current, ["a"]), "id")

    assert [row["id"] for row in result.rows] == ["k2500"]
