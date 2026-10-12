"""Reclaiming data files no snapshot references (R11).

THE ORPHAN IS PLANTED: a copy of a real data file under a new name in a
real table's data directory, which no snapshot can reference. The
sweep must find it, delete it only with --write, leave every referenced
file -- the table must still read -- and leave a YOUNG orphan alone,
which is what a write in flight looks like.
"""

import contextlib
import io
import os
import shutil
import time

from core.mirror.catalog import open_mirror_catalog
from scripts.remove_orphan_files import run

TABLE = "primary_sql.customers"


def _data_dir(paths):
    return paths.data_dir / "mirror" / "warehouse" / "primary_sql" / "customers" / "data"


def _plant(paths, name: str, age_hours: float):
    real = next(_data_dir(paths).rglob("*.parquet"))
    orphan = real.with_name(name)
    shutil.copy(real, orphan)
    then = time.time() - age_hours * 3600
    os.utime(orphan, (then, then))
    return orphan


def _run(paths, **kwargs) -> str:
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        assert run(paths, **kwargs) == 0
    return printed.getvalue()


def test_a_dry_run_reports_and_deletes_nothing(synced_deployment):
    orphan = _plant(synced_deployment, "orphan-old.parquet", age_hours=100)

    report = _run(synced_deployment)

    assert f"{TABLE}: 1 orphaned file(s)" in report
    assert "dry run" in report
    assert orphan.exists()


def test_write_deletes_the_orphan_and_nothing_the_table_uses(synced_deployment):
    orphan = _plant(synced_deployment, "orphan-old.parquet", age_hours=100)
    rows_before = len(open_mirror_catalog(synced_deployment.data_dir / "mirror")
                      .load_table(TABLE).scan().to_arrow())

    _run(synced_deployment, write=True)

    assert not orphan.exists()
    table = open_mirror_catalog(synced_deployment.data_dir / "mirror").load_table(TABLE)
    assert len(table.scan().to_arrow()) == rows_before


def test_a_young_orphan_is_left_alone(synced_deployment):
    """THE MARGIN: an unreferenced file written an hour ago is what a
    write in flight looks like, and Iceberg's own procedure spares it."""
    young = _plant(synced_deployment, "orphan-young.parquet", age_hours=1)

    _run(synced_deployment, write=True)

    assert young.exists()


def test_nothing_is_touched_while_a_sync_holds_the_lock(synced_deployment):
    from core.mirror.sync_lock import single_writer

    orphan = _plant(synced_deployment, "orphan-old.parquet", age_hours=100)
    with single_writer(synced_deployment.data_dir / "sync.lock") as acquired:
        assert acquired
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = run(synced_deployment, write=True)

    assert code == 1 and "A sync is running" in printed.getvalue()
    assert orphan.exists()
