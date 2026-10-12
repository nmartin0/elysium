"""R66 through the real run_sync: the operator's flag reaches gold.

The matrix test (test_a_source_changes_and_what_a_reader_sees.py)
proves build_gold honours the flag; this proves run_sync PASSES it,
which is the half that was missing -- the flag reached the sync and
stopped there.
"""

import contextlib
import io
import sqlite3

from core.mirror.catalog import open_mirror_catalog
from core.mirror.gold import _latest_published_snapshot
from scripts.run_sync import run_sync


def _published_transactions(paths) -> int:
    table = open_mirror_catalog(paths.data_dir / "mirror").load_table("gold.Transaction")
    return len(table.scan(snapshot_id=_latest_published_snapshot(table)).to_arrow())


def _delete_most_transactions(paths) -> None:
    with sqlite3.connect(paths.data_dir / "dev_fixtures" / "mediator.db") as conn:
        conn.execute("DELETE FROM transactions WHERE transaction_id > 1")


def _sync(paths, **kwargs) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return run_sync(paths, **kwargs)


def test_the_accepted_deletion_reaches_the_reader(synced_deployment):
    before = _published_transactions(synced_deployment)
    _delete_most_transactions(synced_deployment)

    _sync(synced_deployment, accept_deletions={"primary_sql.transactions"})

    assert before > 2
    assert _published_transactions(synced_deployment) == 1


def test_accepting_a_different_table_licenses_nothing(synced_deployment):
    """THE CONTROL: the flag names the table, and only that table's
    types move."""
    before = _published_transactions(synced_deployment)
    _delete_most_transactions(synced_deployment)

    _sync(synced_deployment, accept_deletions={"primary_sql.customers"})

    assert _published_transactions(synced_deployment) == before
