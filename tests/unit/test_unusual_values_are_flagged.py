"""
Unusual values are flagged, never acted on (R30).

Warn only, always: an outlier is RARE, not wrong. These tests hold the
three textbook methods to their definitions, and hold the pipeline to
its promise that a flagged row still lands.
"""

import sqlite3
from decimal import Decimal

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.outliers import MIN_VALUES, unusual, validate_outliers
from core.mirror.sync_targets import resolve_sync_targets

ORDINARY = [float(value) for value in range(100, 130)]  # 30 values, 100..129


class TestTheMethods:
    def test_tukey_far_out_fences(self):
        """With these 33 values Q1 is 107 and Q3 123, so k = 3 puts the
        fences at 59 and 171: 300 and -50 are outside, 170 is not."""
        found = unusual([*ORDINARY, 300.0, 170.0, -50.0], {"method": "iqr", "k": 3.0})

        assert sorted(found) == [30, 32]
        assert "outside 59 to 171" in found[30]
        assert "Tukey's fences at k = 3" in found[30]

    def test_the_modified_z_score(self):
        found = unusual([*ORDINARY, 1000.0], {"method": "mad", "k": 3.0})

        assert list(found) == [30]
        assert "robust z-score" in found[30]

    def test_decimals_are_measured(self):
        values = [Decimal(value) for value in range(100, 130)] + [Decimal("100000.50")]
        assert list(unusual(values, {"method": "iqr", "k": 3.0})) == [30]

    def test_a_shape_almost_nothing_else_has(self):
        codes = [f"SW{i} {i}AA" for i in range(1, 200)] + ["unknown"]
        found = unusual(codes, {"method": "pattern"})

        assert list(found) == [199]
        assert "'unknown' is shaped 'A'" in found[199]

    def test_free_text_has_no_usual_shape(self):
        """Forty shapes, five values each, and one shape seen once: the
        one is rare (under 1%), but no shape is USUAL, so nothing is
        unusual against it."""
        values = [f"a{'1a' * k}" for k in range(1, 41) for _ in range(5)] + ["?"]
        assert unusual(values, {"method": "pattern"}) == {}

    def test_too_few_values_is_no_flag(self):
        assert unusual([1.0] * (MIN_VALUES - 2) + [1e9], {"method": "iqr", "k": 3.0}) == {}

    def test_empty_values_are_skipped(self):
        assert unusual([*ORDINARY, None, None], {"method": "iqr", "k": 3.0}) == {}


class TestRefusedAtLoad:
    @pytest.mark.parametrize("field, says", [
        ({"data_type": "string", "outliers": True}, "for text use"),
        ({"data_type": "integer", "outliers": {"method": "pattern"}}, "shapes of text"),
        ({"data_type": "string", "outliers": {"method": "mad"}}, "measures numbers"),
        ({"data_type": "number", "outliers": {"method": "zscore"}}, "method must be one of"),
        ({"data_type": "number", "outliers": {"method": "mad", "k": 2}}, "applies to iqr only"),
        ({"data_type": "number", "outliers": {"k": 0}}, "positive number"),
        ({"data_type": "number", "outliers": "yes"}, "true or a mapping"),
    ])
    def test_a_declaration_that_could_never_work(self, field, says):
        with pytest.raises(ValueError, match=says):
            validate_outliers({"T": {"fields": {"f": {"type": "data", **field}}}})


def test_a_flagged_row_still_lands(tmp_path):
    """THE PROMISE: warn only. The row with the unusual amount is in
    silver, and the run reported it."""
    source = tmp_path / "s.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE orders (id TEXT PRIMARY KEY, amount REAL)")
    connection.executemany("INSERT INTO orders VALUES (?, ?)",
                           [(f"o{i}", value) for i, value in enumerate(ORDINARY)] + [("big", 1e7)])
    connection.commit()
    connection.close()
    schema = {"Order": {"id_field": "id", "storage": {"silo": "s", "table": "orders", "id_column": "id"},
                        "fields": {"id": {"type": "data"},
                                   "amount": {"type": "data", "data_type": "number",
                                              "outliers": True}}}}
    validate_outliers(schema)
    (target,) = resolve_sync_targets({"object_types": schema})
    sync = IcebergMirrorSync(tmp_path / "m", {"s": SQLiteReadAdapter({"path": source})})

    result = sync.sync_table("s", "orders", "id", target.columns, target.column_types,
                             target.fields_by_column, target.standardisation, target.expectations)

    ids = {row["id"] for row in sync._catalog.load_table("s.orders").scan().to_arrow().to_pylist()}
    assert "big" in ids and len(ids) == 31
    assert result.quarantined == 0
    assert any("Tukey" in rule for rule in result.violations)
