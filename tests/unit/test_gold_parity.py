"""
The same answers from gold as from the source (GOLD-3).

THE CLAIM THIS EXISTS TO MEASURE: pointing the ontology at gold
changes where rows come from and NOTHING a caller can observe. Two
mediators are built over one dataset -- one on the source-shaped
schema reading the mirror, one on the GOLD VIEW reading the gold
connector -- and every read the mediator offers is compared.

WHY IT IS WORTH THE TROUBLE. The gold view rebinds storage, drops
column overrides and re-keys reverse links; the connector reads a
different namespace with a different shape. Each of those is a place
to be subtly wrong in a way that no unit test of either part would
catch, because both parts would be internally consistent and WRONG
TOGETHER. Only the comparison catches that.

MAC AND RBAC ARE INCLUDED ON PURPOSE. Security is resolved by the
mediator from values in the rows, so it has to survive the rebinding
too -- and the pushdown guard (test_security_pushdown_guard.py) is
exactly the machinery that changes meaning under gold.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.filters import FieldFilter
from core.intermediate_layer.audit import AuditLog
from core.intermediate_layer.auth import UserRecord
from core.mirror.gold import build_gold
from core.mirror.gold_connector import GoldConnector
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.mirror_adapter import MirrorReadAdapter
from core.ontology.gold_view import build_gold_view
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLogWriter

SCHEMA = {
    "Customer": {
        "id_field": "customer_id",
        "security": {"field": "region"},
        "storage": {"silo": "p", "table": "customers", "id_column": "cust_pk"},
        "fields": {
            "customer_id": {"type": "data", "column": "cust_pk"},
            "region": {"type": "data"},
            "name": {"type": "data"},
            "transactions": {"type": "link", "target": "Transaction", "cardinality": "many",
                              "via_table": "txns", "via_column": "cust_fk"},
        },
    },
    "Transaction": {
        "id_field": "transaction_id",
        "security": {"via_field": "customer_id"},
        "storage": {"silo": "p", "table": "txns", "id_column": "txn_pk"},
        "fields": {
            "transaction_id": {"type": "data", "column": "txn_pk"},
            "amount": {"type": "data", "data_type": "decimal"},
            "category": {"type": "data"},
            "customer_id": {"type": "link", "target": "Customer", "cardinality": "one",
                             "column": "cust_fk"},
        },
    },
}

ROLES = {
    "analyst": {"allowed_actions": [
        "read:Customer", "read:Customer.customer_id", "read:Customer.region",
        "read:Customer.name", "read:Customer.transactions",
        "read:Transaction", "read:Transaction.transaction_id", "read:Transaction.amount",
        "read:Transaction.category", "read:Transaction.customer_id",
    ]},
    "narrow": {"allowed_actions": [
        "read:Customer", "read:Customer.customer_id", "read:Customer.name",
    ]},
}

WEST = UserRecord("u_west", "us-west", "analyst")
EAST = UserRecord("u_east", "us-east", "analyst")
NARROW = UserRecord("u_narrow", "us-west", "narrow")
NO_CLEARANCE = UserRecord("u_none", None, "analyst")
USERS = [WEST, EAST, NARROW, NO_CLEARANCE]

ROWS = [
    ("c1", "us-west", "Ada Okafor"),
    ("c2", "us-east", "Ben Carter"),
    ("c3", "us-west", "Cleo Nkemdirim"),
    ("c4", "eu-west", "Dmitri Alvarez"),
]
TXNS = [
    ("t1", "49.99", "subscription", "c1"),
    ("t2", "120.50", "hardware", "c1"),
    ("t3", "8.25", "subscription", "c2"),
    ("t4", "49.99", "hardware", "c3"),
    ("t5", "1284.00", "services", "c4"),
]


@pytest.fixture
def both(tmp_path, isolated_audit_log):
    """One dataset, two mediators: source-shaped and gold-shaped."""
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE customers (cust_pk TEXT PRIMARY KEY, region TEXT, name TEXT)")
    conn.executemany("INSERT INTO customers VALUES (?,?,?)", ROWS)
    conn.execute("CREATE TABLE txns (txn_pk TEXT PRIMARY KEY, amount TEXT, "
                 "category TEXT, cust_fk TEXT)")
    conn.executemany("INSERT INTO txns VALUES (?,?,?,?)", TXNS)
    conn.commit()
    conn.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": source})})
    sync.sync_table("p", "customers", "cust_pk", ["cust_pk", "region", "name"],
                    dict.fromkeys(["cust_pk", "region", "name"], "string"))
    sync.sync_table("p", "txns", "txn_pk", ["txn_pk", "amount", "category", "cust_fk"],
                    {"txn_pk": "string", "amount": "decimal", "category": "string",
                     "cust_fk": "string"})
    for object_type, type_def in SCHEMA.items():
        silver = sync._catalog.load_table(
            f"p.{type_def['storage']['table']}").scan().to_arrow().to_pylist()
        assert build_gold(sync._catalog, object_type, type_def, silver).published

    def _mediator(schema, adapters, silo_for_type, name):
        return DataMediator(schema, adapters, silo_for_type, ROLES,
                             write_log=WriteLogWriter(tmp_path / f"{name}.db"),
                             audit_log=AuditLog(isolated_audit_log / f"{name}.log"))

    from_source = _mediator(SCHEMA, {"p": MirrorReadAdapter(sync._catalog, "p")},
                             {"Customer": "p", "Transaction": "p"}, "source")
    view, excluded = build_gold_view(SCHEMA)
    assert excluded == {}
    from_gold = _mediator(view, {"gold": GoldConnector(sync._catalog)},
                           {"Customer": "gold", "Transaction": "gold"}, "gold")
    return from_source, from_gold


BINDING_KEYS = frozenset({"column", "storage", "via_table", "via_column",
                           "via_target_column"})


def _without_binding(outcome):
    """An outcome's schema with the where-it-lives facts removed."""
    if outcome[0] != "returned":
        return outcome
    return ("returned", {
        object_type: {
            key: ({field_name: {k: v for k, v in field_info.items()
                                if k not in BINDING_KEYS}
                   for field_name, field_info in value.items()}
                  if key == "fields" else value)
            for key, value in type_def.items()
        }
        for object_type, type_def in outcome[1].items()
    })


