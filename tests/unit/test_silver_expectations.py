"""
Silver checks every row, and nothing is dropped silently (GOLD-1's
second stage, MEDALLION_PIPELINE.md's S2 and S3).

THE RULES ALREADY EXISTED: a field's `constraints` block (patch 297) is
evaluated when a WRITE proposes a value. The same block is an
expectation about what a SOURCE holds. One rule language, declared
once; `required` adds completeness.

THE POLICIES ARE THE OWNER'S DECISION of September 22, and the split
follows precedent: per-row checks default to WARN (keep the row, count
it), build-level checks default to FAIL. QUARANTINE is the only removal
-- the row is written to the quarantine table with the rule that caught
it, and bronze still holds it exactly as the source wrote it.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.expectations import (
    ExpectationFailed,
    apply_expectations,
    expectations_for,
    policy_for,
)
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.sync_targets import resolve_sync_targets

ONE_OF = {"type": "data", "data_type": "string", "constraints": {"one_of": ["us-west", "us-east"]}}
ROWS = [{"id": "a", "region": "us-west"}, {"id": "b", "region": "mars"}, {"id": "c", "region": None}]


def _expectations(policy="warn", required=False):
    return {"region": {"field_def": {**ONE_OF, "on_violation": policy, "required": required},
                       "required": required, "policy": policy, "field_name": "region"}}


class TestTheThreePolicies:
    def test_warn_keeps_the_row_and_counts_it(self):
        result = apply_expectations(ROWS, _expectations("warn"))

        assert len(result.kept) == 3 and not result.quarantined
        assert sum(result.counts.values()) == 1

    def test_quarantine_holds_the_row_back_with_its_reason(self):
        result = apply_expectations(ROWS, _expectations("quarantine"))

        assert [row["id"] for row in result.kept] == ["a", "c"]
        held_row, finding = result.quarantined[0]
        assert held_row["id"] == "b" and "not one of" in finding.reason

    def test_fail_stops_the_build(self):
        with pytest.raises(ExpectationFailed, match="mirror is unchanged"):
            apply_expectations(ROWS, _expectations("fail"))

    def test_the_default_is_warn(self):
        assert policy_for({}) == "warn"

    def test_an_unknown_policy_is_refused(self):
        """A typo that downgraded a `fail` to nothing would be the worst
        failure this feature could have."""
        with pytest.raises(ValueError, match="on_violation must be one of"):
            policy_for({"on_violation": "quarentine"})


class TestWhatIsChecked:
    def test_a_missing_value_violates_required(self):
        result = apply_expectations(ROWS, _expectations("quarantine", required=True))

        reasons = {finding.reason for _, finding in result.quarantined}
        assert "is required, and missing" in reasons
        assert [row["id"] for row in result.kept] == ["a"]

    def test_a_null_alone_violates_nothing(self):
        """A NULL is the absence of a value; `required` is the rule for
        it, and a range or a pattern cannot apply."""
        result = apply_expectations([{"id": "c", "region": None}], _expectations("quarantine"))

        assert len(result.kept) == 1 and not result.quarantined

    def test_a_column_declaring_nothing_is_not_checked(self):
        assert expectations_for({"type": "data"}) is None

    def test_constraints_alone_are_enough_to_check(self):
        assert expectations_for(ONE_OF)["policy"] == "warn"

    def test_the_strictest_policy_a_row_meets_decides(self):
        """A quarantine rule is never overridden by a warn on another
        column."""
        expectations = {
            "region": {"field_def": ONE_OF, "required": False, "policy": "warn",
                       "field_name": "region"},
            "code": {"field_def": {"type": "data", "data_type": "string",
                                   "constraints": {"pattern": "^[A-Z]+$"}},
                     "required": False, "policy": "quarantine", "field_name": "code"},
        }

        result = apply_expectations([{"id": "b", "region": "mars", "code": "lower"}], expectations)

        assert not result.kept and len(result.quarantined) == 1


class TestThroughTheSync:
    @pytest.fixture
    def synced(self, tmp_path):
        source = tmp_path / "s.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, region TEXT)")
        conn.executemany("INSERT INTO t VALUES (?,?)", [("a", "us-west"), ("b", "mars")])
        conn.commit()
        conn.close()
        return IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": source})})

    def _sync(self, sync, policy):
        return sync.sync_table("p", "t", "id", ["id", "region"],
                               {"id": "string", "region": "string"},
                               expectations=_expectations(policy))

    def test_a_quarantined_row_is_not_in_silver(self, synced):
        result = self._sync(synced, "quarantine")

        assert result.row_count == 1 and result.quarantined == 1

    def test_and_is_recorded_with_its_rule(self, synced):
        self._sync(synced, "quarantine")

        held = synced._catalog.load_table("quarantine_p.t").scan().to_arrow().to_pylist()
        assert [(h["object_id"], h["column"], h["policy"]) for h in held] == [("b", "region", "quarantine")]
        assert "not one of" in held[0]["reason"]

    def test_and_bronze_still_holds_the_row(self, synced):
        """NOTHING IS LOST: quarantine holds a row back from silver, and
        the source's own version stays in bronze."""
        self._sync(synced, "quarantine")

        bronze = synced._catalog.load_table("bronze_p.t").scan().to_arrow().to_pylist()
        assert sorted(row["id"] for row in bronze) == ["a", "b"]

    def test_findings_are_appended_not_overwritten(self, synced):
        self._sync(synced, "quarantine")
        self._sync(synced, "quarantine")

        held = synced._catalog.load_table("quarantine_p.t").scan().to_arrow().to_pylist()
        assert len(held) == 2

    def test_warn_syncs_everything_and_reports(self, synced):
        result = self._sync(synced, "warn")

        assert result.row_count == 2 and result.quarantined == 0
        assert sum(result.violations.values()) == 1

    def test_fail_leaves_the_mirror_unchanged(self, synced):
        self._sync(synced, "warn")   # a good sync first
        before = synced._catalog.load_table("p.t").current_snapshot().snapshot_id

        with pytest.raises(ExpectationFailed):
            self._sync(synced, "fail")

        assert synced._catalog.load_table("p.t").current_snapshot().snapshot_id == before


def test_the_policy_reaches_the_sync_target():
    schema = {"object_types": {"Customer": {
        "id_field": "customer_id",
        "storage": {"silo": "s", "table": "customers", "id_column": "customer_id"},
        "security": {"field": "region"},
        "fields": {"region": {**ONE_OF, "on_violation": "quarantine"}},
    }}}

    target = resolve_sync_targets(schema)[0]

    assert target.expectations["region"]["policy"] == "quarantine"


def test_a_bad_policy_names_the_field():
    schema = {"object_types": {"Customer": {
        "id_field": "customer_id",
        "storage": {"silo": "s", "table": "customers", "id_column": "customer_id"},
        "security": {"field": "region"},
        "fields": {"region": {**ONE_OF, "on_violation": "quarentine"}},
    }}}

    with pytest.raises(ValueError, match="Field 'region'"):
        resolve_sync_targets(schema)
