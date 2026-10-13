"""
A fact beside the object as it was at the fact's time (R46).

A transaction from May should be reported with the customer's region in
May, not today's: joining on today's dimension rewrites history every
time a customer moves. AsOf reads the changelog's SCD2 versions (R10)
and silver's current rows; as_of_join puts each fact beside the version
valid at the fact's own time.
"""

import csv
import io
import sqlite3

from core.mirror.changelog import AsOf, as_of_join

VERSIONS = [
    {"id": "c1", "region": "us-west", "_valid_from": None, "_valid_to": "2026-06-01T00:00:00+00:00",
     "_current": False},
    {"id": "c1", "region": "us-east", "_valid_from": "2026-06-01T00:00:00+00:00", "_valid_to": None,
     "_current": True},
    {"id": "c3", "region": "eu", "_valid_from": "2026-07-01T00:00:00+00:00", "_valid_to": None,
     "_current": True},
]
CURRENT = [{"id": "c1", "region": "us-east"}, {"id": "c2", "region": "ap"},
           {"id": "c3", "region": "eu"}]
AS_OF = AsOf(VERSIONS, CURRENT, "id")


class TestAVersionAtATime:
    def test_before_and_after_a_change(self):
        assert AS_OF.version_at("c1", "2026-05-15")["region"] == "us-west"
        assert AS_OF.version_at("c1", "2026-06-02")["region"] == "us-east"

    def test_the_boundary_belongs_to_the_new_version(self):
        assert AS_OF.version_at("c1", "2026-06-01T00:00:00+00:00")["region"] == "us-east"

    def test_an_object_never_seen_changing_is_as_it_is_now(self):
        assert AS_OF.version_at("c2", "2020-01-01")["region"] == "ap"

    def test_an_object_inserted_later_did_not_exist_then(self):
        assert AS_OF.version_at("c3", "2026-06-15") is None

    def test_bookkeeping_columns_are_not_part_of_the_answer(self):
        assert AS_OF.version_at("c1", "2026-05-15") == {"id": "c1", "region": "us-west"}


def test_each_fact_joins_the_version_of_its_own_day():
    facts = [{"tx": "t1", "customer": "c1", "on": "2026-05-20"},
             {"tx": "t2", "customer": "c1", "on": "2026-06-20"},
             {"tx": "t3", "customer": "c3", "on": "2026-05-20"},
             {"tx": "t4", "customer": None, "on": "2026-05-20"}]

    joined = as_of_join(facts, "on", "customer", AS_OF)

    assert [None if row["_as_of"] is None else row["_as_of"]["region"] for row in joined] == \
        ["us-west", "us-east", None, None]


def test_the_history_script_answers_as_of_a_time(synced_deployment):
    """Through the real changelog: a customer renamed after the first
    sync reads with the OLD name as of a time before the rename."""
    from datetime import UTC, datetime, timedelta

    from scripts.history_of import run
    from scripts.run_sync import run_sync

    before_rename = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    db = synced_deployment.data_dir / "dev_fixtures" / "mediator.db"
    connection = sqlite3.connect(db)
    old = connection.execute("SELECT name FROM customers WHERE customer_id = 'cust_001'").fetchone()[0]
    connection.execute("UPDATE customers SET name = 'Renamed' WHERE customer_id = 'cust_001'")
    connection.commit()
    connection.close()
    with __import__("contextlib").redirect_stdout(io.StringIO()):
        assert run_sync(synced_deployment) == 0

    def names(at):
        out = io.StringIO()
        assert run("primary_sql.customers", "cust_001", paths=synced_deployment, out=out,
                   as_of=at) == 0
        return [row["name"] for row in csv.DictReader(io.StringIO(out.getvalue()))]

    assert names(before_rename) == [old]
    assert names(datetime.now(UTC).isoformat()) == ["Renamed"]
