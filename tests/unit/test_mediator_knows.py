"""DataMediator.knows: whether a person may know a name exists, by the rule
visible_schema applies -- asked by the removal screen before it names a
blocker, so it must agree with visible_schema on every case.
"""

import pytest

from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator

SCHEMA = {
    "Order": {"storage": {"silo": "s", "table": "orders", "id_column": "order_id"}, "id_field": "order_id",
              "security": {"field": "region"},
              "fields": {"region": {"type": "data"}, "price": {"type": "data"},
                         "lines": {"type": "link", "link_type": "OrderLines", "target": "Line"}}},
    "Line": {"storage": {"silo": "s", "table": "lines", "id_column": "line_id"}, "id_field": "line_id",
             "security": {"field": "region"},
             "fields": {"region": {"type": "data"},
                        "order": {"type": "link", "link_type": "OrderLines", "target": "Order"}}},
    "Memo": {"storage": {"silo": "s", "table": "memos", "id_column": "memo_id"}, "id_field": "memo_id",
             "security": {"field": "region"}, "discoverable": True, "fields": {"region": {"type": "data"}}},
}
USERS = {name: {"org_id": "o", "role": name} for name in ("nobody_role", "types", "price", "reads", "linker")}
ROLES = {
    "nobody_role": {"allowed_actions": []},
    "types": {"allowed_actions": ["discover:Order", "discover:Line"]},
    "price": {"allowed_actions": ["discover:Order", "discover:Order.price"]},
    "reads": {"allowed_actions": ["read:Order", "read:Order.price"]},
    "linker": {"allowed_actions": ["discover:Line", "discover:Line.order"]},
}


@pytest.fixture
def mediator():
    return DataMediator(SCHEMA, {}, {}, ROLES)


def knows(mediator, who, subject):
    return mediator.knows(resolve_user_record(USERS, who, "org_id"), subject)


@pytest.mark.parametrize("who, subject, expected", [
    ("nobody_role", "Order", False),
    ("types", "Order", True),
    ("types", "Order.price", False),
    ("price", "Order.price", True),
    ("price", "Order.region", False),
    ("reads", "Order", True),
    ("reads", "Order.price", True),
    ("price", "Line", False),
    # A field on a type they cannot discover is not known, grant or not.
    ("linker", "Line.order", True),
    ("linker", "Order", False),
    # A type listed to everyone is known to a role with no grants at all, and its fields are not.
    ("nobody_role", "Memo", True),
    ("nobody_role", "Memo.region", False),
    # A name the schema does not have.
    ("types", "Nobody", False),
    ("types", "Order.nope", False),
    ("types", "Nobody.price", False),
    # A link type is known through any one end that is.
    ("linker", "link:OrderLines", True),
    ("price", "link:OrderLines", False),
    ("types", "link:OrderLines", False),
    ("nobody_role", "link:Nope", False),
])
def test_it_answers_as_the_visible_schema_would(mediator, who, subject, expected):
    assert knows(mediator, who, subject) is expected


@pytest.mark.parametrize("who", list(USERS))
def test_every_type_and_field_it_knows_is_in_the_visible_schema_and_no_other(mediator, who):
    record = resolve_user_record(USERS, who, "org_id")
    visible = mediator.visible_schema(record)

    for object_type, definition in SCHEMA.items():
        assert mediator.knows(record, object_type) is (object_type in visible)
        for field in definition["fields"]:
            in_schema = object_type in visible and field in visible[object_type]["fields"]
            assert mediator.knows(record, f"{object_type}.{field}") is in_schema, (who, object_type, field)
