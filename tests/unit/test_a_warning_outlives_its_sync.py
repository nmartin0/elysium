"""The rules that fired and let the row through anyway.

THE ASYMMETRY THIS FIXES. A declared expectation has three policies.
`fail` stops the build, and the refusal is recorded as a sync attempt.
`quarantine` holds the row back and writes a finding to the lake with
the rule that caught it. `warn` keeps the row -- and the finding lived
in a log line on whatever process ran the sync, which on an unattended
on-prem deployment is a file nobody opens.

So the PERMISSIVE policy was the invisible one, which is the wrong way
round. A quarantined row is absent, and the absence is explained. A
warned row is PRESENT, in silver, in gold and on screen, identical to
one that broke no rule -- and the deployment declared a rule about it
precisely because somebody wanted to know.

DEV_UI.md section 5 item 6 asks for "failing expectations" beside the
quarantined rows. This is where that half comes from.
"""

import sqlite3
import time

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.expectation_warnings import ExpectationWarnings
from core.mirror.expectations import (
    RuleCount,
    apply_expectations,
    expectations_for,
)
from core.mirror.iceberg_sync import IcebergMirrorSync


def _warn(column, required=True):
    return expectations_for({"required": required, "on_violation": "warn"})


class TestWhatTheCheckReports:
    """`ExpectationResult.warnings`, which `counts` could not answer."""

    def test_it_counts_the_rows_each_rule_let_through(self):
        rows = [{"email": None}, {"email": None}, {"email": "ada@example.com"}]

        result = apply_expectations(rows, {"email": _warn("email")})

        assert [(rule.column, rule.rows) for rule in result.warnings] == [("email", 2)]

    def test_the_rows_are_still_kept_because_that_is_what_warn_means(self):
        rows = [{"email": None}, {"email": "ada@example.com"}]

        result = apply_expectations(rows, {"email": _warn("email")})

        assert len(result.kept) == 2
        assert result.quarantined == []

    def test_TWO_COLUMNS_FAILING_THE_SAME_WAY_ARE_TWO_RULES(self):
        """The case `counts` gets wrong, and the reason `warnings`
        exists as a separate property rather than a reshape of it.

        A reason names the RULE, not the column, so one row missing
        both email and region fails `required` twice with identical
        text. Keyed on the reason alone that is one entry of 2; keyed
        on the column too it is two entries of 1, and only the second
        can be read against a table size."""
        rows = [{"email": None, "region": None}]

        result = apply_expectations(
            rows, {"email": _warn("email"), "region": _warn("region")})

        assert sum(rule.rows for rule in result.warnings) == 2
        assert {rule.column for rule in result.warnings} == {"email", "region"}
        assert all(rule.rows == 1 for rule in result.warnings)

    def test_it_reports_the_loudest_rule_first(self):
        rows = [
            {"email": None, "region": "us-west"},
            {"email": None, "region": "us-east"},
            {"email": None, "region": None},
        ]

        result = apply_expectations(
            rows, {"email": _warn("email"), "region": _warn("region")})

        assert [(rule.column, rule.rows) for rule in result.warnings] == [
            ("email", 3), ("region", 1)]

    def test_a_QUARANTINED_row_is_not_also_reported_as_a_warning(self):
        """A row held back is held back once. Reporting it here as well
        would double-count it across two stores, and the panel would
        show the same bad customer under both headings."""
        rows = [{"email": None, "region": None}]

        result = apply_expectations(rows, {
            "email": expectations_for({"required": True, "on_violation": "quarantine"}),
            "region": _warn("region"),
        })

        assert result.quarantined
        assert result.warnings == []

    def test_a_clean_table_warns_about_nothing(self):
        rows = [{"email": "ada@example.com"}]

        result = apply_expectations(rows, {"email": _warn("email")})

        assert result.warnings == []


class TestTheSyncCarriesThem:
    def test_a_warned_rule_reaches_the_sync_result(self, tmp_path):
        """END TO END THROUGH THE REAL SYNC, not just the checker. The
        counts were computed all along; what was missing was anything
        carrying them out of the function that made them."""
        source = tmp_path / "s.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, email TEXT)")
        conn.executemany("INSERT INTO customers VALUES (?,?)",
                         [("c1", "ada@example.com"), ("c2", None)])
        conn.commit()
        conn.close()
        sync = IcebergMirrorSync(tmp_path / "mirror",
                                  {"primary": SQLiteReadAdapter({"path": source})})

        result = sync.sync_table(
            "primary", "customers", "customer_id", ["customer_id", "email"],
            {"customer_id": "string", "email": "string"},
            expectations={"email": _warn("email")},
        )

        assert [(rule.column, rule.rows) for rule in result.warnings] == [("email", 1)]
        assert result.row_count == 2, "warn keeps the row"
        assert result.quarantined == 0


