"""
What each sync attempt did, including the ones that failed.

WHY THIS EXISTS. The mirror's timestamps come from Iceberg snapshots,
which record when data last CHANGED -- the right thing for them to
record, and it leaves two states indistinguishable from outside:

    a sync that ran and found nothing to do
    a sync that ran and was REFUSED

Both leave the previous snapshot in place. A table whose syncs have
been failing since Tuesday looks exactly like one whose source has not
changed since Tuesday, and the first is an incident while the second
is Tuesday.

SEEN ON A REAL DEPLOYMENT, which is what prompted this: the mirror
panel showed a table last changed two days ago while its sync had been
refusing for two days, and nothing on the screen could tell them
apart.
"""

import time

import pytest

from core.mirror.sync_attempts import SyncAttempts


@pytest.fixture
def attempts(tmp_path):
    return SyncAttempts(tmp_path / "sync_attempts.db")


class TestRecording:
    def test_an_attempt_survives_the_connection_closing(self, attempts):
        """THE BUG A REAL SYNC EXPOSED. open_connection sets
        isolation_level='', so an implicit transaction opens on the
        first write and is ROLLED BACK on close unless committed.

        A first version left the commit out. The table existed, the
        insert reported success, and a fresh connection saw nothing --
        which looked like the recorder was never called.
        """
        attempts.record("s", "t", "synced")

        assert attempts.last_for("s", "t") is not None

    def test_a_refusal_keeps_its_reason(self, attempts):
        # A reader who sees a refusal wants the column and the value,
        # not a category.
        attempts.record("s", "t", "refused", "column 'when' contains 'banana'")

        assert "banana" in attempts.last_for("s", "t").detail

    def test_the_most_recent_attempt_wins(self, attempts):
        attempts.record("s", "t", "refused", "old")
        time.sleep(0.01)
        attempts.record("s", "t", "synced")

        assert attempts.last_for("s", "t").outcome == "synced"

    def test_tables_are_recorded_separately(self, attempts):
        attempts.record("s", "one", "synced")
        attempts.record("s", "two", "refused", "bad")

        assert attempts.last_for("s", "one").outcome == "synced"
        assert attempts.last_for("s", "two").outcome == "refused"

    def test_an_unrecorded_table_reports_nothing(self, attempts):
        # NOT A FAILURE. An existing deployment has no attempts until
        # its next sync, and inventing one would be worse than silence.
        assert attempts.last_for("s", "never-seen") is None


class TestItNeverBreaksASync:
    def test_recording_into_an_impossible_path_is_silent(self, tmp_path):
        """A SYNC WHOSE DATA WORK SUCCEEDED MUST NOT FAIL BECAUSE ITS
        BOOKKEEPING DID. That would turn a working mirror into a broken
        one for the sake of a log."""
        broken = SyncAttempts(tmp_path / "no" / "such" / "dir" / "a.db")

        broken.record("s", "t", "synced")

    def test_reading_from_an_impossible_path_reports_nothing(self, tmp_path):
        broken = SyncAttempts(tmp_path / "no" / "such" / "dir" / "a.db")

        assert broken.last_for("s", "t") is None


class TestRetention:
    def test_old_attempts_are_dropped(self, attempts):
        attempts.record("s", "t", "synced")

        assert attempts.forget_older_than(days=-1) == 1
        assert attempts.last_for("s", "t") is None

    def test_recent_attempts_are_kept(self, attempts):
        # THE CONTROL on the sweep. One that dropped everything would
        # leave the panel permanently saying "not recorded".
        attempts.record("s", "t", "synced")

        assert attempts.forget_older_than(days=30) == 0
        assert attempts.last_for("s", "t") is not None
