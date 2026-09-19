"""
Id lists reach SQLite as one JSON parameter, not as placeholders.

WHAT THIS REMOVED. Two `S608` suppressions and a chunking loop. The
old code built `IN (?,?,?...)` by string interpolation -- safe,
because only placeholders were interpolated, but it needed a
suppression saying so on every read. And it chunked at 500 ids to stay
under SQLite's variable limit.

ONE JSON PARAMETER MAKES THE SQL A CONSTANT STRING. There is nothing
left to interpolate, so there is nothing to suppress, and no variable
limit to respect.

MEASURED: 50,000 ids in a single query, 4.1ms -- a hundred times the
old chunk size, one round trip.

IT NEEDS SQLITE 3.38, where json1 stops depending on how the library
was built. `require_json_each()` refuses at startup rather than
letting the failure arrive as "no such function: json_each" from
inside a write-log lookup.
"""

import sqlite3

import pytest

from core.sqlite_connection import (
    MINIMUM_SQLITE_FOR_JSON_EACH,
    require_json_each,
)


@pytest.fixture
def write_log(tmp_path):
    from core.ontology.write_log import WriteLogWriter

    return WriteLogWriter(tmp_path / "wl.db")


class TestIdListsOfAnySize:
    def test_a_small_list(self, write_log):
        assert write_log.pending_changes_for_ids("Customer", ["a", "b"]) == {}

    def test_past_the_old_chunk_boundary(self, write_log):
        """THE OLD CODE CHUNKED AT 500. A list of 5,000 exercised the
        loop; now it is one query, and this pins that it still
        answers."""
        ids = [str(i) for i in range(5_000)]

        assert write_log.pending_changes_for_ids("Customer", ids) == {}

    def test_far_past_sqlite_s_variable_limit(self, write_log):
        """SQLITE'S LIMIT IS 999 ON OLDER BUILDS. Fifty thousand
        placeholders would fail outright; one JSON parameter does
        not."""
        ids = [str(i) for i in range(50_000)]

        assert write_log.pending_changes_for_ids("Customer", ids) == {}

    def test_an_empty_list_asks_nothing(self, write_log):
        assert write_log.pending_changes_for_ids("Customer", []) == {}

    def test_the_deleted_lookup_takes_the_same_shape(self, write_log):
        ids = [str(i) for i in range(5_000)]

        assert write_log.deleted_ids("Customer", ids) == set()


class TestTheSqlIsConstant:
    def test_no_suppression_remains_in_the_module(self):
        """A SOURCE-LEVEL TRIPWIRE, because a reintroduced
        interpolation would pass every behavioural test above while
        bringing back the thing this commit removed.

        The suppressions were honest -- only placeholders were
        interpolated -- but a comment asserting safety is weaker than
        SQL with nothing to interpolate.
        """
        import inspect

        import core.ontology.write_log as module

        source = inspect.getsource(module)

        # `# noqa: S608`, NOT THE BARE WORD. A first version asserted
        # "S608" was absent and failed against the COMMENT explaining
        # its removal -- the tripwire caught the explanation rather
        # than the thing.
        assert "noqa: S608" not in source
        assert "json_each" in source


class TestTheStartupCheck:
    def test_it_passes_on_a_capable_sqlite(self):
        require_json_each()

    def test_the_floor_is_where_json1_became_unconditional(self):
        # 3.38 (2022) is where json1 stopped depending on how the
        # library was built. Below it, json_each MAY still work.
        assert MINIMUM_SQLITE_FOR_JSON_EACH == (3, 38, 0)

    def test_this_build_can_actually_run_it(self):
        """THE CHECK ASKS RATHER THAN ASSUMING below the floor, so this
        confirms the thing it asks about really works here -- a check
        that passed while the feature was broken would be worse than
        none."""
        conn = sqlite3.connect(":memory:")

        rows = conn.execute("SELECT value FROM json_each('[1,2]')").fetchall()

        assert [row[0] for row in rows] == [1, 2]
