"""Which source supplied each value of a golden record (R38).

`_fused_from` says which sources had something to say about an object;
the conflicts table says who LOST where two disagreed. Neither says who
supplied a value when nobody disagreed -- a customer fused from billing
and a CRM reported one silo for every field, including the ones the
CRM filled. `_field_sources` records the winner for every field.

THROUGH A REAL BUILD, as the conflicts reader is tested: what is read
back has to be what build_gold wrote.
"""

import json
import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.fusion import FIELD_SOURCES_COLUMN, fuse
from core.mirror.gold import build_gold
from core.mirror.gold_provenance import read_provenance
from core.mirror.iceberg_sync import IcebergMirrorSync

IDENTITY_TYPE = {
    "id_field": "customer_id",
    "security": {"field": "region"},
    "storage": {"silo": "b", "table": "customers", "id_column": "cust_pk"},
    "additional_storage": {"crm": {"silo": "c", "table": "contacts",
                                    "id_column": "contact_id"}},
    "identity": {"match_on": ["email"]},
    "fields": {
        "customer_id": {"type": "data", "column": "cust_pk"},
        "region": {"type": "data"},
        "email": {"type": "data"},
        "name": {"type": "data"},
        "phone": {"type": "data"},
    },
}


@pytest.fixture
def published(tmp_path):
    """Billing has the name and no phone; the CRM has both. Billing is
    preferred (declaration order), so the name is billing's and the
    phone is the CRM's -- the case `_silo` misreports."""
    billing, crm = tmp_path / "billing.db", tmp_path / "crm.db"
    for path, table, key, row in (
            (billing, "customers", "cust_pk", ("c1", "a@x.com", "us-west", "Ada", None)),
            (crm, "contacts", "contact_id", ("9f2a", "a@x.com", "us-west", "Ada Okafor", "555"))):
        conn = sqlite3.connect(path)
        conn.execute(f"CREATE TABLE {table} ({key} TEXT PRIMARY KEY, email TEXT, "
                     f"region TEXT, name TEXT, phone TEXT)")
        conn.execute(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?)", row)
        conn.commit()
        conn.close()
    sync = IcebergMirrorSync(tmp_path / "mirror", {
        "b": SQLiteReadAdapter({"path": billing}), "c": SQLiteReadAdapter({"path": crm})})
    for silo, table, key in (("b", "customers", "cust_pk"), ("c", "contacts", "contact_id")):
        columns = [key, "email", "region", "name", "phone"]
        sync.sync_table(silo, table, key, columns, dict.fromkeys(columns, "string"))
    silver = sync._catalog.load_table("b.customers").scan().to_arrow().to_pylist()
    contacts = sync._catalog.load_table("c.contacts").scan().to_arrow().to_pylist()
    result = build_gold(sync._catalog, "Customer", IDENTITY_TYPE, silver,
                        additional_rows={"crm": contacts})
    assert result.published, result.problems
    return sync


class TestThroughARealBuild:
    def test_every_value_names_the_source_that_supplied_it(self, published):
        provenance = read_provenance(published._catalog, "Customer", "customer_id", "c1")

        assert provenance["field_sources"] == {
            "email": "primary", "region": "primary", "name": "primary", "phone": "crm"}

    def test_it_is_in_gold_itself_not_computed_on_read(self, published):
        row = published._catalog.load_table("gold.Customer").scan().to_arrow().to_pylist()[0]

        assert json.loads(row[FIELD_SOURCES_COLUMN])["phone"] == "crm"

    def test_a_single_source_type_records_nothing(self, synced_deployment):
        """`silo` already answers it for every field there."""
        from core.mirror.catalog import open_mirror_catalog

        catalog = open_mirror_catalog(synced_deployment.data_dir / "mirror")
        provenance = read_provenance(catalog, "Customer", "customer_id", "cust_001")

        assert provenance["silo"]
        assert provenance["field_sources"] is None


class TestTheJoinPath:
    """GOLD-5's fusion: each field has one home, so its home supplied it
    -- unless the object is absent there, or the value is null."""

    TYPE = {
        "id_field": "customer_id",
        "storage": {"silo": "a", "table": "customers", "id_column": "customer_id"},
        "additional_storage": {"risk_db": {"silo": "r", "table": "risk",
                                           "id_column": "cust_ref"}},
        "fields": {"name": {"type": "data"}, "nickname": {"type": "data"},
                   "risk_score": {"type": "data", "storage": "risk_db", "column": "score"}},
    }

    def _sources(self, rows):
        return [json.loads(row[FIELD_SOURCES_COLUMN]) for row in rows]

    def test_each_field_names_its_storage(self):
        rows = fuse(self.TYPE, {None: [{"customer_id": "c1", "name": "Ada", "nickname": "A"}],
                                "risk_db": [{"cust_ref": "c1", "score": 0.3}]})

        assert self._sources(rows) == [{"name": "primary", "nickname": "primary",
                                        "risk_score": "risk_db"}]

    def test_a_null_or_an_absent_storage_supplied_nothing(self):
        rows = fuse(self.TYPE, {None: [{"customer_id": "c1", "name": "Ada", "nickname": None}],
                                "risk_db": []})

        assert self._sources(rows) == [{"name": "primary"}]


def test_an_unreadable_record_is_no_answer_not_a_guess(published):
    table = published._catalog.load_table("gold.Customer")
    rows = table.scan().to_arrow().to_pylist()
    rows[0][FIELD_SOURCES_COLUMN] = "{not json"
    import pyarrow as pa

    table.overwrite(pa.Table.from_pylist(rows, schema=table.schema().as_arrow()))

    assert read_provenance(published._catalog, "Customer", "customer_id",
                           "c1")["field_sources"] is None
