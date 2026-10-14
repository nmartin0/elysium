"""
Cleaning-rule suggestions a person accepts or dismisses (R31).

THE OWNER'S SHAPE (14 Oct): a review queue; the YAML stays the only
source of rules. What this must get right:
  - a dismissal is remembered, so a judged "N/A" never comes back;
  - once the schema declares a rule, its suggestion reads DECLARED;
  - findings are named by the TYPE and FIELD a rule is declared on.
"""

import contextlib
import io
import sqlite3

import pytest

from core.rule_suggestions import (
    ABSENCE,
    ACCEPTED,
    DECLARED,
    DISMISSED,
    PENDING,
    RuleSuggestionStore,
    suggestion_id,
)


def _finding(value="N/A", seen=3):
    return {"object_type": "Customer", "field": "email", "kind": ABSENCE, "value": value,
            "seen": seen, "why": "a word meaning 'no value'", "examples": [value]}


@pytest.fixture
def store(tmp_path):
    return RuleSuggestionStore(tmp_path / "rule_suggestions.db")


def _state(store, value="N/A"):
    return {item.value: item.state for item in store.all()}[value]


class TestTheQueue:
    def test_a_finding_arrives_pending(self, store):
        assert store.record_scan([_finding()], set()) ["new"] == 1
        assert _state(store) == PENDING

    def test_a_dismissal_survives_the_next_scan(self, store):
        """THE MEMORY THIS EXISTS FOR."""
        store.record_scan([_finding()], set())
        store.decide(suggestion_id("Customer", "email", ABSENCE, "N/A"), DISMISSED, "ann")

        outcome = store.record_scan([_finding(seen=9)], set())

        assert outcome["kept_dismissed"] == 1
        assert _state(store) == DISMISSED

    def test_a_pending_one_is_refreshed(self, store):
        """THE CONTROL: only a dismissal is frozen."""
        store.record_scan([_finding(seen=3)], set())
        store.record_scan([_finding(seen=9)], set())

        assert [item.seen for item in store.all()] == [9]

    def test_accepted_then_declared_reads_declared(self, store):
        sid = suggestion_id("Customer", "email", ABSENCE, "N/A")
        store.record_scan([_finding()], set())
        store.decide(sid, ACCEPTED, "ann")

        store.record_scan([_finding()], {sid})

        assert _state(store) == DECLARED
        assert store.decide(sid, DISMISSED, "ann") is False   # settled by the schema

    def test_an_id_is_safe_in_a_url(self):
        assert "/" not in suggestion_id("Customer", "email", ABSENCE, "N/A")


class TestTheScan:
    def test_a_disguised_absence_is_found_on_the_field_it_belongs_to(self, synced_deployment):
        from core.deployment_loader import load_deployment
        from core.mirror.catalog import open_mirror_catalog
        from core.mirror.rule_suggestion_scan import refresh
        from scripts.run_sync import run_sync

        with sqlite3.connect(synced_deployment.data_dir / "dev_fixtures" / "mediator.db") as conn:
            conn.execute("UPDATE customers SET email = 'N/A' WHERE customer_id = 'cust_002'")
        with contextlib.redirect_stdout(io.StringIO()):
            run_sync(synced_deployment)
        store = RuleSuggestionStore(synced_deployment.data_dir / "rule_suggestions.db")
        schema = load_deployment(synced_deployment.config_dir).schema

        refresh(open_mirror_catalog(synced_deployment.data_dir / "mirror"), schema, store)

        found = {(item.object_type, item.field, item.value): item.state for item in store.all()}
        assert found.get(("Customer", "email", "N/A")) == PENDING

    def test_a_value_the_schema_already_nulls_is_declared(self):
        from core.mirror.rule_suggestion_scan import already_declared

        schema = {"Customer": {"fields": {"email": {"standardise": {"null_if": ["N/A"]}}}}}

        assert already_declared(schema, [_finding("N/A"), _finding("none")]) == {
            suggestion_id("Customer", "email", ABSENCE, "N/A")}
