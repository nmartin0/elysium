"""
A catalog repair does not run while a sync is writing (PA001-A16).

`repair_catalog --write` REPOINTS TABLES in the same catalog a sync
writes to. A repair landing between a sync's read and its commit is
exactly the race Iceberg's optimistic concurrency turns into a hard
failure -- and `_single_writer` exists to prevent precisely that.

IT WAS A PRIVATE HELPER OF run_sync, so this script simply did not
take it. Not an oversight in the reasoning: the lock's own docstring
already explains the race in detail, for the sync. Nobody asked
whether anything ELSE writes to the catalog.

SO IT MOVED. `core/mirror/sync_lock.py` holds it now, because two
callers is the moment a private helper becomes a shared one. The
reasoning is the sync's original, unchanged.

REFUSES RATHER THAN WAITS, like the sync: a repair is a deliberate act
by a person at a terminal, and "a sync is running, try again" is a
better answer than blocking for an unknown time while they wonder
whether it has hung. It says NOTHING WAS REPAIRED, because a repair
that half-ran would be worse than one that did not start.
"""

from pathlib import Path

import pytest

from core.mirror.sync_lock import single_writer


class TestTheLockItself:
    def test_one_holder_at_a_time(self, tmp_path):
        with single_writer(tmp_path / "sync.lock") as first:
            assert first is True
            with single_writer(tmp_path / "sync.lock") as second:
                assert second is False

    def test_it_is_released_afterwards(self, tmp_path):
        with single_writer(tmp_path / "sync.lock") as first:
            assert first
        with single_writer(tmp_path / "sync.lock") as again:
            assert again is True

    def test_it_is_released_even_when_the_body_raises(self, tmp_path):
        """flock releases on process death, and the context manager
        must release on an exception -- or one failed sync would block
        every later one until a restart.

        HONEST NOTE: this test cannot fail for the reason it looks
        like it guards. A control removing the explicit
        `flock(LOCK_UN)` left it passing, because the enclosing
        `with open(...)` closes the file and CLOSING RELEASES THE
        LOCK. The explicit unlock is belt-and-braces; the `with` is
        what does the work. The test is kept because the PROPERTY
        matters, and a future rewrite that held the file open longer
        would break it for real."""
        with pytest.raises(RuntimeError):
            with single_writer(tmp_path / "sync.lock") as acquired:
                assert acquired
                raise RuntimeError("injected")

        with single_writer(tmp_path / "sync.lock") as after:
            assert after is True

    def test_the_directory_is_created_if_absent(self, tmp_path):
        """A first sync on a fresh deployment has no mirror directory
        yet."""
        with single_writer(tmp_path / "new" / "sync.lock") as acquired:
            assert acquired is True


class TestBothWritersUseIt:
    """The point of the move: one lock, two callers. A test rather
    than a comment, because the failure mode of getting this wrong is
    silent -- two writers that never notice each other until a commit
    is rejected."""

    def test_the_sync_takes_it(self):
        source = Path("scripts/run_sync.py").read_text()

        assert "from core.mirror.sync_lock import single_writer" in source
        assert "single_writer(runtime_paths.data_dir" in source

    def test_and_so_does_the_repair(self):
        source = Path("scripts/repair_catalog.py").read_text()

        assert "from core.mirror.sync_lock import single_writer" in source
        assert "single_writer(" in source

    def test_the_repair_refuses_rather_than_waiting(self):
        source = Path("scripts/repair_catalog.py").read_text()

        assert "NOTHING WAS REPAIRED" in source

    def test_they_name_the_same_lock_file(self):
        """Two locks would be no lock at all."""
        sync = Path("scripts/run_sync.py").read_text()
        repair = Path("scripts/repair_catalog.py").read_text()

        assert '"sync.lock"' in sync
        assert '"sync.lock"' in repair
