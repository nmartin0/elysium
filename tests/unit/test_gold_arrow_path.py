"""
Building gold without Python dicts (GOLD-7).

MEASURED, NOT ASSUMED. 200,000 six-column rows cost 25.7 MB as Arrow
buffers and 154.3 MB as a list of dicts -- 772 bytes a row, a SIX-FOLD
amplification, because every value becomes a Python object and every
row a hash table. Ten million rows would need 7.7 GB that way.

AND THE WORK NEVER NEEDED DICTS: conform is a column rename, and the
audit counts nulls, counts distinct ids and compares totals. Building
gold for a single-source type now peaks at 0.4 MB instead of 126.7 and
takes 0.18s instead of 5.80.

WHAT STILL USES DICTS, deliberately: identity resolution and
survivorship compare values row by row across sources, and the
changelog diffs two snapshots by key. Those are row-shaped problems.

THE CENTREPIECE HERE IS PARITY. Two audits that are supposed to agree
and quietly drift apart are worse than one slower audit, so the
findings are compared MESSAGE FOR MESSAGE.
"""

import pyarrow as pa
import pytest

from core.mirror.gold import audit, build_gold, conform
from core.mirror.gold_arrow import audit_arrow, conform_arrow

TYPE = {
    "id_field": "customer_id",
    "security": {"field": "region"},
    "storage": {"silo": "p", "table": "customers", "id_column": "cust_pk"},
    "fields": {
        "customer_id": {"type": "data", "column": "cust_pk"},
        "region": {"type": "data", "required": True},
        "name": {"type": "data"},
        "owner": {"type": "link", "target": "Staff", "cardinality": "one"},
        "txns": {"type": "link", "target": "Transaction", "cardinality": "many",
                  "via_table": "t", "via_column": "c"},
    },
}
ROWS = [
    {"cust_pk": "c1", "region": "us-west", "name": "Ada", "owner": "s1", "_silo": "p"},
    {"cust_pk": "c2", "region": "us-east", "name": "Ben", "owner": "s1", "_silo": "p"},
    {"cust_pk": "c3", "region": "eu", "name": "Cleo", "owner": None, "_silo": "p"},
]


def _table(rows):
    return pa.Table.from_pylist(rows)


class TestConformParity:
    def test_the_two_paths_produce_the_same_rows(self):
        """Compared at the shape that gets PUBLISHED: the dict path
        completes the lineage columns and casts to the declared types
        in _arrow(), which conform_arrow does in one step."""
        from core.mirror.gold import _arrow

        assert conform_arrow(TYPE, _table(ROWS)).to_pylist() == \
            _arrow(conform(TYPE, ROWS), TYPE).to_pylist()

    def test_the_id_is_renamed_to_the_ontologys_name(self):
        conformed = conform_arrow(TYPE, _table(ROWS))

        assert "customer_id" in conformed.column_names
        assert "cust_pk" not in conformed.column_names

    def test_a_reverse_link_is_not_a_column(self):
        """It is resolved by querying the target, not stored."""
        assert "txns" not in conform_arrow(TYPE, _table(ROWS)).column_names

    def test_lineage_travels(self):
        assert "_silo" in conform_arrow(TYPE, _table(ROWS)).column_names

    def test_a_declared_property_silver_lacks_becomes_null(self):
        rows = [{"cust_pk": "c1", "region": "us-west", "_silo": "p"}]

        conformed = conform_arrow(TYPE, _table(rows))

        assert conformed.column("name").null_count == 1


class TestAuditParity:
    """Compared MESSAGE FOR MESSAGE, because a divergence here is two
    checks disagreeing about whether to publish."""

    @pytest.mark.parametrize("rows, previous, known", [
        (ROWS, None, None),
        (ROWS, 3, {"Staff": {"s1"}}),
        # no id
        ([{"cust_pk": None, "region": "eu", "_silo": "p"}], None, None),
        # duplicate ids
        ([{"cust_pk": "c1", "region": "eu"}, {"cust_pk": "c1", "region": "eu"}], None, None),
        # a required property missing
        ([{"cust_pk": "c1", "region": None}], None, None),
        # a link pointing at nothing
        ([{"cust_pk": "c1", "region": "eu", "owner": "s9"}], None, {"Staff": {"s1"}}),
        # most of the rows gone
        (ROWS, 100, None),
    ])
    def test_both_audits_find_the_same_things(self, rows, previous, known):
        table = _table(rows)

        from_dicts = audit(TYPE, conform(TYPE, rows), previous, known)
        from_arrow = audit_arrow(TYPE, conform_arrow(TYPE, table), previous, known)

        assert sorted(from_dicts) == sorted(from_arrow)

    def test_a_missing_id_column_is_reported_rather_than_raised(self):
        table = pa.Table.from_pylist([{"region": "eu"}])

        assert audit_arrow(TYPE, table, None, None) == ["no customer_id column"]


class TestThroughABuild:
    def test_arrow_in_publishes_the_same_gold_as_dicts_in(self, tmp_path):
        from pyiceberg.catalog.sql import SqlCatalog
        warehouse = tmp_path / "w"
        warehouse.mkdir()
        catalog = SqlCatalog("t", uri=f"sqlite:///{tmp_path / 'c.db'}",
                              warehouse=f"file://{warehouse}")

        from_dicts = build_gold(catalog, "FromDicts", TYPE, ROWS)
        from_arrow = build_gold(catalog, "FromArrow", TYPE, _table(ROWS))

        assert from_dicts.published and from_arrow.published
        assert from_dicts.rows == from_arrow.rows
        dict_rows = catalog.load_table("gold.FromDicts").scan().to_arrow().to_pylist()
        arrow_rows = catalog.load_table("gold.FromArrow").scan().to_arrow().to_pylist()
        assert sorted(dict_rows, key=repr) == sorted(arrow_rows, key=repr)

    def test_a_failing_audit_refuses_on_the_arrow_path_too(self, tmp_path):
        from pyiceberg.catalog.sql import SqlCatalog
        warehouse = tmp_path / "w"
        warehouse.mkdir()
        catalog = SqlCatalog("t", uri=f"sqlite:///{tmp_path / 'c.db'}",
                              warehouse=f"file://{warehouse}")
        broken = [{"cust_pk": "c1", "region": None, "_silo": "p"}]

        result = build_gold(catalog, "Broken", TYPE, _table(broken))

        assert not result.published
        assert "missing required region" in result.problems[0]


class TestWhatKeepsTheDictPath:
    def test_a_fused_type_still_gets_rows(self, tmp_path):
        """Survivorship compares values row by row; there is nothing to
        gain by pretending otherwise."""
        from pyiceberg.catalog.sql import SqlCatalog
        warehouse = tmp_path / "w"
        warehouse.mkdir()
        catalog = SqlCatalog("t", uri=f"sqlite:///{tmp_path / 'c.db'}",
                              warehouse=f"file://{warehouse}")
        fused = {**TYPE, "additional_storage": {"other": {"silo": "q", "table": "x",
                                                           "id_column": "cust_pk"}}}

        result = build_gold(catalog, "Fused", fused, ROWS, additional_rows={"other": []})

        assert result.published and result.rows == len(ROWS)
