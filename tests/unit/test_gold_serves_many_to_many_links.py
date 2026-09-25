"""
Many-to-many links read the same from gold as from the source
(PA001-G1, and the first half of PA001-G2).

G1 DOES NOT REPRODUCE, and the reason is worth recording rather than
just ticking. It reported that a many-to-many link RAISES on gold
because the view points it at `gold.<Target>`, which has no such
column. Two things had already closed it:

  - gold_view keeps the JOIN TABLE's own name for a link whose
    via_table is not the target's table. That branch says it was
    "FOUND BY THE INTEGRATION SUITE once it read gold".
  - PA001-A2 (patch 410) made the join table a sync target at all.
    Before it, the table never reached silver, so _publish_link_tables
    had nothing to copy and every many-to-many link read EMPTY from
    gold -- not raising, but not right either.

SO THE TEST IS THE DELIVERABLE HERE. Nothing compared a many-to-many
link read from GOLD against the same link read from the SOURCE, which
is exactly the gap PA001-G2 names: the existing parity test compares
gold to the MIRROR, on a schema with no many-to-many link and no
cross-silo field, so it could not have seen this.

COMPARING AGAINST THE SOURCE IS THE POINT. Gold agreeing with silver
proves the copy was faithful; it says nothing about whether either
matches the database the customer actually has.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.intermediate_layer.auth import UserRecord
from core.mirror.gold import build_gold, published_snapshot_ids
from core.mirror.gold_connector import GoldConnector
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.sync_targets import resolve_sync_targets
from core.ontology.gold_view import build_gold_view
from core.ontology.link_types import expand_link_types
from core.ontology.mediator import DataMediator
from scripts.run_sync import _publish_link_tables

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
            "join_table": {"table": "customer_tags",
                            "source_column": "customer_id",
                            "target_column": "tag_id"}},
}
USER = UserRecord(user_id="u", security_value="us-west", role_name="r")


@pytest.fixture
def both(tmp_path):
    """The same question asked of the SOURCE and of GOLD."""
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
    for object_type in ("Customer", "Tag"):
        table = schema[object_type]["storage"]["table"]
        build_gold(sync.catalog, object_type, schema[object_type],
                    sync.catalog.load_table(f"p.{table}").scan().to_arrow())
    _publish_link_tables(sync, schema)

    grants = []
    for object_type, type_def in schema.items():
        grants += [f"read:{object_type}"]
        grants += [f"read:{object_type}.{f}" for f in type_def["fields"]]
        grants.append(f"read:{object_type}.{type_def['id_field']}")
    roles = {"r": {"allowed_actions": grants}}

    view, _ = build_gold_view(schema)
    connector = GoldConnector(sync.catalog, published_snapshot_ids(sync.catalog, view))
    return {
        "live": DataMediator(schema, {"p": SQLiteReadAdapter({"path": source})},
                              {t: "p" for t in schema}, roles),
        "gold": DataMediator(view, {"gold": connector},
                              {t: "gold" for t in view}, roles),
    }


class TestGoldAgreesWithTheSource:
    @pytest.mark.parametrize("object_type,object_id,field", [
        ("Customer", "c1", "tags"),
        ("Customer", "c2", "tags"),
        ("Tag", "vip", "customers"),
        ("Tag", "new", "customers"),
    ])
    def test_a_link_field(self, both, object_type, object_id, field):
        live = sorted(both["live"].get_field(USER, object_type, object_id, field) or [])
        gold = sorted(both["gold"].get_field(USER, object_type, object_id, field) or [])

        assert gold == live
        assert live, "the fixture has no links; the test would prove nothing"

    def test_link_counts(self, both):
        live = both["live"].link_counts(USER, "Customer", "c1")["tags"]["count"]
        gold = both["gold"].link_counts(USER, "Customer", "c1")["tags"]["count"]

        assert gold == live == 2

    def test_search_around(self, both):
        live = sorted(both["live"].search_around(USER, "Customer", [], "tags"))
        gold = sorted(both["gold"].search_around(USER, "Customer", [], "tags"))

        assert gold == live == ["new", "vip"]

    def test_it_does_not_raise(self, both):
        """G1's literal claim. It does not, and a test that only
        asserted "no exception" would have passed while gold returned
        an empty list -- which is why every test above compares
        VALUES."""
        both["gold"].get_field(USER, "Customer", "c1", "tags")


class TestTheViewKeepsTheJoinTable:
    def test_a_many_to_many_link_points_at_the_join_table(self):
        """Not at gold.<Target>, which has no such column. This is the
        mechanism G1 reported as broken."""
        schema = expand_link_types(LINK_TYPES, OBJECT_TYPES)

        view, _ = build_gold_view(schema)

        tags = view["Customer"]["fields"]["tags"]
        assert tags["via_table"] == "customer_tags"
        assert tags["via_column"] == "customer_id"

    def test_a_ONE_to_many_link_is_re_keyed_to_the_target(self):
        """The other branch, kept honest: a reverse link whose
        via_table IS the target's own table is re-pointed at
        gold.<Target> and its PROPERTY name."""
        object_types = {
            "Customer": OBJECT_TYPES["Customer"],
            "Order": {"storage": {"silo": "p", "table": "orders",
                                   "id_column": "order_id"},
                       "id_field": "order_id", "security": {"field": "region"},
                       "fields": {"region": {"type": "data"},
                                   "customer_id": {"type": "data"}}},
        }
        schema = expand_link_types(
            {"CO": {"source": {"object_type": "Customer", "api_name": "orders"},
                     "target": {"object_type": "Order", "api_name": "customer"},
                     "cardinality": "one_to_many",
                     "foreign_key_column": "customer_id"}}, object_types)

        view, _ = build_gold_view(schema)

        assert view["Customer"]["fields"]["orders"]["via_table"] == "Order"
