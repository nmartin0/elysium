"""
Something reads `gold_history`.

IT WAS WRITTEN FOR MONTHS AND READ BY NOTHING. Every gold publication
compares the previous rows to the new ones and appends one row per
change; `NEW-7` recorded that no consumer existed. That made it the
sixth thing in this codebase built, tested, and wired to nowhere --
after a retention property nothing acted on, an adapter nothing
constructed, an atomic method the route ignored, a repair tool the
failure never mentioned, and a manifest nothing opened.

The owner has now said the feature is wanted, so the writer stops
being a cost with no benefit.

WHAT IT ANSWERS: "when did this customer's region change, and what was
it before". The writer stores the whole row JSON-encoded in ONE column
rather than one column per property, deliberately -- "an object type's
properties change over time and a history table that changes shape
with them cannot answer questions about the past in the past's terms"
-- so the reader decodes it rather than making every caller do so.

NO ACCESS CONTROL HERE, and that is deliberate: this reads the lake
directly like the rest of `core/mirror`. Anything exposing it to a
user must filter per caller itself.
"""

import json

import pytest

from core.mirror.gold_history import (
    CHANGE_COLUMN,
    CHANGED_AT_COLUMN,
    SNAPSHOT_COLUMN,
    HistoryNotRecorded,
    read_history,
)


class _Table:
    def __init__(self, rows):
        self._rows = rows

    def scan(self):
        return self

    def to_arrow(self):
        return self

    def to_pylist(self):
        return self._rows


class _Catalog:
    def __init__(self, rows=None, missing=False):
        self._rows = rows or []
        self._missing = missing

    def load_table(self, identifier):
        if self._missing:
            from pyiceberg.exceptions import NoSuchTableError

            raise NoSuchTableError(identifier)
        return _Table(self._rows)


def _row(object_id, change, at, values=None, publication="s1"):
    return {
        "customer_id": object_id,
        CHANGE_COLUMN: change,
        CHANGED_AT_COLUMN: at,
        SNAPSHOT_COLUMN: publication,
        "values": json.dumps(values or {"customer_id": object_id}),
    }


class TestWhatItReturns:
    def test_a_change_comes_back_decoded(self):
        """The caller wants the row, not the JSON string the writer
        chose to store it as."""
        catalog = _Catalog([_row("c1", "UPDATE", "2026-09-01T00:00:00Z",
                                  {"region": "us-east"})])

        entries = read_history(catalog, "Customer", "customer_id")

        assert len(entries) == 1
        assert entries[0]["values"] == {"region": "us-east"}
        assert entries[0]["change"] == "UPDATE"
        assert entries[0]["object_id"] == "c1"

    def test_newest_first(self):
        """The question is almost always 'what changed recently', and
        the table only grows."""
        catalog = _Catalog([
            _row("c1", "INSERT", "2026-09-01T00:00:00Z"),
            _row("c1", "UPDATE", "2026-09-03T00:00:00Z"),
            _row("c1", "UPDATE", "2026-09-02T00:00:00Z"),
        ])

        entries = read_history(catalog, "Customer", "customer_id")

        assert [e["changed_at"] for e in entries] == [
            "2026-09-03T00:00:00Z",
            "2026-09-02T00:00:00Z",
            "2026-09-01T00:00:00Z",
        ]

    def test_the_publication_is_carried(self):
        """Which publication made the change is how a reader ties it
        back to a sync."""
        catalog = _Catalog([_row("c1", "DELETE", "2026-09-01T00:00:00Z",
                                  publication="snap-7")])

        assert read_history(catalog, "Customer", "customer_id")[0][
            "publication"] == "snap-7"


class TestNarrowingIt:
    def test_by_object_id(self):
        catalog = _Catalog([_row("c1", "UPDATE", "2026-09-01T00:00:00Z"),
                            _row("c2", "UPDATE", "2026-09-02T00:00:00Z")])

        entries = read_history(catalog, "Customer", "customer_id",
                               object_id="c2")

        assert [e["object_id"] for e in entries] == ["c2"]

    def test_by_date(self):
        catalog = _Catalog([_row("c1", "UPDATE", "2026-08-01T00:00:00Z"),
                            _row("c1", "UPDATE", "2026-09-05T00:00:00Z")])

        entries = read_history(catalog, "Customer", "customer_id",
                               since="2026-09-01")

        assert len(entries) == 1
        assert entries[0]["changed_at"].startswith("2026-09-05")

    @pytest.mark.parametrize("limit", [1, 2, 5])
    def test_the_limit_is_applied_after_sorting(self, limit):
        """A limit that cut before sorting would return an arbitrary
        subset rather than the most recent ones."""
        catalog = _Catalog([_row("c1", "UPDATE", f"2026-09-0{n}T00:00:00Z")
                            for n in range(1, 6)])

        entries = read_history(catalog, "Customer", "customer_id",
                               limit=limit)

        assert len(entries) == min(limit, 5)
        assert entries[0]["changed_at"].startswith("2026-09-05")


class TestWhatIsNotAnError:
    def test_a_type_with_no_history_table_RAISES(self):
        """ABSENT IS NOT EMPTY. The first version returned [] for both,
        and the command above it then asserted "a type published only
        once has no history yet" -- which it could not know.

        Run on a real deployment it printed exactly that, and the
        output could not distinguish a writer that had never recorded
        from a reader dropping every row. Same collapse S3 avoids with
        NoSuchBucket against NoSuchKey."""
        with pytest.raises(HistoryNotRecorded):
            read_history(_Catalog(missing=True), "Customer", "customer_id")

    def test_an_empty_table_is_not_the_same_answer(self):
        """A table that exists and holds nothing is stranger than no
        table: the writer creates it on the first CHANGE, so it has no
        path to produce an empty one."""
        assert read_history(_Catalog([]), "Customer", "customer_id") == []

    def test_absence_is_ordinary_not_a_fault(self):
        """MEASURED: two syncs of the dev deployment with no data
        change leave no table at all, because record_publication
        returns before creating one when the diff is empty."""
        import inspect

        from core.mirror.gold_history import HistoryNotRecorded as absent

        assert "not a fault" in inspect.getdoc(absent).lower()

    def test_a_row_whose_values_will_not_decode(self):
        """It is still a row that changed. Saying so beats dropping it
        silently, which is the behaviour this whole table exists to
        avoid."""
        catalog = _Catalog([{
            "customer_id": "c1", CHANGE_COLUMN: "UPDATE",
            CHANGED_AT_COLUMN: "2026-09-01T00:00:00Z",
            SNAPSHOT_COLUMN: "s1", "values": "{not json",
        }])

        entries = read_history(catalog, "Customer", "customer_id")

        assert len(entries) == 1
        assert entries[0]["values"]["_undecodable"] == "{not json"
