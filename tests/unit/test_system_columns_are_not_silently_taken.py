"""
A source column named after a system column is refused, not
overwritten (found by LLM3).

WHAT WAS HAPPENING. `with_lineage` spreads Elysium's own values AFTER
the row, so last-write-wins destroyed any source column of the same
name:

    source: {'customer_id': 'c1', '_silo': 'CUSTOMER VALUE'}
    silver: {'customer_id': 'c1', '_silo': 'primary_sql'}

No error, no warning, no drift report. The loss happens exactly once,
at that function; everything downstream carries the already-lost value
forward. Leading underscores are not exotic -- they appear routinely
in exports, staging tables and ORM-generated schemas.

A SECOND, DIFFERENT FAILURE if the ONTOLOGY declares the name: gold's
schema gains the column twice and the build raises "Column _silo does
not exist in schema" -- opaque, at gold-build time.

WHY THIS SITS BESIDE THE SECURITY FIX. A type declaring
`security: field: _silo` would compare every reader against the string
"primary_sql" -- identical for every row in the silo. Not the wrong
compartment: NO compartment. Remote, but the same failure class as
standardising the security field, found within an hour of it, and both
come from the security attribute sharing a namespace with values the
pipeline writes.

TWO CHECKS, BECAUSE ONE CANNOT SEE BOTH CASES. The load-time check
reads the SCHEMA and catches a declared field or a declared `column:`.
It cannot see a column the SOURCE has and the ontology does not
mention -- so the sync-time check lives at the point of loss, which is
also the only place that knows.
"""

import sqlite3
from pathlib import Path

import pytest
import yaml

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.deployment_loader import _refuse_system_column_names
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.lineage import (
    LINEAGE_COLUMNS,
    SYSTEM_COLUMNS,
    collides_with_a_system_column,
    with_lineage,
)


class TestTheSyncRefusesTheCollision:
    def test_a_source_column_called_silo(self):
        """THE REGRESSION TEST. This used to return the row with the
        customer's value replaced."""
        with pytest.raises(ValueError, match="_silo"):
            with_lineage([{"customer_id": "c1", "_silo": "CUSTOMER VALUE"}],
                          ["customer_id", "_silo"], "primary_sql", "customers")

    @pytest.mark.parametrize("column", LINEAGE_COLUMNS)
    def test_every_lineage_column(self, column):
        with pytest.raises(ValueError, match=column):
            with_lineage([{"id": "c1", column: "theirs"}], ["id", column],
                          "p", "t")

    def test_the_message_names_the_table_and_the_column(self):
        """An operator has to know WHICH table to rename."""
        with pytest.raises(ValueError, match="primary_sql.customers"):
            with_lineage([{"id": "c1", "_row_hash": "theirs"}],
                          ["id", "_row_hash"], "primary_sql", "customers")

    def test_an_ordinary_table_is_untouched(self):
        rows = with_lineage([{"customer_id": "c1", "name": "Ada"}],
                             ["customer_id", "name"], "primary_sql", "customers")

        assert rows[0]["customer_id"] == "c1"
        assert rows[0]["_silo"] == "primary_sql"

    def test_a_real_sync_refuses_rather_than_losing_the_column(self, tmp_path):
        """End to end: the table is not copied, and the message says
        why."""
        source = tmp_path / "s.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, _silo TEXT)")
        conn.execute("INSERT INTO t VALUES ('a','CUSTOMER VALUE')")
        conn.commit()
        conn.close()
        sync = IcebergMirrorSync(tmp_path / "m",
                                  {"p": SQLiteReadAdapter({"path": source})})

        with pytest.raises(ValueError, match="_silo"):
            sync.sync_table("p", "t", "id", ["id", "_silo"], {})


class TestTheLoadRefusesADeclaredOne:
    def test_a_field_named_after_a_system_column(self):
        schema = {"object_types": {"C": {"fields": {"_silo": {"type": "data"}}}}}

        with pytest.raises(ValueError, match="_silo"):
            _refuse_system_column_names(schema)

    def test_a_field_READING_a_system_column(self):
        """`region: {column: _silo}` collides just as surely and reads
        less obviously."""
        schema = {"object_types": {"C": {
            "fields": {"region": {"type": "data", "column": "_silo"}}}}}

        with pytest.raises(ValueError, match="_silo"):
            _refuse_system_column_names(schema)

    def test_an_id_column(self):
        schema = {"object_types": {"C": {
            "storage": {"id_column": "_row_hash"}, "fields": {}}}}

        with pytest.raises(ValueError, match="_row_hash"):
            _refuse_system_column_names(schema)

    def test_the_message_names_the_object_type(self):
        schema = {"object_types": {"Customer": {
            "fields": {"_fused_from": {"type": "data"}}}}}

        with pytest.raises(ValueError, match="Customer"):
            _refuse_system_column_names(schema)

    def test_an_ordinary_schema_loads(self):
        schema = {"object_types": {"C": {
            "storage": {"id_column": "id"},
            "fields": {"name": {"type": "data"}, "region": {"type": "data"}}}}}

        _refuse_system_column_names(schema)

    def test_the_shipped_deployment_still_loads(self):
        """The check must not refuse what we ship."""
        from pathlib import Path

        import yaml

        raw = yaml.safe_load(Path("deployment/etc/ontology_schema.yaml").read_text())

        _refuse_system_column_names(raw)

    def test_the_integration_fixture_still_loads(self):
        from pathlib import Path

        import yaml

        raw = yaml.safe_load(
            Path("tests/integration/fixtures/ontology_schema.yaml").read_text())

        _refuse_system_column_names(raw)