def _sorted(outcome):
    """An outcome with any id list put in a stable order."""
    if outcome[0] == "returned" and isinstance(outcome[1], list):
        return ("returned", sorted(outcome[1], key=repr))
    return outcome


def _outcome(mediator, method, *args, **kwargs):
    """What one read did -- its answer, or the refusal it raised.

    REFUSALS ARE PART OF PARITY. A read that is declined for one
    binding and allowed for the other is exactly the divergence this
    file exists to catch, and comparing only successful answers would
    let it through -- which it nearly did: the narrow role's filter
    raised in both paths and the test simply blew up.
    """
    try:
        return ("returned", getattr(mediator, method)(*args, **kwargs))
    except Exception as refusal:  # noqa: BLE001 - the refusal IS the answer here
        return ("raised", type(refusal).__name__, str(refusal))


def _both(both, method, *args, **kwargs):
    """Run one read on both mediators and return the pair."""
    source, gold = both
    return (_outcome(source, method, *args, **kwargs),
            _outcome(gold, method, *args, **kwargs))


class TestSearch:
    @pytest.mark.parametrize("user", USERS, ids=lambda u: u.user_id)
    def test_every_customer_a_user_can_see(self, both, user):
        a, b = _both(both, "search_object", user, "Customer", [])

        assert _sorted(a) == _sorted(b)

    @pytest.mark.parametrize("user", USERS, ids=lambda u: u.user_id)
    def test_filtered_by_a_property(self, both, user):
        conditions = [FieldFilter("region", "equals", "us-west")]

        a, b = _both(both, "search_object", user, "Customer", conditions)

        assert _sorted(a) == _sorted(b)

    def test_filtered_by_a_decimal(self, both):
        """F-20's territory: the literal has to be quantised the same
        way against gold's column as against silver's."""
        conditions = [FieldFilter("amount", "equals", "49.99")]

        a, b = _both(both, "search_object", WEST, "Transaction", conditions)

        assert _sorted(a) == _sorted(b)

    def test_filtered_by_in(self, both):
        conditions = [FieldFilter("category", "in", ["hardware", "services"])]

        a, b = _both(both, "search_object", WEST, "Transaction", conditions)

        assert _sorted(a) == _sorted(b)

    def test_free_text(self, both):
        a, b = _both(both, "search_object_free_text", WEST, "Customer", "okafor")

        assert _sorted(a) == _sorted(b)

    @pytest.mark.parametrize("user", USERS, ids=lambda u: u.user_id)
    def test_count(self, both, user):
        a, b = _both(both, "count_objects", user, "Customer", [])

        assert a == b


