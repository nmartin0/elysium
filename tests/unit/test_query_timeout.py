"""
One query may not run forever.

THERE IS ONE WORKER PROCESS, so a hung query does not slow the service
down -- it stops it. A few of them and nothing is served at all.

SQLITE ON LOCAL DISK RARELY HANGS, which is why this looks like
over-engineering until the first network adapter. It is built now so
that the mechanism has been SEEN TO FIRE before a PostgreSQL adapter
depends on it; a timeout added alongside that adapter would be a
timeout nobody had ever watched work.

THE MECHANISM IS SQLITE'S OWN. `set_progress_handler` runs a callback
every N virtual-machine instructions, and returning non-zero aborts
the statement with OperationalError("interrupted").
"""

import sqlite3
import time

import pytest

from core.sqlite_connection import DEFAULT_QUERY_TIMEOUT_SECONDS, open_connection


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (a INTEGER)")
    conn.execute("CREATE TABLE dest (a INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(400)])
    conn.commit()
    conn.close()
    return path


RUNAWAY = "SELECT count(*) FROM t a, t b, t c"


class TestARunawayQueryStops:
    def test_it_aborts_rather_than_running_on(self, db):
        conn = open_connection(db, timeout_seconds=0.2)

        with pytest.raises(sqlite3.OperationalError, match="interrupted"):
            conn.execute(RUNAWAY).fetchone()

    def test_it_stops_near_the_deadline(self, db):
        """NOT MERELY EVENTUALLY. A handler checked too rarely would
        pass the test above while letting a query run for minutes."""
        conn = open_connection(db, timeout_seconds=0.2)
        started = time.monotonic()

        with pytest.raises(sqlite3.OperationalError):
            conn.execute(RUNAWAY).fetchone()

        assert time.monotonic() - started < 2.0


class TestOrdinaryQueriesAreUnaffected:
    def test_a_normal_read_completes(self, db):
        conn = open_connection(db, timeout_seconds=0.2)

        assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 400

    def test_the_default_does_not_interfere(self, db):
        # THE CONTROL THAT MATTERS. A deadline that fired on ordinary
        # work would be worse than none.
        conn = open_connection(db)

        assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 400


class TestAnAbortedWriteLeavesNothing:
    def test_a_timed_out_insert_rolls_back(self, db):
        """SQLITE ABORTS CLEANLY -- verified rather than assumed,
        because a half-applied write would be far worse than a slow
        one."""
        conn = open_connection(db, timeout_seconds=0.15)

        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO dest SELECT a.a FROM t a, t b, t c")
            conn.commit()

        check = sqlite3.connect(db)
        assert check.execute("SELECT count(*) FROM dest").fetchone()[0] == 0


class TestTheDefaultIsSane:
    def test_it_is_far_above_any_real_query(self):
        # The scan ceiling bounds the largest read at about 50ms,
        # measured. This is a backstop against never-finishing, not a
        # performance target.
        assert DEFAULT_QUERY_TIMEOUT_SECONDS >= 10

    def test_and_far_below_a_person_s_patience(self):
        assert DEFAULT_QUERY_TIMEOUT_SECONDS <= 60


class TestASiloMayChooseItsOwn:
    def test_an_explicit_timeout_is_honoured(self, db):
        conn = open_connection(db, timeout_seconds=0.05)

        with pytest.raises(sqlite3.OperationalError):
            conn.execute(RUNAWAY).fetchone()

    def test_zero_means_no_deadline(self, db):
        """A SILO THAT GENUINELY WANTS NO LIMIT can say so, and the
        alternative -- treating 0 as "abort immediately" -- would make
        a plausible config value break every query."""
        conn = open_connection(db, timeout_seconds=0)

        # A QUERY BIG ENOUGH TO REACH THE PROGRESS HANDLER. A first
        # version counted 400 rows, which finishes in fewer than
        # _PROGRESS_STEPS instructions -- so the handler was never
        # called and a control treating 0 as "abort immediately"
        # passed the test unchanged.
        assert conn.execute(
            "SELECT count(*) FROM t a, t b",
        ).fetchone()[0] == 160_000
