"""
What a generation pins, and what it does not (PA001-A6).

THIS FILE CHANGES NO BEHAVIOUR. It measures and pins the behaviour
that exists, because A6 turns out to be a DECISION this repository has
already made in the opposite direction, and the owner should make it
knowingly rather than inherit it from a comment.

WHAT A6 REPORTS. A generation pins the snapshot of every table it was
built against, so a reload cannot move the ground under a request
mid-flight. A table ABSENT from that pin map falls through to
`current`. So one generation can serve a pinned table as of its
snapshot and an unpinned one as of now.

MEASURED, and the numbers are the point:

    a generation built when only type A was published
    both A and B then change and are published
    the SAME generation answers "one" for A and "two" for B

Two ages in one answer, and the agent can join across them in a single
query with nothing marking the halves as coming from different
moments.

THE OTHER SIDE, which is written down in
tests/unit/test_mirror_snapshot_pin.py and predates the audit:

    A table synced for the first time AFTER this generation was built
    has no id to pin. Reading its current state is better than reading
    nothing, and better than raising -- the mirror is allowed to gain
    tables between reloads.

That is a real argument, not an oversight.

WHAT I TRIED, AND WHY IT IS NOT HERE. Making the pin map authoritative
-- a table absent from it is not served -- breaks two things. It
contradicts the decision above, and it REFUSES EVERY MANY-TO-MANY
LINK, because link tables are published to gold but never appear in
published_snapshot_ids. Six tests from patch 425 failed immediately.
A fix that silently disables a feature is not a fix.

SO THE CHOICE IS THE OWNER'S:

  (a) leave it: a generation may serve two ages, and a table gained
      between reloads is readable at once.
  (b) make the pin map authoritative AND put link tables in it: one
      generation, one moment, at the cost of a new table being
      invisible until the next reload.
  (c) pin per REQUEST rather than per generation, which is the
      roadmap's own open question about snapshot pinning.

The tests below pin (a) so that (b) or (c) has to be chosen
deliberately.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.gold import build_gold, published_snapshot_ids
from core.mirror.gold_connector import GoldConnector
from core.mirror.iceberg_sync import IcebergMirrorSync


def _type(table):
    return {"id_field": "id", "security": {"field": "region"},
            "storage": {"silo": "p", "table": table, "id_column": "id"},
            "fields": {"id": {"type": "data"}, "v": {"type": "data"},
                        "region": {"type": "data"}}}


SCHEMA = {"A": _type("a"), "B": _type("b")}


def _config(object_type):
    return {"storage": {"table": object_type, "id_column": "id"}, "fields": {}}


@pytest.fixture
def deployment(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    for table in ("a", "b"):
        conn.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, v TEXT, region TEXT)")
        conn.execute(f"INSERT INTO {table} VALUES ('{table}1','one','us-west')")
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "m", {"p": SQLiteReadAdapter({"path": source})})

    def sync_all():
        for table in ("a", "b"):
            sync.sync_table("p", table, "id", ["id", "v", "region"], {})

    def publish(object_type):
        table = SCHEMA[object_type]["storage"]["table"]
        build_gold(sync.catalog, object_type, SCHEMA[object_type],
                    sync.catalog.load_table(f"p.{table}").scan().to_arrow())

    def change(value):
        conn = sqlite3.connect(source)
        for table in ("a", "b"):
            conn.execute(f"UPDATE {table} SET v=? WHERE id='{table}1'", (value,))
        conn.commit()
        conn.close()

    sync.sync_all, sync.publish, sync.change = sync_all, publish, change
    return sync


class TestWhatIsPinned:
    def test_a_pinned_type_holds_its_moment(self, deployment):
        """The guarantee that works, and the reason pinning exists: a
        reload cannot move the ground under a request."""
        deployment.sync_all()
        deployment.publish("A")
        connector = GoldConnector(deployment.catalog,
                                   published_snapshot_ids(deployment.catalog, SCHEMA))

        deployment.change("two")
        deployment.sync_all()
        deployment.publish("A")

        assert connector.get_raw_field("A", "a1", "v", _config("A")) == "one"


class TestWhatIsNot:
    def test_a_type_published_later_is_read_at_CURRENT(self, deployment):
        """PA001-A6, measured. Today's behaviour, pinned so that
        changing it is a decision rather than a side effect."""
        deployment.sync_all()
        deployment.publish("A")
        connector = GoldConnector(deployment.catalog,
                                   published_snapshot_ids(deployment.catalog, SCHEMA))

        deployment.change("two")
        deployment.sync_all()
        deployment.publish("B")

        assert connector.get_raw_field("B", "b1", "v", _config("B")) == "two"

    def test_so_ONE_GENERATION_SERVES_TWO_AGES(self, deployment):
        """The finding in one assertion. A and B are read through the
        same connector, in the same request, and disagree about when
        'now' is."""
        deployment.sync_all()
        deployment.publish("A")
        connector = GoldConnector(deployment.catalog,
                                   published_snapshot_ids(deployment.catalog, SCHEMA))

        deployment.change("two")
        deployment.sync_all()
        deployment.publish("B")

        assert connector.get_raw_field("A", "a1", "v", _config("A")) == "one"
        assert connector.get_raw_field("B", "b1", "v", _config("B")) == "two"


class TestWhyTheObviousFixIsNotEnough:
    def test_link_tables_are_absent_from_the_pin_map(self, deployment):
        """THE REASON (b) IS NOT A ONE-LINE CHANGE. published_snapshot_ids
        walks OBJECT TYPES. A join table is published to gold and is
        not an object type, so it never appears -- and making the pin
        map authoritative without fixing this refuses every
        many-to-many link."""
        deployment.sync_all()
        deployment.publish("A")

        pins = published_snapshot_ids(deployment.catalog, SCHEMA)

        assert set(pins) <= set(SCHEMA), (
            "if this now includes non-object-type tables, option (b) "
            "may have become viable")
