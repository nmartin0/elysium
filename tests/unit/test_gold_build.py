"""
Gold: one table per object type, audited before anyone can read it
(GOLD-2, MEDALLION_PIPELINE.md's G1 and G4).

Silver is one table per SOURCE TABLE, with the source's column names.
Gold is one table per OBJECT TYPE, keyed by the object's id, with the
ONTOLOGY'S property names -- the shape the ontology asks for. For a
type with one source that is a conform and nothing more, which is why
the ontology can move to gold before identity resolution exists.

WRITE, AUDIT, PUBLISH: new rows go to a branch, the audit runs there,
and only if it passes does one commit move main and tag the result. A
reader sees the previous publication until that instant.
"""

import sqlite3

import pytest
from pyiceberg.exceptions import NoSuchTableError

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.gold import audit, build_gold, conform, published_ids
from core.mirror.iceberg_sync import IcebergMirrorSync

CUSTOMER = {
    "id_field": "customer_id",
    "storage": {"silo": "p", "table": "customers", "id_column": "customer_id"},
    "fields": {
        "name": {"type": "data", "required": True},
        "region": {"type": "data", "column": "cust_region"},
        "transactions": {"type": "link", "target": "Transaction", "cardinality": "many",
                          "via_table": "transactions"},
    },
}


class TestConform:
    def test_columns_become_property_names(self):
        rows = conform(CUSTOMER, [{"customer_id": "c1", "name": "Ada", "cust_region": "us-west"}])

        assert rows == [{"customer_id": "c1", "name": "Ada", "region": "us-west"}]

    def test_a_reverse_link_is_not_a_column(self):
        """Computed from the other table; nothing on this row holds it."""
        rows = conform(CUSTOMER, [{"customer_id": "c1", "name": "Ada"}])

        assert "transactions" not in rows[0]

    def test_lineage_is_carried_forward(self):
        rows = conform(CUSTOMER, [{"customer_id": "c1", "_silo": "p", "_source_table": "customers",
                                   "_row_hash": "abc"}])

        assert rows[0]["_silo"] == "p" and rows[0]["_row_hash"] == "abc"


class TestTheAudit:
    def test_a_clean_build_has_nothing_to_say(self):
        assert audit(CUSTOMER, [{"customer_id": "c1", "name": "Ada"}], None) == []

    def test_a_missing_key(self):
        problems = audit(CUSTOMER, [{"customer_id": None, "name": "Ada"}], None)

        assert "no customer_id" in problems[0]

    def test_a_duplicate_key(self):
        rows = [{"customer_id": "c1", "name": "Ada"}, {"customer_id": "c1", "name": "Ada"}]

        assert "duplicate customer_id" in audit(CUSTOMER, rows, None)[0]

    def test_a_missing_required_property(self):
        problems = audit(CUSTOMER, [{"customer_id": "c1", "name": None}], None)

        assert "missing required name" in problems[0]

    def test_a_link_pointing_at_nothing(self):
        type_def = {**CUSTOMER, "fields": {**CUSTOMER["fields"],
                                           "owner": {"type": "link", "target": "Owner",
                                                     "cardinality": "one"}}}
        rows = [{"customer_id": "c1", "name": "Ada", "owner": "missing"}]

        problems = audit(type_def, rows, None, known_ids={"Owner": {"o1"}})

        assert "point at no Owner" in problems[0]

    def test_a_link_whose_target_has_no_gold_yet_is_not_a_finding(self):
        """A check that cannot run must not pretend to have passed OR
        to have failed."""
        type_def = {**CUSTOMER, "fields": {**CUSTOMER["fields"],
                                           "owner": {"type": "link", "target": "Owner",
                                                     "cardinality": "one"}}}

        assert audit(type_def, [{"customer_id": "c1", "name": "Ada", "owner": "o9"}], None) == []

    def test_losing_most_of_the_rows(self):
        rows = [{"customer_id": "c1", "name": "Ada"}]

        problems = audit(CUSTOMER, rows, previous_count=10)

        assert "of the last publication is gone" in problems[0]

    def test_a_normal_shrink_is_allowed(self):
        rows = [{"customer_id": f"c{n}", "name": "Ada"} for n in range(8)]

        assert audit(CUSTOMER, rows, previous_count=10) == []