class TestElysiumsOwnColumnsAreNotRefused:
    """FOUND BY THE SUITE, NOT BY REASONING. My first version checked
    the WIDE set at sync time, and `_link_id` is a column ELYSIUM
    ITSELF adds to a join table (PA001-A2's composite key). Every
    many-to-many sync refused:

        ValueError: p.customer_tags has '_link_id', which the pipeline
        writes for itself

    A guard that refuses the thing it is guarding is worse than no
    guard. `with_lineage` can only overwrite what IT writes, so that
    is what it checks."""

    def test_a_join_tables_link_id_is_allowed(self):
        rows = with_lineage([{"customer_id": "c1", "tag_id": "t1",
                               "_link_id": "c1\x1ft1"}],
                             ["customer_id", "tag_id", "_link_id"], "p",
                             "customer_tags")

        assert rows[0]["_link_id"] == "c1\x1ft1"

    def test_but_a_DECLARED_link_id_field_is_still_refused_at_load(self):
        """The load check keeps the wide set: declaring a field of
        that name is a mistake wherever it appears."""
        schema = {"object_types": {"C": {"fields": {"_link_id": {"type": "data"}}}}}

        with pytest.raises(ValueError, match="_link_id"):
            _refuse_system_column_names(schema)


class TestItIsWiredIntoTheLoad:
    """WRITTEN BECAUSE A CONTROL PROVED NOTHING -- FOR THE THIRD TIME
    IN THIS AUDIT (patches 427, 438, and now here).

    Every test above calls the checking function DIRECTLY, so removing
    the CALL to it left all sixteen passing. The pattern is now clear
    enough to name: a test of a validator is not a test that anything
    validates."""

    def test_a_deployment_declaring_a_system_column_refuses_to_load(self,
                                                                     tmp_path):
        import shutil

        from core.deployment_loader import load_deployment

        fixtures = Path("tests/integration/fixtures")
        for name in ("config.yaml", "ontology_schema.yaml", "policy.yaml",
                      "data_silos.yaml"):
            shutil.copy(fixtures / name, tmp_path / name)
        schema = yaml.safe_load((tmp_path / "ontology_schema.yaml").read_text())
        first = next(iter(schema["object_types"].values()))
        first["fields"]["_silo"] = {"type": "data"}
        (tmp_path / "ontology_schema.yaml").write_text(yaml.safe_dump(schema))

        with pytest.raises(ValueError, match="_silo"):
            load_deployment(tmp_path)

    def test_the_unmodified_fixture_still_loads(self, tmp_path):
        import shutil

        from core.deployment_loader import load_deployment

        fixtures = Path("tests/integration/fixtures")
        for name in ("config.yaml", "ontology_schema.yaml", "policy.yaml",
                      "data_silos.yaml"):
            shutil.copy(fixtures / name, tmp_path / name)

        assert load_deployment(tmp_path) is not None


class TestTheListStaysHonest:
    def test_it_covers_every_column_the_pipeline_writes(self):
        """The set is named in one place; the columns are declared in
        three modules. If they drift, the guard silently stops
        guarding -- so the drift is a test failure instead."""
        from core.mirror.fusion import FUSED_FROM_COLUMN
        from core.mirror.sync_targets import LINK_ID_COLUMN

        for column in (*LINEAGE_COLUMNS, FUSED_FROM_COLUMN, LINK_ID_COLUMN):
            assert column in SYSTEM_COLUMNS, (
                f"{column} is written by the pipeline but not guarded")

    def test_it_reports_all_collisions_not_just_the_first(self):
        """An operator renaming one column at a time, discovering the
        next only after another sync, would be a poor way to spend an
        afternoon."""
        assert collides_with_a_system_column(
            ["id", "_silo", "name", "_row_hash"]) == ["_row_hash", "_silo"]
