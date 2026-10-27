"""What names a type, a field or a link (core/ontology/used_by.py).

A hand-built schema that uses every kind of reference, which the
fixture configuration does not (it has no rules, derived, enriched or
predicted fields). Each case is one reference and one expected row; the
completeness against the real loader is test_used_by_is_complete.py.
"""

from types import SimpleNamespace

from core.ontology.used_by import used_by_field, used_by_link, used_by_type
from core.saved_views import SavedView


def _schema() -> dict:
    return {
        "Order": {
            "id_field": "order_id", "title_field": "label",
            "security": {"field": "region"},
            "fields": {
                "label": {"type": "data"}, "region": {"type": "data"},
                "price": {"type": "data", "data_type": "number"},
                "cost": {"type": "data", "data_type": "number"},
                "margin": {"type": "data", "derived": {"subtract": ["price", "cost"]}},
                "mood": {"type": "data", "enrich": {"from": "label", "instruction": "x",
                                                    "choices": ["a", "b"]}},
                "late": {"type": "data", "data_type": "boolean",
                         "predict": {"of": "label", "from": ["price"]}},
                "lines": {"type": "link", "link_type": "OrderLines", "target": "Line"},
            },
            "rules": {"price_over_cost": {"field": "price", "op": ">=", "other": "cost"}},
            "dependencies": {"label_fixes_region": {"determinant": "label", "dependent": "region"}},
            "unusual": {"numbers": ["price"], "within": []},
        },
        "Line": {
            "id_field": "line_id", "security": {"via_field": "order"},
            "fields": {"order": {"type": "link", "link_type": "OrderLines", "target": "Order"}},
        },
    }


ROLES = {"clerk": {"allowed_actions": ["read:Order", "read:Order.price", "execute:Fix"]},
         "boss": {"allowed_actions": ["manage:users", "read:label:pii"]}}
ACTIONS = {"Fix": {"affected_object_types": ["Order"],
                   "sub_writes": [{"object_type": "Order", "operation": "update",
                                   "mutations": [{"set": {"property": "price", "value": "parameter.p"}}],
                                   "submission_criteria": [{"check": "current_state", "field": "cost",
                                                            "operator": "equals", "value": 1}]}]}}


def _trigger(conditions):
    view = SavedView("v", "v", "Order", "", conditions, {}, "now")
    return SimpleNamespace(name="watch", views_by_id={"v": view})


def _rows(found):
    return {(item.kind, item.place) for item in found}


def test_a_field_lists_each_block_that_reads_it():
    found = used_by_field(_schema(), ROLES, ACTIONS, [_trigger([{"field": "price"}])], "Order", "price")
    assert _rows(found) == {
        ("grant", "role clerk"), ("derived", "type Order, field margin"),
        ("rule", "type Order, rule price_over_cost"), ("predicted", "type Order, field late"),
        ("unusual", "type Order, unusual-records check"), ("action", "action Fix"),
        ("trigger", "trigger watch"),
    }


def test_the_identifier_title_and_row_rule_are_named_for_what_they_are():
    assert ("title", "type Order") in _rows(used_by_field(_schema(), {}, {}, [], "Order", "label"))
    assert ("identifier", "type Order") in _rows(used_by_field(_schema(), {}, {}, [], "Order", "order_id"))
    found = used_by_field(_schema(), {}, {}, [], "Order", "region")
    assert ("security", "type Order, row rule") in _rows(found)


def test_other_types_that_borrow_a_row_rule_are_listed_with_what_they_borrow():
    schema = _schema()
    found = used_by_field(schema, {}, {}, [], "Order", "region")
    assert ("security", "Line row rule") in _rows(found)
    assert [item for item in found if item.place == "Line row rule"][0].says.endswith("Order.region")
    assert ("security", "Line row rule") in _rows(used_by_type(schema, {}, {}, [], "Order"))


def test_enriched_and_dependency_inputs_are_found():
    found = used_by_field(_schema(), {}, {}, [], "Order", "label")
    assert {("enriched", "type Order, field mood"), ("dependency", "type Order, dependency label_fixes_region"),
            ("predicted", "type Order, field late")} <= _rows(found)


def test_an_action_is_found_by_the_field_it_sets_and_the_field_its_criteria_read():
    assert ("action", "action Fix") in _rows(used_by_field(_schema(), {}, ACTIONS, [], "Order", "price"))
    assert ("action", "action Fix") in _rows(used_by_field(_schema(), {}, ACTIONS, [], "Order", "cost"))
    assert not used_by_field(_schema(), {}, ACTIONS, [], "Order", "mood")


def test_a_type_lists_grants_links_actions_and_triggers_but_not_its_own_blocks():
    found = used_by_type(_schema(), ROLES, ACTIONS, [_trigger([])], "Order")
    assert _rows(found) == {("grant", "role clerk"), ("link", "link OrderLines"),
                            ("action", "action Fix"), ("trigger", "trigger watch"),
                            ("security", "Line row rule")}


def test_a_role_is_one_row_however_many_grants_it_has():
    found = [item for item in used_by_type(_schema(), ROLES, {}, [], "Order") if item.kind == "grant"]
    assert len(found) == 1 and "2 grants" in found[0].says


def test_label_grants_and_unrelated_grants_are_not_references():
    assert not [item for item in used_by_type(_schema(), ROLES, {}, [], "Order") if item.place == "role boss"]


def test_a_link_lists_what_names_either_end():
    found = used_by_link(_schema(), {"r": {"allowed_actions": ["read:Order.lines"]}}, {}, [], "OrderLines")
    assert {("grant", "role r"), ("security", "type Line, row rule")} <= _rows(found)
    assert not [item for item in found if item.kind == "link"]


def test_a_link_end_says_it_belongs_to_a_link():
    found = used_by_field(_schema(), {}, {}, [], "Order", "lines")
    assert ("link", "link OrderLines") in _rows(found)


def test_inherited_security_names_the_silo_it_came_from():
    schema = _schema()
    schema["Order"]["security_inherited_from"] = "main"
    found = used_by_field(schema, {}, {}, [], "Order", "region")
    own = [item for item in found if item.place == "type Order, row rule"][0]
    assert "inherited from silo main" in own.says
