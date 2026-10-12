"""scripts/history_of: a source row's versions, through the real sync (R10)."""

import contextlib
import csv
import io
import sqlite3

from scripts.history_of import run
from scripts.run_sync import run_sync


def test_a_renamed_customer_has_two_versions_and_one_is_current(synced_deployment):
    with sqlite3.connect(synced_deployment.data_dir / "dev_fixtures" / "mediator.db") as conn:
        conn.execute("UPDATE customers SET name = 'Ada O.' WHERE customer_id = 'cust_001'")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        run_sync(synced_deployment)

    out = io.StringIO()
    assert run("primary_sql.customers", "cust_001", paths=synced_deployment, out=out) == 0
    versions = list(csv.DictReader(io.StringIO(out.getvalue())))

    assert [(v["name"], v["_current"]) for v in versions] == [
        ("Ada Okafor", "False"), ("Ada O.", "True")]
    # The first version began before the changelog existed: unknown, not invented.
    assert versions[0]["_valid_from"] == ""
    assert versions[0]["_valid_to"] == versions[1]["_valid_from"] != ""


def test_a_table_this_deployment_does_not_sync_is_refused(synced_deployment):
    with contextlib.redirect_stderr(io.StringIO()):
        assert run("primary_sql.nope", paths=synced_deployment, out=io.StringIO()) == 1
