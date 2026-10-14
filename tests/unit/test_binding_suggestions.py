"""
Which fields a new source table's columns probably are (R55).

Two signals kept apart -- name and values -- and an id detector. Checked
end to end against the dev deployment too: pointed at risk_sql's
customer_risk table it reconstructs the binding the deployment already
declares (cust_ref is the Customer id, score_val is risk_score).
"""

import yaml

from core.mirror.binding_suggestions import suggest, yaml_skeleton

SCHEMA = {
    "Customer": {
        "id_field": "customer_id",
        "fields": {
            "email": {"type": "data"},
            "postcode": {"type": "data", "display_name": "Post code"},
            "orders": {"type": "link", "target": "Order", "cardinality": "many"},
        },
    },
    "Order": {"id_field": "order_id", "fields": {"total": {"type": "data"}}},
}
GOLD = {
    "Customer": [{"customer_id": f"c{n}", "email": f"u{n}@x.org", "postcode": f"AB{n}"}
                 for n in range(20)],
    "Order": [{"order_id": f"o{n}", "total": str(n)} for n in range(20)],
}


def _run(rows, only_type=None):
    return suggest(SCHEMA, rows, GOLD.get, only_type)


def test_values_find_a_field_whatever_the_column_is_called():
    by_column, _ = _run([{"contact_mail": f"u{n}@x.org"} for n in range(10)])

    best = by_column["contact_mail"][0]
    assert (best.object_type, best.field, best.value_share) == ("Customer", "email", 1.0)


def test_a_name_alone_is_reported_with_no_values_to_back_it():
    by_column, _ = _run([{"post_code": f"ZZ{n}"} for n in range(5)])

    best = by_column["post_code"][0]
    assert (best.field, best.value_share) == ("postcode", 0.0)
    assert best.name_score >= 0.6


def test_the_id_column_is_recognised():
    _, ids = _run([{"cust_ref": f"c{n}"} for n in range(10)])

    assert [(m.column, m.object_type, m.share) for m in ids] == [("cust_ref", "Customer", 1.0)]


def test_a_column_matching_nothing_gets_nothing():
    """THE CONTROL: unrelated names and values are not dressed up."""
    by_column, ids = _run([{"zzz": "q"}])

    assert by_column["zzz"] == [] and ids == []


def test_a_link_field_is_not_offered():
    by_column, _ = _run([{"orders": "x"}])

    assert all(m.field != "orders" for m in by_column["orders"])


def test_only_type_narrows_the_comparison():
    by_column, _ = _run([{"total": "3"}], only_type="Customer")

    assert all(m.object_type == "Customer" for m in by_column["total"])


def test_the_skeleton_is_valid_yaml_of_the_declared_shape():
    text = yaml_skeleton("Customer", "crm", "crm_sql", "contacts", "cust_ref",
                         {"email": "contact_mail"})

    parsed = yaml.safe_load(text)["object_types"]["Customer"]
    assert parsed["additional_storage"]["crm"] == {"silo": "crm_sql", "table": "contacts",
                                                   "id_column": "cust_ref"}
    assert parsed["fields"]["email"] == {"storage": "crm", "column": "contact_mail"}
