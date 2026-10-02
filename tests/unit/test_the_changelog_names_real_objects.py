"""
Every changelog entry names an object the table held (the backlog (consumed)
section 0c, item 1).

the backlog (consumed) left this explicitly unchecked, and said why:

    "whether every changelog entry names an object that existed. The
    changelog is append-only history whose row count deliberately
    matches nothing, so it needs its own reasoning rather than an
    extension of these rules."

THE REASONING. An id in the changelog is accounted for if silver still
holds it, OR if the changelog itself records a DELETE for it. Anything
else is history describing an object that is not there and was never
recorded as leaving: either the changelog gained an entry for
something that never existed, or a row vanished from silver without
its deletion being written.

A ROW COUNT PROVES NOTHING HERE. The changelog grows forever while
silver holds only current rows, so the two are SUPPOSED to disagree --
which is exactly why the bronze-versus-silver comparison could not be
extended to cover it.

WHY IT MATTERS FOR A TEARDOWN, which is the section this comes from:
bronze and silver can be rebuilt from source and the changelog cannot.
It is the one layer where a silent inconsistency is permanent.
"""

import pyarrow as pa
import pytest

from core.mirror.integrity import (
    _changelog_id_column,
    _check_changelog_names_real_objects,
)


class _Report:
    def __init__(self):
        self.problems = []

    def note(self, message):
        self.problems.append(message)


class _Catalog:
    """A catalog standing in for the real one, holding fixed rows."""

    def __init__(self, tables):
        self._tables = tables

    def load_table(self, identifier):
        if identifier not in self._tables:
            raise KeyError(identifier)
        rows = self._tables[identifier]

        class _Table:
            def scan(self_inner):
                return self_inner

            def to_arrow(self_inner):
                return pa.Table.from_pylist(rows) if rows else pa.table({})

        return _Table()


def _check(tables):
    report = _Report()
    _check_changelog_names_real_objects(_Catalog(tables), {"p.t"}, report)
    return report.problems


class TestWhatIsAccountedFor:
    def test_an_id_silver_still_holds(self):
        problems = _check({
            "p.t": [{"thing_id": "a", "name": "Ada"}],
            "changelog_p.t": [{"thing_id": "a", "_change": "INSERT"}],
        })

        assert problems == []

    def test_an_id_the_changelog_records_as_deleted(self):
        """Gone from silver, and the history SAYS it is gone. That is
        the changelog working, not a fault."""
        problems = _check({
            "p.t": [],
            "changelog_p.t": [{"thing_id": "a", "_change": "INSERT"},
                               {"thing_id": "a", "_change": "DELETE"}],
        })

        assert problems == []

    def test_a_deployment_with_no_changelog_yet(self):
        """One sync produces silver and no history. Not a fault."""
        assert _check({"p.t": [{"thing_id": "a"}]}) == []

    def test_an_empty_changelog(self):
        assert _check({"p.t": [{"thing_id": "a"}], "changelog_p.t": []}) == []


class TestWhatIsReported:
    def test_an_id_that_is_gone_with_no_deletion_recorded(self):
        """THE CASE THIS EXISTS FOR. History describes an object that
        is not there and was never recorded as leaving."""
        problems = _check({
            "p.t": [{"thing_id": "a"}],
            "changelog_p.t": [{"thing_id": "a", "_change": "INSERT"},
                               {"thing_id": "ghost", "_change": "UPDATE"}],
        })

        assert len(problems) == 1
        assert "ghost" in problems[0]

    def test_the_message_names_both_tables(self):
        """An operator has to know which history and which table."""
        problems = _check({
            "p.t": [{"thing_id": "a"}],
            "changelog_p.t": [{"thing_id": "ghost", "_change": "UPDATE"}],
        })

        assert "changelog_p.t" in problems[0]
        assert "p.t" in problems[0]

    def test_it_counts_them_and_shows_only_a_few(self):
        """A changelog can be enormous. The count is the finding; the
        examples are for recognising it."""
        problems = _check({
            "p.t": [],
            "changelog_p.t": [{"thing_id": f"g{n}", "_change": "UPDATE"}
                               for n in range(40)],
        })

        assert "40 id(s)" in problems[0]
        assert problems[0].count("'g") == 5

    def test_a_changelog_with_no_id_column(self):
        """Entries that cannot be matched to any object are their own
        problem, and silence would hide it."""
        problems = _check({
            "p.t": [{"thing_id": "a"}],
            "changelog_p.t": [{"name": "Ada", "_change": "INSERT"}],
        })

        assert "no id column" in problems[0]


class TestFindingTheIdColumn:
    @pytest.mark.parametrize("entry,expected", [
        ({"id": "a", "_change": "INSERT"}, "id"),
        ({"thing_id": "a", "_change": "INSERT"}, "thing_id"),
        ({"name": "Ada", "customer_id": "c1"}, "customer_id"),
    ])
    def test_it_names_the_id(self, entry, expected):
        assert _changelog_id_column(entry) == expected

    def test_system_columns_are_skipped(self):
        """`_change` and the lineage columns all begin with an
        underscore, and none of them identifies the object."""
        assert _changelog_id_column({"_id": "x", "thing_id": "a"}) == "thing_id"

    def test_none_when_there_is_no_candidate(self):
        assert _changelog_id_column({"name": "Ada", "_change": "INSERT"}) is None
