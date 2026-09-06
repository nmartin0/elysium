"""
Tests for the single-writer lock on scripts/run_sync.py.

WHY IT EXISTS. Iceberg uses optimistic concurrency: a commit carries
"the table's metadata is version N", and a second writer that started
from the same N is rejected rather than allowed to clobber the first.
That is the correct design -- it is what stops a lost overwrite.

But PyIceberg surfaces the rejection as a hard exception whose retry
loop cannot resolve a full-table overwrite (Java Iceberg retries
transparently; PyIceberg's equivalent is still an open pull request).
Confirmed directly by running two syncs at once: one succeeded, the
other failed with "Added data files were found matching the filter".

And it is genuinely reachable, not hypothetical -- INSTALL.md tells
operators to schedule syncs with cron or a systemd timer, and nothing
stops a slow run from overlapping the next scheduled one.
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path("tests/integration/fixtures")


@pytest.fixture
def deployment(tmp_path):
    (tmp_path / "dev_fixtures").mkdir()
    for db_name, schema_name in (
        ("mediator.db", "schema.sql"),
        ("support.db", "support_schema.sql"),
        ("risk.db", "risk_schema.sql"),
    ):
        conn = sqlite3.connect(tmp_path / "dev_fixtures" / db_name)
        conn.executescript((FIXTURES / schema_name).read_text())
        conn.commit()
        conn.close()
    return tmp_path


def _run_sync(data_dir, **popen_kwargs):
    env = {
        **os.environ,
        "ELYSIUM_CONFIG_DIR": str(FIXTURES.resolve()),
        "ELYSIUM_DATA_DIR": str(data_dir),
    }
    return subprocess.Popen(
        [sys.executable, "-m", "scripts.run_sync"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **popen_kwargs,
    )


def test_a_single_sync_runs_normally(deployment):
    # The lock must not break the ordinary case.
    process = _run_sync(deployment)
    stdout, _stderr = process.communicate(timeout=120)

    assert process.returncode == 0
    assert "6/6 tables synced successfully" in stdout


def test_a_second_concurrent_sync_exits_instead_of_colliding(deployment):
    # Exits cleanly rather than blocking: the run it collided with is
    # already copying the same data, so waiting would only queue
    # redundant work.
    first = _run_sync(deployment)
    second = _run_sync(deployment)

    first_out, first_err = first.communicate(timeout=120)
    second_out, second_err = second.communicate(timeout=120)

    combined_err = first_err + second_err
    combined_out = first_out + second_out

    assert "another sync is already running" in combined_err
    assert "6/6 tables synced successfully" in combined_out
    # Neither process fails -- the skipped one is a normal outcome, not
    # an error a scheduler should alert on.
    assert first.returncode == 0
    assert second.returncode == 0


def test_the_lock_is_released_so_a_later_sync_still_runs(deployment):
    # flock releases automatically when the process exits, including on
    # a crash -- no stale lock file to clean up, unlike a hand-rolled
    # PID file.
    first = _run_sync(deployment)
    first.communicate(timeout=120)

    second = _run_sync(deployment)
    stdout, _stderr = second.communicate(timeout=120)

    assert second.returncode == 0
    assert "6/6 tables synced successfully" in stdout


def test_a_hard_killed_holder_leaves_no_stale_lock(deployment, tmp_path):
    # THE property that justified flock over a PID file, verified
    # rather than asserted in a comment. A process killed with SIGKILL
    # runs no cleanup at all -- the kernel releases the lock, so the
    # next sync proceeds normally. A hand-rolled PID file would be left
    # behind here and would block every subsequent run until someone
    # removed it by hand.
    import signal
    import time

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import fcntl, time; f = open({str(deployment / 'sync.lock')!r}, 'w'); "
            "fcntl.flock(f, fcntl.LOCK_EX); print('held', flush=True); time.sleep(60)",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    holder.stdout.readline()

    blocked = _run_sync(deployment)
    _out, err = blocked.communicate(timeout=120)
    assert "another sync is already running" in err

    holder.send_signal(signal.SIGKILL)
    holder.wait(timeout=10)
    time.sleep(0.3)

    recovered = _run_sync(deployment)
    stdout, _stderr = recovered.communicate(timeout=120)
    assert "6/6 tables synced successfully" in stdout
