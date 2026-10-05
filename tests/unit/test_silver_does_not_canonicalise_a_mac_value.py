"""
Silver leaves the security column exactly as the source wrote it.

`LLM3-3` asks where the security attribute should live, and the risk
behind the question is that the ELT pipeline rewrites it. I checked
whether that actually happens before building anything, and it does:
`transform_rows` standardises EVERY column, including the one MAC
reads.

MEASURED with the deployment's own rules:

    "N/A"        -> None        `null_if` reads it as a sentinel, and
                                the object then belongs to NO
                                compartment at all
    " us-west "  -> "us-west"   stops matching a caller whose own
                                value kept its spacing

The first is fail-closed and the second is a silent mismatch. Neither
is visible to anyone.

WHY STANDARDISATION IS RIGHT EVERYWHERE ELSE AND WRONG HERE. It exists
to make values COMPARABLE -- so two spellings of a city match. A
security value is not compared to other rows; it is compared to the
CALLER's own value, and it decides who may see the row. Canonicalising
it changes that decision.

THIS IS NOT THE SIDE TABLE. The owner chose a side table for LLM3-3
and this is smaller: it stops the pipeline rewriting the column that
exists today. It also produces the evidence the migration was going to
need -- the column's weakness is real and now measured, and what
remains of the argument for moving the value is that every FUTURE
pipeline stage must remember the same rule.

`via_field` IS DELIBERATELY NOT HANDLED. That security value lives on
a different type's row, so this table has no column to protect and the
protection belongs to the table that does.
"""

import pytest

from core.mirror.transform import transform_rows

RULES = {"unicode": "NFC", "collapse_whitespace": True, "trim": True,
         "null_if": ["N/A", ""]}
TYPES = {"customer_id": "string", "region": "string", "name": "string"}
COLUMNS = ["customer_id", "region", "name"]
STANDARDISATION = {column: RULES for column in COLUMNS}


def _rows():
    return [{"customer_id": "c1", "region": " us-west ", "name": " Ada "},
            {"customer_id": "c2", "region": "N/A", "name": "Bo"}]


class TestWithoutTheExemption:
    """What the pipeline was doing, kept as a test so the fix cannot be
    removed without the reason reappearing."""

    def test_a_sentinel_region_becomes_none(self):
        result = transform_rows(_rows(), COLUMNS, TYPES, STANDARDISATION)

        assert result.rows[1]["region"] is None

    def test_a_padded_region_is_rewritten(self):
        result = transform_rows(_rows(), COLUMNS, TYPES, STANDARDISATION)

        assert result.rows[0]["region"] == "us-west"


class TestWithIt:
    def test_a_sentinel_region_survives(self):
        """`"N/A"` is a bad compartment value and that is the
        deployment's problem to fix. Turning it into None makes the row
        invisible to everyone, which hides the problem instead."""
        result = transform_rows(_rows(), COLUMNS, TYPES, STANDARDISATION,
                                security_column="region")

        assert result.rows[1]["region"] == "N/A"

    def test_a_padded_region_survives(self):
        result = transform_rows(_rows(), COLUMNS, TYPES, STANDARDISATION,
                                security_column="region")

        assert result.rows[0]["region"] == " us-west "

    def test_every_other_column_is_still_canonicalised(self):
        """The exemption is ONE column. Silver still does its job."""
        result = transform_rows(_rows(), COLUMNS, TYPES, STANDARDISATION,
                                security_column="region")

        assert result.rows[0]["name"] == "Ada"

    def test_naming_a_column_that_is_not_there_changes_nothing(self):
        result = transform_rows(_rows(), COLUMNS, TYPES, STANDARDISATION,
                                security_column="nonexistent")

        assert result.rows[0]["region"] == "us-west"


class TestWhereTheColumnComesFrom:
    def test_it_is_read_from_the_type_declaration(self):
        from core.mirror.sync_targets import resolve_sync_targets

        schema = {"object_types": {"Customer": {
            "id_field": "customer_id",
            "security": {"field": "region"},
            "storage": {"silo": "p", "table": "customers",
                         "id_column": "customer_id"},
            "fields": {"customer_id": {"data_type": "string"},
                        "region": {"data_type": "string"}},
        }}}

        target = resolve_sync_targets(schema)[0]

        assert target.security_column == "region"

    def test_a_type_with_no_security_block_has_none(self):
        from core.mirror.sync_targets import resolve_sync_targets

        schema = {"object_types": {"Widget": {
            "id_field": "widget_id",
            "storage": {"silo": "p", "table": "widgets",
                         "id_column": "widget_id"},
            "fields": {"widget_id": {"data_type": "string"}},
        }}}

        assert resolve_sync_targets(schema)[0].security_column is None

    def test_two_types_disagreeing_about_one_table_is_refused(self):
        """Picking one would leave a column nobody protects."""
        from core.mirror.sync_targets import resolve_sync_targets

        shared = {"silo": "p", "table": "shared", "id_column": "id"}
        schema = {"object_types": {
            "A": {"id_field": "id", "security": {"field": "region"},
                   "storage": shared,
                   "fields": {"id": {"data_type": "string"},
                               "region": {"data_type": "string"},
                               "zone": {"data_type": "string"}}},
            "B": {"id_field": "id", "security": {"field": "zone"},
                   "storage": shared,
                   "fields": {"id": {"data_type": "string"},
                               "region": {"data_type": "string"},
                               "zone": {"data_type": "string"}}},
        }}

        with pytest.raises(ValueError, match="different security fields"):
            resolve_sync_targets(schema)


class TestItIsActuallyWired:
    """Ten times this codebase has built something and connected it to
    nothing. The guard is worthless unless the real sync passes it."""

    def test_sync_table_takes_it(self):
        import inspect

        from core.mirror.iceberg_sync import IcebergMirrorSync

        assert "security_column" in inspect.signature(
            IcebergMirrorSync.sync_table).parameters

    def test_the_real_sync_script_passes_it(self):
        from pathlib import Path

        source = Path("scripts/run_sync.py").read_text()

        assert "security_column=target.security_column" in source

    def test_the_parameter_is_last_in_the_signature(self):
        """It was inserted mid-list first, and mypy caught that it
        shifted every positional argument at the one call site that
        passes them that way."""
        import inspect

        from core.mirror.iceberg_sync import IcebergMirrorSync

        parameters = list(inspect.signature(
            IcebergMirrorSync.sync_table).parameters)

        assert parameters[-1] == "security_column"
