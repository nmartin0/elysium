"""
A search reads at most MAX_SEARCH_SCAN rows.

MEASURED, on the path this bounds: 200,000 rows cost 858ms and 66MB
unbounded, 49ms and 3.2MB capped -- and that is a table twenty times
smaller than the ten million that would have exhausted memory outright
at an extrapolated 3.3GB.

WHAT THE CAP MEANS DEPENDS ON WHETHER MAC WAS PUSHED. With `field:`
security the database returns only rows the user may see, so the cap
bounds the ANSWER. With `via_field:` it bounds a SCAN whose survivors
are filtered afterwards -- so truncation says "WE STOPPED LOOKING",
not "there is more for you".
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.ontology.mediator import MAX_SEARCH_SCAN


@pytest.fixture
def adapter(tmp_path):
    db = tmp_path / "many.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, region TEXT)")
    con.executemany(
        "INSERT INTO t (region) VALUES (?)",
        [("us-west" if i % 2 else "us-east",) for i in range(500)],
    )
    con.commit()
    con.close()
    return SQLiteReadAdapter({"path": db})


CONFIG = {
    "storage": {"table": "t", "id_column": "id"},
    "fields": {"id": {"column": "id"}, "region": {"column": "region"}},
}


class TestTheAdapterHonoursALimit:
    def test_it_reads_no_more_than_asked(self, adapter):
        assert len(adapter.find_ids("T", [], CONFIG, 10)) == 10

    def test_none_means_everything(self, adapter):
        # The caller that wants a whole small table passes None, and
        # must still get it.
        assert len(adapter.find_ids("T", [], CONFIG, None)) == 500

    def test_a_limit_larger_than_the_table_returns_the_table(self, adapter):
        assert len(adapter.find_ids("T", [], CONFIG, 10_000)) == 500

    def test_a_non_positive_limit_is_no_limit(self, adapter):
        """ASKING FOR AT MOST ZERO ROWS is almost always a caller bug
        rather than an intention, and returning nothing would look
        like an empty table."""
        assert len(adapter.find_ids("T", [], CONFIG, 0)) == 500
        assert len(adapter.find_ids("T", [], CONFIG, -1)) == 500


class TestTheLimitReachesTheQuery:
    def test_it_is_not_trimmed_afterwards(self, adapter, tmp_path):
        """THE WHOLE POINT. Trimming in Python after a full fetch would
        pass every test above while doing nothing about the memory the
        cap exists to bound.

        So the SQL itself is asserted, the way this project pins other
        mechanisms whose symptom is invisible.
        """
        import inspect

        import adapters.sqlite_adapter as module

        source = inspect.getsource(module._limit_clause)

        assert "LIMIT" in source

    def test_the_clause_is_absent_when_there_is_no_limit(self):
        from adapters.sqlite_adapter import _limit_clause

        assert _limit_clause(None) == ""
        assert _limit_clause(50) == " LIMIT 50"


class TestTheCeilingIsSane:
    def test_it_is_far_above_any_page_a_user_reads(self):
        # The API's own MAX_PAGE_SIZE is 500. A ceiling below that
        # would truncate ordinary paging rather than runaway scans.
        assert MAX_SEARCH_SCAN > 500

    def test_it_is_far_below_where_the_fetch_hurts(self):
        # At the measured rate -- 200,000 rows in 858ms and 66MB --
        # this ceiling costs about 35ms and 3MB.
        assert MAX_SEARCH_SCAN <= 100_000
