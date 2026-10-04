"""
A value that will not coerce costs the ROW, not the TABLE -- when the
deployment says so.

SEVEN `ZOO` FINDINGS COLLAPSE INTO THIS ONE QUESTION: ZOO-11, ZOO-12,
ZOO-15, ZOO-17, ZOO-18, ZOO-21, ZOO-22. Today an `N/A` in an integer
column refuses the whole table.

MEASURED ON A REAL DEPLOYMENT: seven transactions, two given
`amount='N/A'`. Before, the sync reported
`FAILED primary_sql.transactions` and wrote nothing. After, with
`on_type_mismatch: quarantine`, it reported "2 row(s) quarantined for
type mismatch; 5 synced" and the pipeline finished.

THE PRECEDENT SEPARATES TWO THINGS THIS DID NOT. Databricks' parsers
distinguish a MALFORMED RECORD from a TYPE MISMATCH -- "only
incomplete and malformed CSV records are considered corrupt", while a
type mismatch is rescued rather than failed, and their published
guidance is to "use PERMISSIVE + audit the corrupt record column
instead of failing the pipeline". An `N/A` in an integer column is a
type mismatch.

Their own forum carries a user describing Elysium's exact behaviour as
the problem: "it completely moves the file to the bad records' path,
which has good data as well... it should move only 2 bad data and 98
good data should load successfully".

QUARANTINE IS NOT A DROP, which is the objection the entry raised
against this -- "silently dropping a row loses data the operator may
not notice". The rows go to `quarantine_<silo>.<table>` with the
column, the offending value and the reason, and the sync says how many
in a warning. Verified end to end: two rows, both readable afterwards.

ABSENT KEEPS REFUSING. A deployment that has never heard of the key
behaves exactly as before, for the reason `write_targets` established:
a default flip applies to new installations, and breaking a working
pipeline to make a point it was never told about is not an upgrade.
"""

import pytest

from core.deployment_loader import _resolve_type_mismatch_policy
from core.mirror.transform import transform_rows

COLUMNS = ["id", "n"]
TYPES = {"id": "string", "n": "integer"}


class TestWhichRowsAreMismatched:
    def test_the_indices_are_reported(self):
        """WHICH ROWS, not just which columns. The column-level drift
        answers "is the schema wrong"; this answers "which records
        cannot be trusted", and without it the only possible response
        to one bad cell is refusing everything."""
        rows = [{"id": "1", "n": "10"}, {"id": "2", "n": "N/A"},
                {"id": "3", "n": "30"}, {"id": "4", "n": "oops"}]

        result = transform_rows(rows, COLUMNS, TYPES, {})

        assert result.mismatched_row_indices == [1, 3]

    def test_a_clean_table_reports_none(self):
        rows = [{"id": "1", "n": "10"}, {"id": "2", "n": "20"}]

        result = transform_rows(rows, COLUMNS, TYPES, {})

        assert result.mismatched_row_indices == []
        assert result.drift == []

    def test_the_good_rows_are_still_usable(self):
        """The point of the whole exercise."""
        rows = [{"id": "1", "n": "10"}, {"id": "2", "n": "N/A"},
                {"id": "3", "n": "30"}]

        result = transform_rows(rows, COLUMNS, TYPES, {})
        kept = [row for index, row in enumerate(result.rows)
                if index not in result.mismatched_row_indices]

        assert [row["id"] for row in kept] == ["1", "3"]
        assert [row["n"] for row in kept] == [10, 30]

    def test_one_row_failing_two_columns_is_counted_once(self):
        rows = [{"id": "1", "n": "bad"}, {"id": "2", "n": "9"}]

        result = transform_rows(rows, ["id", "n"], {"id": "integer",
                                                     "n": "integer"}, {})

        assert result.mismatched_row_indices == [0]

    def test_the_drift_report_is_unchanged(self):
        """The column-level report existed and other things read it.
        Adding row indices must not alter what it says."""
        rows = [{"id": "1", "n": "N/A"}, {"id": "2", "n": "also bad"}]

        result = transform_rows(rows, COLUMNS, TYPES, {})

        assert [d.column for d in result.drift] == ["n"]
        assert result.drift[0].example_value == "N/A"


class TestThePolicy:
    def test_absent_means_the_old_behaviour(self):
        """The upgrade path. An existing deployment keeps refusing."""
        assert _resolve_type_mismatch_policy({}) is None

    @pytest.mark.parametrize("declared", ["refuse", "quarantine"])
    def test_both_values_are_accepted(self, declared):
        assert _resolve_type_mismatch_policy(
            {"on_type_mismatch": declared}) == declared

    @pytest.mark.parametrize("declared", ["REFUSE", " Quarantine "])
    def test_case_and_space_are_forgiven(self, declared):
        assert _resolve_type_mismatch_policy(
            {"on_type_mismatch": declared}) in ("refuse", "quarantine")

    def test_anything_else_is_an_error(self):
        """Silently ignoring a typo would leave the operator believing
        rows are rescued while the table is still being refused."""
        with pytest.raises(ValueError, match="on_type_mismatch"):
            _resolve_type_mismatch_policy({"on_type_mismatch": "drop"})

    def test_the_error_names_the_valid_values(self):
        with pytest.raises(ValueError, match="quarantine"):
            _resolve_type_mismatch_policy({"on_type_mismatch": "yes"})


class TestItIsActuallyWired:
    """Eight times now this codebase has built something and connected
    it to nothing."""

    def test_the_sync_takes_the_policy(self):
        import inspect

        from core.mirror.iceberg_sync import IcebergMirrorSync

        parameters = inspect.signature(IcebergMirrorSync.__init__).parameters

        assert "on_type_mismatch" in parameters

    def test_the_real_sync_script_passes_it(self):
        from pathlib import Path

        source = Path("scripts/run_sync.py").read_text()

        assert "on_type_mismatch=config.on_type_mismatch" in source

    def test_the_quarantine_branch_writes_rows_rather_than_raising(self):
        from pathlib import Path

        source = Path("core/mirror/iceberg_sync.py").read_text()
        i = source.index('self._on_type_mismatch == "quarantine"')
        branch = source[i:i + 1400]

        assert "_write_quarantine(" in branch
        assert "raise" not in branch
