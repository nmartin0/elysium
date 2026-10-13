"""Rules between two fields of one object (R29), core/ontology/field_rules.py.

The precedent is the column-pair expectation -- Great Expectations'
`expect_column_pair_values_A_to_be_greater_than_B` -- checked per row.
Here at two points: a WRITE is refused, and SILVER applies the declared
policy to what a source holds.
"""

import datetime
import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.sync_targets import resolve_sync_targets
from core.ontology.field_rules import rule_violation, rules_for, validate_field_rules

BOOKING = {
    "id_field": "id",
    "storage": {"silo": "s", "table": "bookings", "id_column": "id"},
    "fields": {
        "id": {"type": "data"},
        "start": {"type": "data", "data_type": "date"},
        "end": {"type": "data", "data_type": "date"},
        "note": {"type": "data"},
        "price": {"type": "data", "data_type": "decimal"},
        "discount": {"type": "data", "data_type": "integer"},
    },
    "rules": {"ends_after_start": {"field": "end", "op": ">=", "other": "start",
                                   "on_violation": "quarantine"}},
}


def _with(rule):
    return {"Booking": {**BOOKING, "rules": {"r": rule}}}


class TestTheRule:
    def test_it_holds_and_it_breaks(self):
        (rule,) = rules_for(BOOKING)

        assert rule_violation(rule, BOOKING, {"start": "2024-01-01", "end": "2024-01-02"}) is None
        assert "ends_after_start" in rule_violation(
            rule, BOOKING, {"start": "2024-01-02", "end": "2024-01-01"})

    def test_a_null_on_either_side_is_not_a_violation(self):
        """An absent end date is not an end before the start."""
        (rule,) = rules_for(BOOKING)

        assert rule_violation(rule, BOOKING, {"start": "2024-01-02", "end": None}) is None

    def test_numbers_of_different_kinds_compare(self):
        schema = _with({"field": "discount", "op": "<=", "other": "price"})["Booking"]
        (rule,) = rules_for(schema)

        assert rule_violation(rule, schema, {"discount": 5, "price": "9.99"}) is None
        assert rule_violation(rule, schema, {"discount": 10, "price": "9.99"}) is not None


class TestRefusedAtLoad:
    @pytest.mark.parametrize("rule, says", [
        ({"field": "nope", "op": "<", "other": "start"}, "does not have"),
        ({"field": "end", "op": "=>", "other": "start"}, "op"),
        ({"field": "end", "op": "<", "other": "end"}, "itself"),
        ({"field": "end", "op": "<", "other": "note"}, "compares a date with a string"),
        ({"field": "note", "op": "<", "other": "id"}, "does not apply to string"),
        ({"field": "end", "op": "<", "other": "start", "on_violation": "drop"}, "on_violation"),
        ({"field": "end", "op": "<", "other": "start", "when": "always"}, "unknown key"),
    ])
    def test_a_rule_that_could_never_be_checked(self, rule, says):
        with pytest.raises(ValueError, match=says):
            validate_field_rules(_with(rule))

    def test_two_storages_have_no_single_row(self):
        schema = _with({"field": "end", "op": ">=", "other": "start"})
        schema["Booking"] = {**schema["Booking"], "fields": {
            **BOOKING["fields"], "end": {"type": "data", "data_type": "date", "storage": "other"}}}

        with pytest.raises(ValueError, match="different storages"):
            validate_field_rules(schema)

    def test_equality_on_text_is_fine(self):
        validate_field_rules(_with({"field": "note", "op": "!=", "other": "id"}))


class TestInSilver:
    def _sync(self, tmp_path, policy):
        source = tmp_path / "s.db"
        conn = sqlite3.connect(source)
        conn.execute('CREATE TABLE bookings (id TEXT PRIMARY KEY, start TEXT, "end" TEXT, '
                     'note TEXT, price TEXT, discount TEXT)')
        conn.executemany("INSERT INTO bookings VALUES (?, ?, ?, NULL, NULL, NULL)", [
            ("good", "2024-01-01", "2024-01-05"),
            ("backwards", "2024-01-05", "2024-01-01"),
        ])
        conn.commit()
        conn.close()
        schema = {"Booking": {**BOOKING, "rules": {"ends_after_start": {
            **BOOKING["rules"]["ends_after_start"], "on_violation": policy}}}}
        (target,) = resolve_sync_targets({"object_types": schema})
        sync = IcebergMirrorSync(tmp_path / "mirror", {"s": SQLiteReadAdapter({"path": source})})
        sync.sync_table("s", "bookings", "id", target.columns, target.column_types,
                        target.fields_by_column, target.standardisation, target.expectations)
        return sync

    def test_quarantine_holds_the_row_and_names_the_rule(self, tmp_path):
        sync = self._sync(tmp_path, "quarantine")

        kept = {row["id"] for row in sync._catalog.load_table("s.bookings").scan().to_arrow().to_pylist()}
        (held,) = sync._catalog.load_table("quarantine_s.bookings").scan().to_arrow().to_pylist()
        assert kept == {"good"}
        assert held["object_id"] == "backwards"
        assert held["field"] == "ends_after_start"

    def test_warn_keeps_the_row(self, tmp_path):
        """THE CONTROL: the default policy reports and keeps."""
        sync = self._sync(tmp_path, "warn")

        rows = sync._catalog.load_table("s.bookings").scan().to_arrow().to_pylist()
        assert {row["id"] for row in rows} == {"good", "backwards"}
        assert next(r for r in rows if r["id"] == "good")["end"] == datetime.date(2024, 1, 5)


class TestOnAWrite:
    """Through the real write mediator of the shipped deployment, with a
    rule added: a transaction's category may not equal its currency. The
    action changes ONLY the category, so the check must read the current
    currency itself."""

    @pytest.fixture
    def writes(self, synced_deployment):
        from core.deployment_loader import build_generation
        from core.intermediate_layer.auth import resolve_user_record

        schema = synced_deployment.config_dir / "ontology_schema.yaml"
        text = schema.read_text()
        # ASSERTED, NOT ASSUMED: the first version's anchor did not match
        # the file, inserted nothing, and the "proposed" test below passed
        # against a deployment with no rule at all.
        assert text.count("\n  Transaction:\n") == 1
        schema.write_text(text.replace(
            "\n  Transaction:\n",
            "\n  Transaction:\n    rules:\n"
            "      category_is_not_a_currency:\n        field: category\n"
            "        op: \"!=\"\n        other: currency\n", 1))
        generation = build_generation(synced_deployment.config_dir, synced_deployment.data_dir,
                                      synced_deployment.log_dir)
        user = resolve_user_record(generation.config.users, "user_alice",
                                   generation.config.security_attribute)
        assert "rules" in generation.config.schema["Transaction"]
        return generation.write_mediator, user

    def test_a_change_that_breaks_it_against_the_current_value_is_refused(self, writes):
        from core.ontology.write_mediator import ConstraintViolation

        mediator, user = writes
        with pytest.raises(ConstraintViolation, match="category_is_not_a_currency"):
            mediator.propose_action(user, "RecategorizeTransactions",
                                    {"transaction_ids": [1], "new_category": "USD"}, "human")

    def test_a_change_that_keeps_it_is_proposed(self, writes):
        mediator, user = writes

        pending = mediator.propose_action(user, "RecategorizeTransactions",
                                          {"transaction_ids": [1], "new_category": "software"},
                                          "human")

        assert pending.sub_writes
