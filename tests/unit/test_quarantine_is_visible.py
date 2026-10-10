"""
What the pipeline held back, where somebody will see it
(the invisible-quarantine risk).

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


@pytest.fixture
def two_rules(tmp_path):
    """One customer failing TWO rules, both of them `required`.

    The reason TEXT is identical for both, because a reason names the
    rule and not the column -- which is precisely the case that tells
    a finding count apart from a row count."""
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
    return sync


@pytest.fixture
def uneven(tmp_path):
    """Two rules catching DIFFERENT numbers of rows -- three missing
    emails, one missing region.

    Written because a control proved nothing: in every other fixture
    here each rule catches the same count, so reversing the sort
    produced an identical list and the ordering test passed with the
    ordering inverted."""
    source = tmp_path / "uneven.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, "
                 "email TEXT, region TEXT)")
    conn.executemany("INSERT INTO customers VALUES (?,?,?)", [
        ("c1", None, "us-west"),
        ("c2", None, "us-east"),
        ("c3", None, None),
    ])
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

    def test_ROWS_not_findings_when_one_row_fails_TWO_rules(self, two_rules):
        """WRITTEN BECAUSE A CONTROL PROVED NOTHING: every row in the
        fixture above fails exactly one rule, so counting findings and
        counting rows give the same answer and a mutation swapping
        them passed. Only a row that fails two rules tells them
        apart -- and reporting "2 rows held back" for one bad customer
        would make the number meaningless beside a row count."""
        report = quarantine_for(two_rules._catalog, "primary", "customers")

        assert report.rows == 1, "one bad customer is one row, not two"
        assert sum(report.by_reason.values()) == 2, "and it failed two rules"

    def test_it_splits_the_findings_by_column_as_well_as_rule(self, synced):
        """Which COLUMN is rejecting, not only how. "12 held back by
        required" says less than "12 held back by email: required"
        when a table declares the same rule on four columns."""
        report = quarantine_for(synced._catalog, "primary", "customers")

        assert [(rule.column, rule.rows) for rule in report.rules] == [("email", 2)]

    def test_TWO_COLUMNS_FAILING_THE_SAME_WAY_ARE_TWO_RULES_NOT_ONE(self, two_rules):
        """THE WHOLE REASON `rules` EXISTS, and the case `by_reason`
        gets wrong.

        One customer, missing both email and region, fails `required`
        twice -- and the reason TEXT is identical both times, because
        a reason names the rule and not the column. So `by_reason`
        holds {"is required, and missing": 2} for ONE row.

        That is harmless for picking the loudest rule, which is all
        `worst_reason` does with it. It is wrong as the numerator of a
        rate: a one-row table would report 200% quarantined. Keyed on
        the column too, each pair catches that row exactly once."""
        report = quarantine_for(two_rules._catalog, "primary", "customers")

        assert report.rows == 1
        assert sum(report.by_reason.values()) == 2, "the finding count double-counts"
        assert sum(rule.rows for rule in report.rules) == 2, "two distinct rules"
        assert all(rule.rows == 1 for rule in report.rules), (
            "but each caught the one row ONCE, which is what makes it divisible")
        assert {rule.column for rule in report.rules} == {"email", "region"}

    def test_a_rule_does_not_grow_louder_when_nothing_changed(self, synced):
        """THE QUARANTINE TABLE IS APPENDED, NEVER OVERWRITTEN -- that
        is deliberate, so one run's findings do not erase the last
        run's. It means a second sync over unchanged data writes the
        same findings again, and a rule counted by FINDINGS would
        double every night while the source sat still.

        Counting distinct ids per rule is what makes the number a
        property of the data rather than of how often the sync ran."""
        before = quarantine_for(synced._catalog, "primary", "customers")
        synced.sync_table(
            "primary", "customers", "customer_id", ["customer_id", "email"],
            {"customer_id": "string", "email": "string"},
            expectations={"email": expectations_for(
                {"required": True, "on_violation": "quarantine"})},
        )
        after = quarantine_for(synced._catalog, "primary", "customers")

        assert sum(rule.rows for rule in after.rules) == sum(
            rule.rows for rule in before.rules), "the data did not change"
        assert sum(after.by_reason.values()) > sum(before.by_reason.values()), (
            "while the finding count did, which is why rules is not built on it")

    def test_the_loudest_rule_comes_first(self, uneven):
        """An operator reads the top of a list. A list whose order came
        from however Iceberg returned the rows makes them read all of
        it to find the one that matters."""
        report = quarantine_for(uneven._catalog, "primary", "customers")

        assert [(rule.column, rule.rows) for rule in report.rules] == [
            ("email", 3), ("region", 1)]

    def test_a_table_with_no_quarantine_has_no_rules(self, synced):
        report = quarantine_for(synced._catalog, "primary", "orders")

        assert report.rules == []

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