@pytest.fixture
def mirrored(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, cust_region TEXT)")
    conn.executemany("INSERT INTO customers VALUES (?,?,?)",
                     [("c1", "Ada", "us-west"), ("c2", "Bram", "us-east")])
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": source})})
    columns = ["customer_id", "name", "cust_region"]
    sync.sync_table("p", "customers", "customer_id", columns, dict.fromkeys(columns, "string"))
    return sync


def _silver(sync):
    return sync._catalog.load_table("p.customers").scan().to_arrow().to_pylist()


def _gold(sync):
    return sync._catalog.load_table("gold.Customer")


class TestBuildingAndPublishing:
    def test_a_first_build_publishes_and_tags(self, mirrored):
        result = build_gold(mirrored._catalog, "Customer", CUSTOMER, _silver(mirrored))

        assert result.published and result.rows == 2
        assert "published-1" in _gold(mirrored).metadata.refs

    def test_the_table_holds_the_ontologys_shape(self, mirrored):
        build_gold(mirrored._catalog, "Customer", CUSTOMER, _silver(mirrored))

        rows = _gold(mirrored).scan().to_arrow()
        assert {"customer_id", "name", "region"} <= set(rows.column_names)
        assert "cust_region" not in rows.column_names

    def test_each_publication_is_tagged_in_turn(self, mirrored):
        build_gold(mirrored._catalog, "Customer", CUSTOMER, _silver(mirrored))
        build_gold(mirrored._catalog, "Customer", CUSTOMER, _silver(mirrored))

        refs = _gold(mirrored).metadata.refs
        assert "published-1" in refs and "published-2" in refs

    def test_a_failed_audit_publishes_nothing_and_leaves_main(self, mirrored):
        build_gold(mirrored._catalog, "Customer", CUSTOMER, _silver(mirrored))
        published = _gold(mirrored).current_snapshot().snapshot_id
        broken = [dict(row, name=None) for row in _silver(mirrored)]

        result = build_gold(mirrored._catalog, "Customer", CUSTOMER, broken)

        assert not result.published and "missing required name" in result.problems[0]
        after = _gold(mirrored)
        assert after.current_snapshot().snapshot_id == published
        assert all(row["name"] for row in after.scan().to_arrow().to_pylist())

    def test_and_leaves_no_audit_branch_behind(self, mirrored):
        build_gold(mirrored._catalog, "Customer", CUSTOMER, _silver(mirrored))
        build_gold(mirrored._catalog, "Customer", CUSTOMER,
                   [dict(row, name=None) for row in _silver(mirrored)])

        assert "audit" not in _gold(mirrored).metadata.refs

    def test_a_FIRST_build_that_fails_leaves_no_gold_at_all(self, mirrored):
        """No gold rather than unaudited gold."""
        broken = [dict(row, name=None) for row in _silver(mirrored)]

        result = build_gold(mirrored._catalog, "Customer", CUSTOMER, broken)

        assert not result.published
        with pytest.raises(NoSuchTableError):
            _gold(mirrored)

    def test_a_type_with_several_sources_needs_their_rows(self, mirrored):
        """SINCE GOLD-5 it is built, by joining the storages -- but
        building it from one side would publish objects missing every
        property the other side holds, so it refuses instead."""
        type_def = {**CUSTOMER, "additional_storage": {"other": {}}}

        result = build_gold(mirrored._catalog, "Customer", type_def, _silver(mirrored))

        assert result.skipped and "not supplied" in result.skipped

    def test_published_ids_reads_what_is_published(self, mirrored):
        build_gold(mirrored._catalog, "Customer", CUSTOMER, _silver(mirrored))

        assert published_ids(mirrored._catalog, "Customer", "customer_id") == {"c1", "c2"}

    def test_and_is_None_before_anything_is(self, mirrored):
        assert published_ids(mirrored._catalog, "Customer", "customer_id") is None
