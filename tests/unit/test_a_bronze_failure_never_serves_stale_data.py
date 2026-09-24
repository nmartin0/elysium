"""
A failed bronze write must not make silver serve old data (PA001-F2).

WHAT HAPPENED. Bronze's overwrite failed -- a full disk is the obvious
case, and it is caught and merely warned about so a sync can carry on.
sync_table then read bronze back UNCONDITIONALLY. The bronze table was
still there from the PREVIOUS sync, so it answered, and silver was
rebuilt from its rows while the fresh rows already in memory were
discarded.

Measured: source said NEW, silver served 'a', the sync reported one row
and success, and the warning said "the mirror is correct".

THE COMMENT WAS THE BUG'S BEST DISGUISE. "Silver stays correct either
way; only the re-derivability is lost, and the warning says so" -- a
clear, confident statement of something untrue, sitting directly above
the line that made it untrue. It is corrected in place rather than
deleted, because the next person to read that code should see that the
question was considered and answered wrongly.

THE FIX IS ONE FACT NOBODY WAS CARRYING: a bronze table EXISTING is not
the same as THIS RUN's bronze being current, and only _write_bronze
knows which. It returns that now.

WHAT IS DELIBERATELY STILL TRUE: the sync does not fail. Bronze is an
archive and a re-derivation source; losing a write degrades lineage,
not correctness. Silver follows the source, and the warning says
bronze is behind instead of claiming everything is fine.
"""

import sqlite3

import pytest
from pyiceberg.table import Table

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync


@pytest.fixture
def mirror(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO t VALUES ('1','a')")
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "m", {"p": SQLiteReadAdapter({"path": source})})

    def run():
        return sync.sync_table("p", "t", "id", ["id", "name"], {})

    def sql(statement):
        conn = sqlite3.connect(source)
        conn.execute(statement)
        conn.commit()
        conn.close()

    def served(identifier="p.t"):
        return [r["name"] for r in
                sync.catalog.load_table(identifier).scan().to_arrow().to_pylist()]

    sync.run, sync.sql, sync.served = run, sql, served
    return sync


@pytest.fixture
def _bronze_fails(monkeypatch):
    """Fails ONLY bronze, so silver's own write path is untouched and
    the test is about which rows silver is built from."""
    real = Table.overwrite

    def failing(self, df, *args, **kwargs):
        if "bronze" in str(self.name()):
            raise OSError("disk full (injected)")
        return real(self, df, *args, **kwargs)
    monkeypatch.setattr(Table, "overwrite", failing)


class TestSilverFollowsTheSource:
    def test_silver_serves_what_the_source_says(self, mirror, _bronze_fails):
        """THE REGRESSION TEST. Source NEW, silver used to serve 'a'."""
        mirror.run()

        mirror.sql("UPDATE t SET name='NEW' WHERE id='1'")
        mirror.run()

        assert mirror.served() == ["NEW"]

    def test_a_new_row_still_arrives(self, mirror, _bronze_fails):
        mirror.run()

        mirror.sql("INSERT INTO t VALUES ('2','b')")
        mirror.run()

        assert sorted(mirror.served()) == ["a", "b"]

    def test_the_sync_still_succeeds(self, mirror, _bronze_fails):
        """Bronze is lineage, not correctness. Failing the whole sync
        because the archive copy failed would trade a real outage for a
        degraded one."""
        mirror.run()
        mirror.sql("UPDATE t SET name='NEW' WHERE id='1'")

        result = mirror.run()

        assert result.row_count == 1


class TestWhatTheOperatorIsTold:
    def test_the_warning_says_bronze_is_behind(self, mirror, _bronze_fails, caplog):
        """It used to say "the mirror is correct", which was the one
        thing it was not."""
        mirror.run()
        mirror.sql("UPDATE t SET name='NEW' WHERE id='1'")

        with caplog.at_level("WARNING"):
            mirror.run()

        assert "BEHIND" in caplog.text
        assert "the mirror is correct" not in caplog.text

    def test_bronze_really_is_behind(self, mirror, _bronze_fails):
        """The warning is accurate, which matters more than it being
        reassuring."""
        mirror.run()
        mirror.sql("UPDATE t SET name='NEW' WHERE id='1'")
        mirror.run()

        # Empty here rather than ['a'], because this fixture fails
        # bronze from the FIRST sync too -- so bronze never held
        # anything. Either way it does not hold what the source says,
        # which is the claim being tested: asserting ['a'] would have
        # pinned an artefact of the fixture instead.
        assert "NEW" not in mirror.served("bronze_p.t")


class TestRecovery:
    def test_the_next_good_sync_catches_bronze_up(self, mirror, monkeypatch):
        """A degraded run must not need a human to undo it."""
        real = Table.overwrite
        failing = {"on": True}

        def maybe_fail(self, df, *args, **kwargs):
            if failing["on"] and "bronze" in str(self.name()):
                raise OSError("disk full (injected)")
            return real(self, df, *args, **kwargs)
        monkeypatch.setattr(Table, "overwrite", maybe_fail)

        mirror.run()
        mirror.sql("UPDATE t SET name='NEW' WHERE id='1'")
        mirror.run()
        failing["on"] = False
        mirror.sql("UPDATE t SET name='NEWER' WHERE id='1'")
        mirror.run()

        assert mirror.served() == ["NEWER"]
        assert mirror.served("bronze_p.t") == ["NEWER"]


class TestTheHealthyPathIsUnchanged:
    def test_bronze_is_still_read_back_when_it_wrote(self, mirror):
        """The read-back is load-bearing: it makes a broken bronze
        break the sync loudly. The fix must not quietly stop reading
        bronze on the normal path."""
        mirror.run()
        mirror.sql("UPDATE t SET name='NEW' WHERE id='1'")
        mirror.run()

        assert mirror.served() == ["NEW"]
        assert mirror.served("bronze_p.t") == ["NEW"]

    def test_bronze_is_STILL_READ_BACK_on_the_healthy_path(self, mirror, monkeypatch):
        """WRITTEN BECAUSE A CONTROL PROVED NOTHING. Never reading
        bronze back at all still passed every test above, because
        silver is built from the in-memory rows either way.

        But the read-back is deliberate and load-bearing: it is what
        makes silver derive from the RAW RECORD rather than from
        whatever the adapter happened to return, and what makes a
        broken bronze break the sync loudly instead of quietly. A fix
        for F2 that silently stopped reading bronze would look
        identical in every other test and lose that."""
        calls = []
        real = IcebergMirrorSync._read_bronze

        def spy(self, *args, **kwargs):
            calls.append(args[:2])
            return real(self, *args, **kwargs)
        monkeypatch.setattr(IcebergMirrorSync, "_read_bronze", spy)

        mirror.run()
        mirror.sql("UPDATE t SET name='NEW' WHERE id='1'")
        mirror.run()

        assert calls, "bronze was never read back on a healthy sync"

    def test_the_first_sync_has_no_bronze_to_read(self, mirror):
        """The other case the fallback exists for."""
        result = mirror.run()

        assert result.row_count == 1
        assert mirror.served() == ["a"]
