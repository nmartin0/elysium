"""
What the pipeline held back, where somebody will see it
(OPEN_RISKS item 1).

THE PROBLEM. A quarantined row is absent from silver and therefore
from gold, BY DESIGN -- it failed a rule the deployment declared, and
letting it through would put data in the ontology that the ontology
says is invalid. But ABSENCE READS AS LOSS: a person looking at 4,000
customers where the source has 4,200 cannot tell whether 200 rows were
rejected on purpose, dropped by a bug, or never existed.

Nothing said so anywhere. This is that, in the two places an operator
already looks: the mirror panel, per table and with the rule named,
and /health, as a fixed word.

HELD BACK IS NOT DEGRADED. A deployment whose rules are firing is
working, so quarantine has its own key and does not make /health say
"degraded" -- otherwise the first thing an operator learns from a
correctly-functioning rule is that something is wrong.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.expectations import expectations_for
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.quarantine_report import quarantine_for, quarantine_summary


class _Target:
    def __init__(self, silo, table):
        self.silo_name = silo
        self.table_name = table


@pytest.fixture
def synced(tmp_path):
    """A sync where one row fails a declared expectation."""
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, email TEXT)")
    conn.executemany("INSERT INTO customers VALUES (?,?)",
                     [("c1", "ada@example.com"), ("c2", None), ("c3", None)])
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "mirror",
                              {"primary": SQLiteReadAdapter({"path": source})})
    sync.sync_table(
        "primary", "customers", "customer_id", ["customer_id", "email"],
        {"customer_id": "string", "email": "string"},
        expectations={"email": expectations_for(
            {"required": True, "on_violation": "quarantine"})},
    )
    return sync


class TestTheReport:
    def test_it_counts_the_rows_held_back(self, synced):
        report = quarantine_for(synced._catalog, "primary", "customers")

        assert report.rows == 2

    def test_it_names_the_rule_that_caught_the_most(self, synced):
        """"12 rows held back" is a fact; "12 held back by required" is
        something somebody can act on."""
        report = quarantine_for(synced._catalog, "primary", "customers")

        assert report.worst_reason is not None
        assert "requir" in report.worst_reason.lower()

    def test_it_says_when(self, synced):
        report = quarantine_for(synced._catalog, "primary", "customers")

        assert report.last_detected_at is not None

    def test_a_table_with_no_quarantine_is_not_an_error(self, synced):
        """A deployment whose rules have never fired has no quarantine
        namespace at all, which is the normal and happy case."""
        report = quarantine_for(synced._catalog, "primary", "orders")

        assert report.rows == 0 and report.worst_reason is None

    def test_ROWS_not_findings_when_one_row_fails_TWO_rules(self, tmp_path):
        """WRITTEN BECAUSE A CONTROL PROVED NOTHING: every row in the
        fixture above fails exactly one rule, so counting findings and
        counting rows give the same answer and a mutation swapping
        them passed. Only a row that fails two rules tells them
        apart -- and reporting "2 rows held back" for one bad customer
        would make the number meaningless beside a row count."""
        source = tmp_path / "two.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, "
                     "email TEXT, region TEXT)")
        conn.execute("INSERT INTO customers VALUES ('c1', NULL, NULL)")
        conn.commit()
        conn.close()
        sync = IcebergMirrorSync(tmp_path / "mirror",
                                  {"primary": SQLiteReadAdapter({"path": source})})
        sync.sync_table(
            "primary", "customers", "customer_id",
            ["customer_id", "email", "region"],
            dict.fromkeys(["customer_id", "email", "region"], "string"),
            expectations={
                "email": expectations_for({"required": True, "on_violation": "quarantine"}),
                "region": expectations_for({"required": True, "on_violation": "quarantine"}),
            },
        )

        report = quarantine_for(sync._catalog, "primary", "customers")

        assert report.rows == 1, "one bad customer is one row, not two"
        assert sum(report.by_reason.values()) == 2, "and it failed two rules"

    def test_the_held_rows_and_the_kept_rows_account_for_everything(self, synced):
        """One row can fail two rules, and reporting "2 rows held back"
        for one bad customer would make the number meaningless next to
        a row count."""
        report = quarantine_for(synced._catalog, "primary", "customers")

        silver = synced._catalog.load_table("primary.customers").scan().to_arrow()
        assert report.rows + silver.num_rows == 3


class TestTheSummary:
    def test_it_totals_across_tables(self, synced):
        summary = quarantine_summary(synced._catalog, [_Target("primary", "customers")])

        assert summary["rows"] == 2
        assert summary["tables"] == ["primary.customers"]

    def test_a_clean_deployment_reports_nothing_held(self, synced):
        summary = quarantine_summary(synced._catalog, [_Target("primary", "orders")])

        assert summary == {"rows": 0, "tables": []}


# THE API SURFACES ARE TESTED IN tests/integration/test_api.py, where
# a real app exists: the mirror panel carries the per-table count and
# the rule, and /health carries a fixed word. They are wired to the
# same two functions above.
