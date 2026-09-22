"""
Generation numbers are unique across restarts and across workers.

THE BUG, MEASURED. Numbers came from itertools.count(1) -- per process,
back to 1 on every start. config_history keys on the number and writes
with INSERT OR IGNORE, so after a RESTART the new generation 1 hit the
old row and was SILENTLY DROPPED: the history showed the previous run's
configuration under that number while a different one ran.

ONE WORKER WAS ENOUGH -- this was not only a multi-worker problem. It
was found while making generation numbers safe for several workers.

NOW THEY ARE ALLOCATED from config_history.db, shared by every process,
seeded from the highest generation already recorded.
"""

import sqlite3
import subprocess
import sys

import pytest

from core.config_history import ConfigHistory


@pytest.fixture
def data_dir(private_deployment):
    # E-08: this COPIED the developer's data directory, credentials and
    # all. A private, empty one has no config history to remove.
    return private_deployment.data_dir


def _one_process_lifetime(data_dir, tag):
    """Builds and records one generation in a FRESH interpreter -- a
    restart, as far as any per-process counter can tell."""
    code = f"""
from pathlib import Path
from core.config_history import ConfigHistory, record_generation
from core.deployment_loader import build_generation, resolve_runtime_paths
r = resolve_runtime_paths()
g = build_generation(r.config_dir, Path({str(data_dir)!r}), r.log_dir)
object.__setattr__(g, 'source_digest', g.source_digest[:-4] + {tag!r})
record_generation(ConfigHistory(Path({str(data_dir)!r}) / 'config_history.db'), g)
print(g.generation)
"""
    result = subprocess.run([sys.executable, "-c", code],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return int(result.stdout.strip())


class TestARestartIsRecorded:
    def test_each_process_lifetime_gets_its_own_number(self, data_dir):
        first = _one_process_lifetime(data_dir, "AAAA")
        second = _one_process_lifetime(data_dir, "BBBB")

        assert second > first

    def test_and_both_are_in_the_history(self, data_dir):
        """THE BUG: the second was silently dropped by INSERT OR IGNORE."""
        _one_process_lifetime(data_dir, "AAAA")
        _one_process_lifetime(data_dir, "BBBB")

        digests = {
            row.source_digest[-4:]
            for row in ConfigHistory(data_dir / "config_history.db").list_generations()
        }
        assert digests == {"AAAA", "BBBB"}


class TestAnExistingHistoryIsContinued:
    def test_numbering_carries_on_after_the_highest_recorded(self, tmp_path):
        """A DEPLOYMENT UPGRADED from per-process numbering already holds
        generations 1..5. The sequence starts after them rather than
        colliding with them."""
        path = tmp_path / "config_history.db"
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE config_generations (generation INTEGER PRIMARY KEY, "
            "loaded_at TEXT NOT NULL, source_digest TEXT NOT NULL, "
            "files TEXT NOT NULL, recorded_at TEXT NOT NULL)",
        )
        for number in range(1, 6):
            conn.execute(
                "INSERT INTO config_generations VALUES (?, 't', 'd', '{}', 't')",
                (number,),
            )
        conn.commit()
        conn.close()

        assert ConfigHistory(path).allocate_generation() == 6


class TestALoadIsWhatIsNumbered:
    def test_the_same_files_loaded_twice_get_two_numbers(self, data_dir, private_deployment):
        """TWO LOADS, TWO NUMBERS -- even of the same files. The number
        says which load; the digest says what was loaded.

        WHAT THIS DOES NOT PROVE: uniqueness across processes. Both loads
        run in this one process, where the old per-process counter ALSO
        gave distinct numbers -- a control restoring it passed this test.
        The restart tests above run separate interpreters, and those are
        what failed under the old counter."""
        from core.deployment_loader import build_generation

        real = private_deployment  # E-08: never the developer's deployment
        one = build_generation(real.config_dir, data_dir, real.log_dir)
        two = build_generation(real.config_dir, data_dir, real.log_dir)

        assert one.generation != two.generation
        assert one.source_digest == two.source_digest
