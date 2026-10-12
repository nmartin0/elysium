"""Gold reconciled against the source, read fresh (R8).

THE END-TO-END TESTS CHANGE THE SOURCE DATABASE BEHIND THE MIRROR'S
BACK -- an update, an insert, a delete, with no sync -- and require the
reconciliation to find exactly those three and nothing else. That is
the property that matters: a check that reports a clean mirror after a
fresh sync proves little unless it also reports a dirty one.
"""

import contextlib
import io
import sqlite3
from decimal import Decimal

from core.mirror.reconcile import describe, reconcile_rows
from scripts.reconcile import run

TYPE = {
    "id_field": "transaction_id",
    "fields": {
        "amount": {"type": "data", "data_type": "decimal"},
        "category": {"type": "data"},
        "customer_id": {"type": "link", "target": "Customer", "cardinality": "one"},
    },
}
COLUMNS = {"amount": "amount", "category": "category", "customer_id": "customer_id"}


def _source(**overrides):
    row = {"transaction_id": 1, "amount": "49.99", "category": "books", "customer_id": "cust_001"}
    return {**row, **overrides}


def _gold(**overrides):
    row = {"transaction_id": "1", "amount": Decimal("49.990000000"), "category": "books",
           "customer_id": "cust_001"}
    return {**row, **overrides}


def _compare(source_rows, gold_rows, type_def=TYPE):
    return reconcile_rows("Transaction", type_def, source_rows, COLUMNS, "transaction_id",
                          gold_rows)


class TestTheComparison:
    def test_identical_sides_are_clean(self):
        """THE CONTROL for everything below. Note what it asserts: a
        decimal read as text from the source and a decimal(38,9) from
        gold are the same amount, and an integer id is the same key as
        its text."""
        assert _compare([_source()], [_gold()]).clean

    def test_a_changed_value_is_named_with_its_id(self):
        result = _compare([_source(amount="50.00")], [_gold()])

        assert result.differing == {"amount": ["1"]}
        assert not result.clean

    def test_a_row_missing_from_either_side_is_named(self):
        result = _compare([_source(), _source(transaction_id=2)], [_gold(), _gold(transaction_id="3")])

        assert result.only_in_source == ["2"]
        assert result.only_in_gold == ["3"]

    def test_declared_standardisation_is_expected_not_a_fault(self):
        """The source says " books ", gold says "books", because silver
        collapses whitespace by default. That is the ontology's rule
        being followed."""
        result = _compare([_source(category="  books ")], [_gold()])

        assert result.clean
        assert result.standardised == {"category": 1}

    def test_a_standardisation_the_field_opted_out_of_is_a_fault(self):
        """THE CONTROL for the test above."""
        opted_out = {**TYPE, "fields": {**TYPE["fields"],
                                        "category": {"type": "data", "standardise": False}}}

        result = _compare([_source(category="  books ")], [_gold()], opted_out)

        assert result.differing == {"category": ["1"]}

    def test_control_totals_catch_what_keys_cannot(self):
        """Every key agrees and every value agrees, yet the totals do
        not -- because a row exists only on one side. The total is the
        check that does not trust either side's list of keys."""
        result = _compare([_source(), _source(transaction_id=2, amount="10")], [_gold()])

        assert result.totals["amount"] == (Decimal("59.99"), Decimal("49.990000000"))

    def test_a_link_is_compared_as_a_key(self):
        result = _compare([_source(customer_id="cust_002")], [_gold()])

        assert result.differing == {"customer_id": ["1"]}


def _run(paths) -> tuple[int, str]:
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        code = run(paths)
    return code, printed.getvalue()


class TestAgainstARealSourceAndARealSync:
    def test_a_fresh_sync_reconciles_clean(self, synced_deployment):
        code, report = _run(synced_deployment)

        assert code == 0, report
        assert "ok      Transaction" in report
        assert "DIFFERS" not in report

    def test_changes_behind_the_mirror_are_found_exactly(self, synced_deployment):
        database = synced_deployment.data_dir / "dev_fixtures" / "mediator.db"
        with sqlite3.connect(database) as conn:
            conn.execute("UPDATE transactions SET amount = 1234.5 WHERE transaction_id = 1")
            conn.execute("DELETE FROM transactions WHERE transaction_id = 2")
            conn.execute(
                "INSERT INTO transactions (transaction_id, customer_id, amount, currency, "
                "category, transaction_date) VALUES (999, 'cust_001', 5, 'USD', 'books', "
                "'2026-01-01')")

        code, report = _run(synced_deployment)

        assert code == 1
        assert "DIFFERS Transaction" in report
        assert "1 only in the source: 999" in report
        assert "1 only in gold: 2" in report
        assert "amount: 1 value(s) differ -- 1" in report
        # ...and nothing about the types nobody touched.
        assert "DIFFERS Customer" not in report



def test_a_type_built_from_several_sources_is_skipped_by_name():
    """Never silently passed: a fused type has no one source row to
    compare with, and the report says so rather than calling it ok."""
    from core.mirror.reconcile import reconcile

    fused = {"Customer": {"id_field": "customer_id",
                          "storage": {"silo": "a", "table": "t", "id_column": "id"},
                          "additional_storage": {"b": {"silo": "b", "table": "u",
                                                       "id_column": "id"}},
                          "fields": {}}}

    (result,) = reconcile(catalog=None, adapters={}, object_types=fused)

    assert "several" in result.skipped
    assert describe([result])[1].startswith("SKIPPED Customer")


def test_the_report_says_when_each_side_was_read():
    from core.mirror.reconcile import TypeReconciliation

    lines = describe([TypeReconciliation("T", 1, 1, published_at="2026-10-12T09:00:00+00:00")])

    assert lines[0].startswith("source read ")
    assert "gold published 2026-10-12T09:00:00+00:00" in lines[1]
