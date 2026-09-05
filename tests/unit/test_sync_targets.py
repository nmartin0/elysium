"""
Tests for core/mirror/sync_targets.py -- working out WHAT to sync from
the ontology alone.

The properties under test are the ones that would silently produce a
WRONG mirror rather than an obviously broken one: a missing MDO table,
a missing security column, a column-name override ignored, or a
reverse-link field mistakenly treated as a real column on the wrong
table. Each of those would leave the sync itself reporting success
while the mirror quietly failed to serve some real query later.
"""

import pytest

from core.mirror.sync_targets import resolve_sync_targets


def _targets_by_table(schema):
    return {(t.silo_name, t.table_name): t for t in resolve_sync_targets(schema)}


def test_a_simple_type_yields_one_target_with_its_own_columns():
    schema = {
        "object_types": {
            "Widget": {
                "storage": {"silo": "primary", "table": "widgets", "id_column": "widget_id"},
                "id_field": "widget_id",
                "fields": {"name": {"type": "data"}, "colour": {"type": "data"}},
            }
        }
    }
    targets = resolve_sync_targets(schema)

    assert len(targets) == 1
    assert targets[0].silo_name == "primary"
    assert targets[0].table_name == "widgets"
    assert targets[0].id_column == "widget_id"
    # The id column is always included -- rows are matched on it.
    assert set(targets[0].columns) == {"widget_id", "name", "colour"}


def test_additional_storage_becomes_its_own_separate_target():
    # THE MDO case: a type whose fields span two genuinely different
    # tables, in two different silos. Missing this would leave the
    # risk_score field unservable from the mirror.
    schema = {
        "object_types": {
            "Customer": {
                "storage": {"silo": "primary", "table": "customers", "id_column": "customer_id"},
                "additional_storage": {
                    "risk_db": {"silo": "risk", "table": "customer_risk", "id_column": "cust_ref"}
                },
                "id_field": "customer_id",
                "fields": {
                    "name": {"type": "data"},
                    "risk_score": {"type": "data", "storage": "risk_db", "column": "score_val"},
                },
            }
        }
    }
    by_table = _targets_by_table(schema)

    assert set(by_table) == {("primary", "customers"), ("risk", "customer_risk")}
    # The MDO field belongs to the MDO table, NOT the primary one.
    assert "score_val" not in by_table[("primary", "customers")].columns
    assert "score_val" in by_table[("risk", "customer_risk")].columns


def test_a_column_override_syncs_the_real_column_name_not_the_field_name():
    # `risk_score` is the ontology's name; `score_val` is what actually
    # exists in the database. Syncing the field name would fail at read
    # time with a confusing "no such column".
    schema = {
        "object_types": {
            "Customer": {
                "storage": {"silo": "primary", "table": "customers", "id_column": "customer_id"},
                "id_field": "customer_id",
                "fields": {"risk_score": {"type": "data", "column": "score_val"}},
            }
        }
    }
    columns = resolve_sync_targets(schema)[0].columns

    assert "score_val" in columns
    assert "risk_score" not in columns


def test_a_reverse_link_field_is_not_treated_as_a_column():
    # Customer.transactions lives in the TRANSACTIONS table, not in
    # customers -- including it here would try to sync a column that
    # doesn't exist on this table at all.
    schema = {
        "object_types": {
            "Customer": {
                "storage": {"silo": "primary", "table": "customers", "id_column": "customer_id"},
                "id_field": "customer_id",
                "fields": {
                    "name": {"type": "data"},
                    "transactions": {
                        "type": "link",
                        "target": "Transaction",
                        "cardinality": "many",
                        "via_table": "transactions",
                        "via_column": "customer_id",
                    },
                },
            }
        }
    }
    columns = resolve_sync_targets(schema)[0].columns

    assert "transactions" not in columns
    assert set(columns) == {"customer_id", "name"}


