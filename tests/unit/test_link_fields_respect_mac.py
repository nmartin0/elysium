"""
A link field never lists objects the caller may not see (PA001-X1).

THE LEAK, reproduced with ONE ROW. A us-west user reading a us-west tag
got back a us-east customer's id, while link_counts and search_around
on the SAME link correctly reported two. The customer's own object
answered `{'name': None}` -- the object was protected and its
IDENTITY was not.

link_counts had the filter and its own comment explained exactly why:
"a deployment whose link crosses a MAC boundary would leak a count of
objects the caller cannot see, which is exactly the disclosure this
feature must not make". The comment then called the case "UNTESTABLE
IN THIS DEPLOYMENT". One many-to-many row that crosses regions tests
it, and get_field two methods above had no such filter.

THE AGENT READS THROUGH get_object, which reads through get_field, so
this reached the model too.

WHAT IS DELIBERATELY NOT CHANGED HERE: a FORWARD single-valued link
(Order.customer) still returns its target's id even when that object
is invisible. That id is a foreign-key COLUMN of the caller's own
visible row, so hiding it is a different decision with different
consequences -- recorded for the owner rather than changed quietly.
The test at the bottom pins today's behaviour so the decision is
visible and cannot drift by accident.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.intermediate_layer.auth import UserRecord
from core.ontology.link_types import expand_link_types
from core.ontology.mediator import DataMediator

OBJECT_TYPES = {
    "Customer": {
        "storage": {"silo": "p", "table": "customers", "id_column": "customer_id"},
        "id_field": "customer_id", "security": {"field": "region"},
        "fields": {"name": {"type": "data"}, "region": {"type": "data"}},
    },
    "Tag": {
        "storage": {"silo": "p", "table": "tags", "id_column": "tag_id"},
        "id_field": "tag_id", "security": {"field": "region"},
        "fields": {"label": {"type": "data"}, "region": {"type": "data"}},
    },
}
LINK_TYPES = {
    "CustomerTags": {
        "source": {"object_type": "Customer", "api_name": "tags"},
        "target": {"object_type": "Tag", "api_name": "customers"},
        "cardinality": "many_to_many",
        "join_table": {"table": "customer_tags", "source_column": "customer_id",
                        "target_column": "tag_id"},
    },
}


def _mediator(tmp_path, schema, rows):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.executescript(
        "CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, region TEXT);"
        "CREATE TABLE tags (tag_id TEXT PRIMARY KEY, label TEXT, region TEXT);"
        "CREATE TABLE customer_tags (customer_id TEXT, tag_id TEXT);"
        "CREATE TABLE orders (order_id TEXT PRIMARY KEY, customer_id TEXT, region TEXT);"
    )
    for statement, values in rows:
        conn.executemany(statement, values)
    conn.commit()
    conn.close()
    grants = []
    for object_type, type_def in schema.items():
        grants += [f"read:{object_type}"]
        grants += [f"read:{object_type}.{f}" for f in type_def["fields"]]
        grants.append(f"read:{object_type}.{type_def['id_field']}")
    return DataMediator(schema, {"p": SQLiteReadAdapter({"path": source})},
                        {t: "p" for t in schema}, {"r": {"allowed_actions": grants}})


@pytest.fixture
def tagged(tmp_path):
    """One tag in us-west, linked to two us-west customers and -- the
    row that makes the case testable -- one in us-east."""
    schema = expand_link_types(LINK_TYPES, OBJECT_TYPES)
    return _mediator(tmp_path, schema, [
        ("INSERT INTO customers VALUES (?,?,?)",
         [("cust_001", "Ada", "us-west"), ("cust_002", "Bram", "us-west"),
          ("cust_003", "Chidi", "us-east")]),
        ("INSERT INTO tags VALUES (?,?,?)", [("tag_vip", "VIP", "us-west")]),
        ("INSERT INTO customer_tags VALUES (?,?)",
         [("cust_001", "tag_vip"), ("cust_002", "tag_vip"), ("cust_003", "tag_vip")]),
    ])


def _user(region):
    return UserRecord(user_id="u", security_value=region, role_name="r")


class TestTheLeak:
    def test_get_field_does_not_list_a_hidden_object(self, tagged):
        listed = tagged.get_field(_user("us-west"), "Tag", "tag_vip", "customers")

        assert sorted(listed) == ["cust_001", "cust_002"]

    def test_get_object_does_not_either(self, tagged):
        """The path the AGENT reads through."""
        seen = tagged.get_object(_user("us-west"), "Tag", "tag_vip", ["customers"])

        assert sorted(seen["customers"]) == ["cust_001", "cust_002"]

    def test_the_hidden_object_was_always_protected_itself(self, tagged):
        """Which is what made the leak subtle: the OBJECT was hidden
        and its IDENTITY was not."""
        assert tagged.get_object(_user("us-west"), "Customer", "cust_003",
                                  ["name"]) == {"name": None}


class TestEveryPathNowAgrees:
    """link_counts and search_around were already right. The value of
    fixing get_field is that one link can no longer answer a question
    three ways."""

    def test_count_listing_and_traversal_match(self, tagged):
        user = _user("us-west")

        counts = tagged.link_counts(user, "Tag", "tag_vip")["customers"]["count"]
        around = sorted(tagged.search_around(user, "Tag", [], "customers"))
        listed = sorted(tagged.get_field(user, "Tag", "tag_vip", "customers"))

        assert counts == len(around) == len(listed) == 2
        assert around == listed

    def test_a_caller_who_may_see_everything_sees_everything(self, tmp_path):
        """The filter can only ever REMOVE ids. With every customer in
        one region, nothing is taken away."""
        schema = expand_link_types(LINK_TYPES, OBJECT_TYPES)
        mediator = _mediator(tmp_path, schema, [
            ("INSERT INTO customers VALUES (?,?,?)",
             [("c1", "Ada", "us-west"), ("c2", "Bram", "us-west")]),
            ("INSERT INTO tags VALUES (?,?,?)", [("t1", "VIP", "us-west")]),
            ("INSERT INTO customer_tags VALUES (?,?)", [("c1", "t1"), ("c2", "t1")]),
        ])

        listed = mediator.get_field(_user("us-west"), "Tag", "t1", "customers")

        assert sorted(listed) == ["c1", "c2"]

    def test_a_link_with_no_visible_targets_is_empty_not_missing(self, tmp_path):
        schema = expand_link_types(LINK_TYPES, OBJECT_TYPES)
        mediator = _mediator(tmp_path, schema, [
            ("INSERT INTO customers VALUES (?,?,?)", [("c3", "Chidi", "us-east")]),
            ("INSERT INTO tags VALUES (?,?,?)", [("t1", "VIP", "us-west")]),
            ("INSERT INTO customer_tags VALUES (?,?)", [("c3", "t1")]),
        ])

        assert mediator.get_field(_user("us-west"), "Tag", "t1", "customers") == []


class TestItDoesNotCostAReadPerLink:
    """WRITTEN BECAUSE A CONTROL PROVED NOTHING. Deleting the batch
    prefetch left every test passing, because correctness does not
    depend on it -- only cost does, and a link list can be long. A
    security check per linked object would turn one read into N."""

    def test_security_values_are_fetched_in_one_batch(self, tmp_path):
        schema = expand_link_types(LINK_TYPES, OBJECT_TYPES)
        customers = [(f"c{i}", f"n{i}", "us-west") for i in range(25)]
        mediator = _mediator(tmp_path, schema, [
            ("INSERT INTO customers VALUES (?,?,?)", customers),
            ("INSERT INTO tags VALUES (?,?,?)", [("t1", "VIP", "us-west")]),
            ("INSERT INTO customer_tags VALUES (?,?)", [(c[0], "t1") for c in customers]),
        ])
        adapter = mediator.adapters["p"]
        calls = {"n": 0}
        real = adapter.get_raw_field

        def counted(*args, **kwargs):
            calls["n"] += 1
            return real(*args, **kwargs)
        adapter.get_raw_field = counted

        listed = mediator.get_field(_user("us-west"), "Tag", "t1", "customers")

        assert len(listed) == 25
        assert calls["n"] <= 5, (
            f"{calls['n']} single-field reads for 25 linked objects: the batch "
            f"prefetch is not being used")


class TestTheOpenQuestion:
    """A FORWARD SINGLE-VALUED LINK STILL RETURNS ITS TARGET'S ID, and
    that is a decision nobody has made rather than a fix nobody wrote.

    The id is a foreign-key COLUMN of a row the caller may read, so
    withholding it would change what "read this object" means and could
    break legitimate joins. The audit's X1 covers many-valued links
    only. This pins today's behaviour so the question is visible in the
    suite and cannot drift silently while it is decided."""

    def test_today_a_foreign_key_to_a_hidden_object_is_returned(self, tmp_path):
        object_types = {
            **OBJECT_TYPES,
            "Order": {
                "storage": {"silo": "p", "table": "orders", "id_column": "order_id"},
                "id_field": "order_id", "security": {"field": "region"},
                "fields": {"region": {"type": "data"}},
            },
        }
        schema = expand_link_types(
            {"CustomerOrders": {"source": {"object_type": "Customer", "api_name": "orders"},
                                 "target": {"object_type": "Order", "api_name": "customer"},
                                 "cardinality": "one_to_many",
                                 "foreign_key_column": "customer_id"}},
            object_types)
        mediator = _mediator(tmp_path, schema, [
            ("INSERT INTO customers VALUES (?,?,?)", [("cust_003", "Chidi", "us-east")]),
            ("INSERT INTO orders VALUES (?,?,?)", [("o1", "cust_003", "us-west")]),
        ])

        linked = mediator.get_field(_user("us-west"), "Order", "o1", "customer")

        assert linked == "cust_003", "behaviour changed: decide it deliberately"
        assert mediator.get_object(_user("us-west"), "Customer", "cust_003",
                                    ["name"]) == {"name": None}
