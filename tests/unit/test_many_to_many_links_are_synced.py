"""
Many-to-many links work on the mirror (PA001-A2).

WHAT WAS WRONG. resolve_sync_targets skips any field carrying
`via_table`, with a comment saying a reverse link "lives in the OTHER
type's table, which is already its own sync target". True for a
ONE-to-many link. For MANY-to-many, via_table is the JOIN TABLE --
customer_tags, enrollments -- which backs no object type, so nothing
ever emitted it and it was never synced.

The mirror then answered every many-to-many question with an EMPTY
LIST. Not an error: a customer with no tags, indistinguishable from
the truth. link_counts said 0 and search_around returned nothing.

AND A SECOND DEFECT THE AUDIT'S FIX NOTE DOES NOT MENTION, found by
running it: a join table has NO ID. Keyed by either column alone,
every second row is a duplicate -- and the default policy is
QUARANTINE -- so a customer with two tags lost one. Measured: live
said ['c1', 'c2'], the mirror said ['c2']. A subset of the truth is
worse than an empty list, because an empty list looks wrong and a
subset looks right.

So a join table is keyed by its PAIR, synthesised into silver. Not
into bronze: bronze holds what the source held, and the source has no
such column.

GOLD DEPENDED ON THIS TOO. _publish_link_tables reads
`{silo}.{table}` from silver for every join table -- a table that was
never going to be there, so it failed on every run.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.intermediate_layer.auth import UserRecord
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.mirror_adapter import MirrorReadAdapter
from core.mirror.sync_targets import LINK_ID_COLUMN, resolve_sync_targets
from core.ontology.link_types import expand_link_types
from core.ontology.mediator import DataMediator

OBJECT_TYPES = {
    "Customer": {"storage": {"silo": "p", "table": "customers",
                              "id_column": "customer_id"},
                  "id_field": "customer_id", "security": {"field": "region"},
                  "fields": {"name": {"type": "data"}, "region": {"type": "data"}}},
    "Tag": {"storage": {"silo": "p", "table": "tags", "id_column": "tag_id"},
             "id_field": "tag_id", "security": {"field": "region"},
             "fields": {"label": {"type": "data"}, "region": {"type": "data"}}},
}
LINK_TYPES = {
    "CT": {"source": {"object_type": "Customer", "api_name": "tags"},
            "target": {"object_type": "Tag", "api_name": "customers"},
            "cardinality": "many_to_many",
            "join_table": {"table": "customer_tags", "source_column": "customer_id",
                            "target_column": "tag_id"}},
}


@pytest.fixture
def both_paths(tmp_path):
    """One source, served two ways: live and through the mirror. The
    mirror is only correct if it agrees with the source."""
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.executescript(
        "CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, region TEXT);"
        "CREATE TABLE tags (tag_id TEXT PRIMARY KEY, label TEXT, region TEXT);"
        "CREATE TABLE customer_tags (customer_id TEXT, tag_id TEXT);")
    conn.executemany("INSERT INTO customers VALUES (?,?,?)",
                     [("c1", "Ada", "us-west"), ("c2", "Bram", "us-west")])
    conn.executemany("INSERT INTO tags VALUES (?,?,?)",
                     [("vip", "VIP", "us-west"), ("new", "New", "us-west")])
    # c1 has TWO tags: the row that was being quarantined.
    conn.executemany("INSERT INTO customer_tags VALUES (?,?)",
                     [("c1", "vip"), ("c1", "new"), ("c2", "vip")])
    conn.commit()
    conn.close()

    schema = expand_link_types(LINK_TYPES, OBJECT_TYPES)
    sync = IcebergMirrorSync(tmp_path / "m", {"p": SQLiteReadAdapter({"path": source})})
    for target in resolve_sync_targets({"object_types": schema}):
        sync.sync_table(target.silo_name, target.table_name, target.id_column,
                        target.columns, target.column_types, target.fields_by_column,
                        target.standardisation, target.expectations,
                        target.duplicate_policy, target.object_types, target.link_pair)

    grants = []
    for object_type, type_def in schema.items():
        grants += [f"read:{object_type}"]
        grants += [f"read:{object_type}.{f}" for f in type_def["fields"]]
        grants.append(f"read:{object_type}.{type_def['id_field']}")
    roles = {"r": {"allowed_actions": grants}}
    silo_for = {t: "p" for t in schema}
    return {
        "sync": sync,
        "live": DataMediator(schema, {"p": SQLiteReadAdapter({"path": source})},
                              silo_for, roles),
        "mirror": DataMediator(schema, {"p": MirrorReadAdapter(sync.catalog, "p")},
                                silo_for, roles),
        "user": UserRecord(user_id="u", security_value="us-west", role_name="r"),
    }


class TestTheMirrorAgreesWithTheSource:
    @pytest.mark.parametrize("object_type,object_id,field", [
        ("Customer", "c1", "tags"),
        ("Customer", "c2", "tags"),
        ("Tag", "vip", "customers"),
        ("Tag", "new", "customers"),
    ])
    def test_a_link_field_reads_the_same_on_both_paths(self, both_paths, object_type,
                                                        object_id, field):
        user = both_paths["user"]
        live = sorted(both_paths["live"].get_field(user, object_type, object_id, field) or [])
        mirror = sorted(both_paths["mirror"].get_field(user, object_type, object_id, field) or [])

        assert mirror == live
        assert live, "the fixture has no links; the test would prove nothing"

    def test_link_counts_agree(self, both_paths):
        user = both_paths["user"]

        live = both_paths["live"].link_counts(user, "Customer", "c1")["tags"]["count"]
        mirror = both_paths["mirror"].link_counts(user, "Customer", "c1")["tags"]["count"]

        assert mirror == live == 2

    def test_search_around_agrees(self, both_paths):
        user = both_paths["user"]

        live = sorted(both_paths["live"].search_around(user, "Customer", [], "tags"))
        mirror = sorted(both_paths["mirror"].search_around(user, "Customer", [], "tags"))

        assert mirror == live == ["new", "vip"]


class TestTheJoinTableIsSynced:
    def test_it_is_a_sync_target(self):
        schema = expand_link_types(LINK_TYPES, OBJECT_TYPES)

        tables = {t.table_name for t in resolve_sync_targets({"object_types": schema})}

        assert "customer_tags" in tables

    def test_it_carries_only_the_two_link_columns(self):
        schema = expand_link_types(LINK_TYPES, OBJECT_TYPES)

        (target,) = [t for t in resolve_sync_targets({"object_types": schema})
                     if t.table_name == "customer_tags"]

        assert sorted(target.columns) == ["customer_id", "tag_id"]
        assert target.link_pair == ("customer_id", "tag_id")

    def test_a_ONE_to_many_reverse_link_emits_no_extra_target(self):
        """The comment that caused this was RIGHT about one-to-many:
        via_table is the target's own table, already a target. Emitting
        it again would sync the same table twice."""
        object_types = {
            "Customer": OBJECT_TYPES["Customer"],
            "Order": {"storage": {"silo": "p", "table": "orders", "id_column": "order_id"},
                       "id_field": "order_id", "security": {"field": "region"},
                       "fields": {"region": {"type": "data"}}},
        }
        schema = expand_link_types(
            {"CO": {"source": {"object_type": "Customer", "api_name": "orders"},
                     "target": {"object_type": "Order", "api_name": "customer"},
                     "cardinality": "one_to_many",
                     "foreign_key_column": "customer_id"}}, object_types)

        tables = sorted(t.table_name for t in resolve_sync_targets({"object_types": schema}))

        assert tables == ["customers", "orders"]


    def test_a_CROSS_SILO_one_to_many_link_emits_no_bogus_target(self):
        """WRITTEN BECAUSE A CONTROL PROVED NOTHING. Dropping the
        "both columns or it is not a join table" guard still passed,
        because a same-silo one-to-many link's via_table is already a
        target and the duplicate check catches it.

        CROSS-SILO IS WHERE IT SHOWS: the target's table lives in silo
        q, the check looks for it under the SOURCE's silo p, finds
        nothing, and emits p.orders -- a table that does not exist.
        The sync would then fail on a table nobody declared."""
        object_types = {
            "Customer": OBJECT_TYPES["Customer"],
            "Order": {"storage": {"silo": "q", "table": "orders",
                                   "id_column": "order_id"},
                       "id_field": "order_id", "security": {"field": "region"},
                       "fields": {"region": {"type": "data"}}},
        }
        schema = expand_link_types(
            {"CO": {"source": {"object_type": "Customer", "api_name": "orders"},
                     "target": {"object_type": "Order", "api_name": "customer"},
                     "cardinality": "one_to_many",
                     "foreign_key_column": "customer_id"}}, object_types)

        targets = {(t.silo_name, t.table_name)
                   for t in resolve_sync_targets({"object_types": schema})}

        assert targets == {("p", "customers"), ("q", "orders")}


class TestTheRowsAreKeyedByTheirPair:
    def test_every_link_row_survives_the_sync(self, both_paths):
        """THE SECOND DEFECT. Keyed by customer_id alone, c1's second
        tag was a duplicate and the default policy quarantined it."""
        rows = both_paths["sync"].catalog.load_table("p.customer_tags") \
            .scan().to_arrow().to_pylist()

        assert len(rows) == 3

    def test_nothing_was_quarantined(self, both_paths):
        catalog = both_paths["sync"].catalog

        assert not catalog.table_exists("quarantine_p.customer_tags")

    def test_the_synthetic_key_is_the_pair(self, both_paths):
        rows = both_paths["sync"].catalog.load_table("p.customer_tags") \
            .scan().to_arrow().to_pylist()

        keys = {r[LINK_ID_COLUMN] for r in rows}
        assert keys == {"c1\x1fvip", "c1\x1fnew", "c2\x1fvip"}

    def test_bronze_holds_what_the_source_held(self, both_paths):
        """The synthetic column is silver's, not bronze's: bronze is
        the raw record and the source has no such column.

        HONESTLY: this is guaranteed by WHERE the synthesis happens --
        bronze is written before it -- so no mutation of the current
        design can break it, and it is documentation rather than a
        guard. It is kept because a later change that moved the
        synthesis earlier would be caught here, and because the
        bronze/silver distinction is the point."""
        columns = both_paths["sync"].catalog.load_table("bronze_p.customer_tags") \
            .schema().column_names

        assert LINK_ID_COLUMN not in columns
        assert sorted(columns) == ["customer_id", "tag_id"]