def test_a_forward_link_field_IS_a_real_column_and_is_included():
    # Transaction.customer_id genuinely is a column on the transactions
    # table -- distinguished from a reverse link by having no
    # via_table, not by its cardinality.
    schema = {
        "object_types": {
            "Transaction": {
                "storage": {"silo": "primary", "table": "transactions", "id_column": "transaction_id"},
                "id_field": "transaction_id",
                "fields": {
                    "amount": {"type": "data"},
                    "customer_id": {"type": "link", "target": "Customer", "cardinality": "one"},
                },
            }
        }
    }
    columns = resolve_sync_targets(schema)[0].columns

    assert "customer_id" in columns


def test_the_security_field_is_always_included():
    # MAC reads this on EVERY access check -- a mirror missing it would
    # make every object of this type unreadable.
    schema = {
        "object_types": {
            "Customer": {
                "storage": {"silo": "primary", "table": "customers", "id_column": "customer_id"},
                "id_field": "customer_id",
                "security": {"field": "region"},
                "fields": {"region": {"type": "data"}, "name": {"type": "data"}},
            }
        }
    }
    assert "region" in resolve_sync_targets(schema)[0].columns


def test_a_via_field_security_chain_needs_no_special_handling():
    # `security: {via_field: customer_id}` names a link field that is
    # already included as an ordinary column -- it must not crash, and
    # must not invent a "via_field" column.
    schema = {
        "object_types": {
            "Transaction": {
                "storage": {"silo": "primary", "table": "transactions", "id_column": "transaction_id"},
                "id_field": "transaction_id",
                "security": {"via_field": "customer_id"},
                "fields": {"customer_id": {"type": "link", "target": "Customer", "cardinality": "one"}},
            }
        }
    }
    columns = resolve_sync_targets(schema)[0].columns

    assert "customer_id" in columns
    assert "via_field" not in columns


def test_two_types_sharing_one_table_produce_one_target_with_united_columns():
    # A real possibility, and syncing the table twice -- or with only
    # the second type's columns -- would be a silent correctness bug.
    schema = {
        "object_types": {
            "A": {
                "storage": {"silo": "primary", "table": "shared", "id_column": "id"},
                "id_field": "id",
                "fields": {"alpha": {"type": "data"}},
            },
            "B": {
                "storage": {"silo": "primary", "table": "shared", "id_column": "id"},
                "id_field": "id",
                "fields": {"beta": {"type": "data"}},
            },
        }
    }
    targets = resolve_sync_targets(schema)

    assert len(targets) == 1
    assert set(targets[0].columns) == {"id", "alpha", "beta"}


def test_a_field_referencing_an_unknown_storage_fails_loudly():
    # "Fail loudly, never silently substitute" -- a typo'd storage key
    # must not quietly drop that field from the mirror.
    schema = {
        "object_types": {
            "Customer": {
                "storage": {"silo": "primary", "table": "customers", "id_column": "customer_id"},
                "id_field": "customer_id",
                "fields": {"risk_score": {"type": "data", "storage": "nonexistent_storage"}},
            }
        }
    }
    with pytest.raises(ValueError, match="unknown storage"):
        resolve_sync_targets(schema)


def test_the_real_fixture_ontology_resolves_to_its_five_real_tables():
    # A real, end-to-end check against the actual fixture schema rather
    # than only synthetic ones -- confirms the resolver handles a real
    # ontology, MDO and all.
    import yaml

    schema = yaml.safe_load(open("tests/integration/fixtures/ontology_schema.yaml"))
    by_table = _targets_by_table({"object_types": schema["object_types"]})

    assert set(by_table) == {
        ("primary_sql", "customers"),
        ("primary_sql", "transactions"),
        ("primary_sql", "accounts"),
        ("risk_sql", "customer_risk"),
        ("support_crm", "tickets"),
    }
    # The real MDO column override, resolved correctly.
    assert "score_val" in by_table[("risk_sql", "customer_risk")].columns
