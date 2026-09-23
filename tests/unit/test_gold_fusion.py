"""
One object from several storages (GOLD-5).

AUDITED BEFORE DESIGNING, and it changed the shape of the work.
Elysium's schema gives each storage its OWN id_column, and each field
names EXACTLY ONE storage -- so a type spanning two databases is a
JOIN, not a survivorship contest. Per-property conflicts, and the MAC
conflict decision D2 governs, arise when two sources describe the same
entity INDEPENDENTLY, which is identity resolution (GOLD-6).

THE JOIN IS OUTER, deliberately: an object in one storage and not the
other is a real thing -- a customer with no risk score yet -- and
dropping it would silently lose an object that exists.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.fusion import FUSED_FROM_COLUMN, fields_by_storage, fuse
from core.mirror.gold import build_gold
from core.mirror.iceberg_sync import IcebergMirrorSync

TYPE = {
    "id_field": "customer_id",
    "security": {"field": "region"},
    "storage": {"silo": "p", "table": "customers", "id_column": "cust_pk"},
    "additional_storage": {"risk": {"silo": "r", "table": "risk_scores",
                                     "id_column": "cust_ref"}},
    "fields": {
        "customer_id": {"type": "data", "column": "cust_pk"},
        "region": {"type": "data"},
        "name": {"type": "data"},
        "risk_score": {"type": "data", "storage": "risk", "column": "score"},
    },
}
PRIMARY = [("c1", "us-west", "Ada"), ("c2", "us-east", "Ben"), ("c3", "eu", "Cleo")]
RISK = [("c1", "12"), ("c2", "83"), ("c9", "40")]   # c3 absent, c9 only here


class TestTheJoinItself:
    def _rows(self):
        return {
            None: [{"cust_pk": pk, "region": region, "name": name}
                    for pk, region, name in PRIMARY],
            "risk": [{"cust_ref": ref, "score": score} for ref, score in RISK],
        }

    def test_each_field_comes_from_the_storage_that_declares_it(self):
        fused = {row["customer_id"]: row for row in fuse(TYPE, self._rows())}

        assert fused["c1"]["name"] == "Ada" and fused["c1"]["risk_score"] == "12"

    def test_an_object_missing_from_one_storage_is_kept(self):
        """A customer with no risk score yet still exists."""
        fused = {row["customer_id"]: row for row in fuse(TYPE, self._rows())}

        assert fused["c3"]["name"] == "Cleo" and fused["c3"]["risk_score"] is None

    def test_an_object_present_only_in_the_SECOND_storage_is_kept(self):
        """Dropping it would silently lose an object that exists."""
        fused = {row["customer_id"]: row for row in fuse(TYPE, self._rows())}

        assert fused["c9"]["risk_score"] == "40" and fused["c9"]["name"] is None

    def test_each_row_names_the_storages_that_contributed(self):
        fused = {row["customer_id"]: row for row in fuse(TYPE, self._rows())}

        assert fused["c1"][FUSED_FROM_COLUMN] == "primary,risk"
        assert fused["c3"][FUSED_FROM_COLUMN] == "primary"
        assert fused["c9"][FUSED_FROM_COLUMN] == "risk"

    def test_the_storages_are_keyed_by_their_OWN_id_columns(self):
        """cust_pk in one database, cust_ref in the other -- which the
        schema already lets a deployment say."""
        fused = fuse(TYPE, self._rows())

        assert {row["customer_id"] for row in fused} == {"c1", "c2", "c3", "c9"}

    def test_the_order_is_reproducible(self):
        """Primary first, then anything seen only elsewhere -- not
        dictionary iteration order."""
        assert [row["customer_id"] for row in fuse(TYPE, self._rows())] == \
            ["c1", "c2", "c3", "c9"]

    def test_a_row_with_no_id_is_left_out_rather_than_guessed_at(self):
        rows = self._rows()
        rows["risk"].append({"cust_ref": None, "score": "99"})

        fused = fuse(TYPE, rows)

        assert all(row["customer_id"] is not None for row in fused)
        assert len(fused) == 4

    def test_fields_are_grouped_by_the_storage_that_holds_them(self):
        grouped = fields_by_storage(TYPE)

        assert set(grouped[None]) == {"customer_id", "region", "name"}
        assert grouped["risk"] == ["risk_score"]


@pytest.fixture
def two_databases(tmp_path):
    primary, risk = tmp_path / "p.db", tmp_path / "r.db"
    conn = sqlite3.connect(primary)
    conn.execute("CREATE TABLE customers (cust_pk TEXT PRIMARY KEY, region TEXT, name TEXT)")
    conn.executemany("INSERT INTO customers VALUES (?,?,?)", PRIMARY)
    conn.commit()
    conn.close()
    conn = sqlite3.connect(risk)
    conn.execute("CREATE TABLE risk_scores (cust_ref TEXT PRIMARY KEY, score TEXT)")
    conn.executemany("INSERT INTO risk_scores VALUES (?,?)", RISK)
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "mirror", {
        "p": SQLiteReadAdapter({"path": primary}),
        "r": SQLiteReadAdapter({"path": risk}),
    })
    sync.sync_table("p", "customers", "cust_pk", ["cust_pk", "region", "name"],
                    dict.fromkeys(["cust_pk", "region", "name"], "string"))
    sync.sync_table("r", "risk_scores", "cust_ref", ["cust_ref", "score"],
                    {"cust_ref": "string", "score": "string"})
    return sync


def _silver(sync):
    return (sync._catalog.load_table("p.customers").scan().to_arrow().to_pylist(),
            {"risk": sync._catalog.load_table("r.risk_scores").scan().to_arrow().to_pylist()})


class TestThroughARealBuild:
    def test_a_type_spanning_two_databases_publishes(self, two_databases):
        silver, additional = _silver(two_databases)

        result = build_gold(two_databases._catalog, "Customer", TYPE, silver,
                             additional_rows=additional)

        assert result.published and result.rows == 4

    def test_the_gold_table_holds_both_databases_properties(self, two_databases):
        silver, additional = _silver(two_databases)
        build_gold(two_databases._catalog, "Customer", TYPE, silver, additional_rows=additional)

        rows = {row["customer_id"]: row for row in
                two_databases._catalog.load_table("gold.Customer").scan().to_arrow().to_pylist()}

        assert rows["c1"]["name"] == "Ada" and rows["c1"]["risk_score"] == "12"

    def test_a_required_property_missing_from_the_other_side_REFUSES(self, two_databases):
        """The audit already checks required properties; fusion just
        lets it see the case."""
        silver, additional = _silver(two_databases)
        strict = {**TYPE, "fields": {**TYPE["fields"],
                                      "risk_score": {**TYPE["fields"]["risk_score"],
                                                     "required": True}}}

        result = build_gold(two_databases._catalog, "Customer", strict, silver,
                             additional_rows=additional)

        assert not result.published
        assert "missing required risk_score" in result.problems[0]

    def test_without_the_other_rows_it_refuses_rather_than_publishing_half(self, two_databases):
        """A fused type built from one side would publish an object
        missing every property the other side holds."""
        silver, _ = _silver(two_databases)

        result = build_gold(two_databases._catalog, "Customer", TYPE, silver)

        assert not result.published and result.skipped