class TestReadingOneObject:
    @pytest.mark.parametrize("object_id", [row[0] for row in ROWS])
    def test_get_object_field_for_field(self, both, object_id):
        a, b = _both(both, "get_object", WEST, "Customer", object_id,
                     ["customer_id", "region", "name"])

        assert a == b

    @pytest.mark.parametrize("user", USERS, ids=lambda u: u.user_id)
    def test_get_field_including_what_is_refused(self, both, user):
        a, b = _both(both, "get_field", user, "Customer", "c1", "name")

        assert a == b

    def test_a_field_the_role_cannot_read(self, both):
        a, b = _both(both, "get_field", NARROW, "Customer", "c1", "region")

        assert a == b

    def test_an_object_that_does_not_exist(self, both):
        a, b = _both(both, "get_object", WEST, "Customer", "nobody", ["name"])

        assert a == b


class TestLinks:
    @pytest.mark.parametrize("user", [WEST, EAST], ids=lambda u: u.user_id)
    def test_search_around_a_reverse_link(self, both, user):
        """THE RE-KEYED PATH: gold follows the link through the
        target's gold table, keyed by the target's property."""
        a, b = _both(both, "search_around", user, "Customer", [], "transactions")

        assert _sorted(a) == _sorted(b)

    def test_search_around_a_forward_link(self, both):
        a, b = _both(both, "search_around", WEST, "Transaction", [], "customer_id")

        assert _sorted(a) == _sorted(b)

    @pytest.mark.parametrize("object_id", ["c1", "c2", "c3"])
    def test_link_counts(self, both, object_id):
        a, b = _both(both, "link_counts", WEST, "Customer", object_id)

        assert a == b

    def test_reading_a_link_field(self, both):
        a, b = _both(both, "get_field", WEST, "Customer", "c1", "transactions")

        assert a == b


class TestAggregates:
    def test_count_grouped_by_a_property(self, both):
        a, b = _both(both, "aggregate_by_field", WEST, "Transaction", [], "category", "count")

        assert a == b

    def test_sum_of_a_decimal(self, both):
        a, b = _both(both, "aggregate_by_field", WEST, "Transaction", [],
                     None, "sum", "amount")

        assert a == b

    @pytest.mark.parametrize("user", USERS, ids=lambda u: u.user_id)
    def test_an_aggregate_respects_what_each_user_may_see(self, both, user):
        a, b = _both(both, "aggregate_by_field", user, "Transaction", [], "category", "count")

        assert a == b


class TestTheSchemaItself:
    @pytest.mark.parametrize("user", USERS, ids=lambda u: u.user_id)
    def test_visible_schema_is_identical_apart_from_the_binding(self, both, user):
        """What a person is told EXISTS must not change with the
        binding: the same types, the same fields, the same kinds.

        THE BINDING ITSELF DIFFERS BY DESIGN -- `column`, `via_table`
        and `storage` name where a field lives, and that is the whole
        point of the gold view. They are compared out here.

        AND THEY ARE STILL IN THE DICT, which is worth knowing: an
        attempt to strip them at the source broke 27 integration tests,
        because visible_schema is fed BACK INTO the mediator and those
        keys are what group fields by storage. The agent being handed
        the customer's column names is therefore a separate piece of
        work with its own blast radius, recorded rather than smuggled
        in here.
        """
        a, b = _both(both, "visible_schema", user)

        assert _without_binding(a) == _without_binding(b)