class TestTheStore:
    @pytest.fixture
    def store(self, tmp_path):
        return ExpectationWarnings(tmp_path / "warnings.db")

    def test_a_warning_survives_the_process_that_found_it(self, store):
        """THE WHOLE POINT. Before this, the finding existed only as a
        log line on whatever ran the sync."""
        store.record("primary", "customers", [RuleCount("email", "is required", 3)])

        kept = store.latest_for("primary", "customers")

        assert [(each.column, each.reason, each.rows) for each in kept] == [
            ("email", "is required", 3)]

    def test_a_table_nothing_warned_about_reads_empty(self, store):
        assert store.latest_for("primary", "orders") == []

    def test_a_clean_run_does_not_even_OPEN_the_database(self, tmp_path):
        """A row per table per sync saying "no rules warned" would be
        the bulk of this store on a healthy deployment, and "when did
        this last warn" is answered by the absence.

        ASSERTED ON THE FILE, NOT ON WHAT COMES BACK, because a first
        version checked `latest_for(...) == []` and passed with the
        guard deleted -- `executemany` over an empty list writes no
        rows whether or not anything asked it to. What the guard
        actually buys is not opening a connection and not creating a
        schema for every clean table of every sync, and the file
        existing is the only visible difference."""
        db = tmp_path / "untouched.db"
        store = ExpectationWarnings(db)

        store.record("primary", "customers", [])

        assert not db.exists()

    def test_only_the_LAST_run_is_reported(self, store):
        """A rule fixed on Tuesday should stop being reported on
        Wednesday. Summing the retention window would keep it on screen
        for thirty days, which is how a panel becomes one nobody
        reads."""
        store.record("primary", "customers", [RuleCount("email", "is required", 9)])
        time.sleep(0.01)
        store.record("primary", "customers", [RuleCount("region", "is required", 1)])

        kept = store.latest_for("primary", "customers")

        assert [each.column for each in kept] == ["region"]

    def test_one_run_s_rules_are_all_reported(self, store):
        store.record("primary", "customers", [
            RuleCount("email", "is required", 3),
            RuleCount("region", "is required", 1),
        ])

        assert len(store.latest_for("primary", "customers")) == 2

    def test_the_loudest_comes_first(self, store):
        store.record("primary", "customers", [
            RuleCount("region", "is required", 1),
            RuleCount("email", "is required", 3),
        ])

        assert [each.column for each in store.latest_for("primary", "customers")] == [
            "email", "region"]

    def test_tables_do_not_see_each_other_s_warnings(self, store):
        store.record("primary", "customers", [RuleCount("email", "is required", 3)])

        assert store.latest_for("primary", "transactions") == []

    def test_silos_do_not_see_each_other_s_warnings(self, store):
        store.record("primary", "customers", [RuleCount("email", "is required", 3)])

        assert store.latest_for("secondary", "customers") == []

    def test_it_forgets_what_nobody_will_ask_about(self, store):
        store.record("primary", "customers", [RuleCount("email", "is required", 3)])

        assert store.forget_older_than(days=0) == 1
        assert store.latest_for("primary", "customers") == []

    def test_it_keeps_what_is_still_recent(self, store):
        store.record("primary", "customers", [RuleCount("email", "is required", 3)])

        assert store.forget_older_than(days=30) == 0
        assert store.latest_for("primary", "customers")

    def test_it_NEVER_RAISES_INTO_THE_SYNC(self, tmp_path):
        """A sync whose data work succeeded must not fail because its
        bookkeeping did. The cost is stated plainly in the class: a
        warning that cannot be written is a warning nobody sees, which
        is no worse than the log line it replaces."""
        unwritable = tmp_path / "no-such-directory" / "warnings.db"
        store = ExpectationWarnings(unwritable)

        store.record("primary", "customers", [RuleCount("email", "is required", 3)])

        assert store.latest_for("primary", "customers") == []
        assert store.forget_older_than() == 0
