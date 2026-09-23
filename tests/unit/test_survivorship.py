"""
Choosing between two sources' versions of one property (GOLD-6).

THE QUESTION GOLD-5 COULD NOT ASK: there each property had exactly one
home, so a type spanning storages was a join. Once identity resolution
decides billing's `c1` and the CRM's `9f2a` are one customer, both may
hold a name.

SURVIVORSHIP IS PER ATTRIBUTE, not per record -- the MDM practice this
project recorded: "trusted source, most recent, most frequent, most
complete -- usually mixed by attribute". A record-level "the CRM wins"
is the wrong shape, because the CRM may have the better address and
the worse phone number.

AND THE LOSING VALUE IS KEPT: "deleting losing values destroys trust".
A person asking why the golden record says Leeds must be able to see
that the CRM said Hull and was outranked.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.gold import build_gold
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.identity import resolve
from core.mirror.survivorship import PROPERTY_CONFLICT, SECURITY_CONFLICT, fuse_entities

TYPE = {
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


def _fuse(type_def, billing, crm):
    return fuse_entities(type_def, resolve(type_def, {None: billing, "crm": crm}))


class TestChoosingAValue:
    def test_the_declaration_order_wins_by_default(self):
        """Primary storage first, then additional as written."""
        fused = _fuse(TYPE,
                       [{"cust_pk": "c1", "email": "a@x", "region": "us-west", "name": "Ada"}],
                       [{"contact_id": "9f2a", "email": "a@x", "region": "us-west",
                         "name": "Ada Okafor"}])

        assert fused.rows[0]["name"] == "Ada"

    def test_a_declared_preference_changes_it(self):
        type_def = {**TYPE, "survivorship": {"prefer": ["crm"]}}

        fused = _fuse(type_def,
                       [{"cust_pk": "c1", "email": "a@x", "region": "us-west", "name": "Ada"}],
                       [{"contact_id": "9f2a", "email": "a@x", "region": "us-west",
                         "name": "Ada Okafor"}])

        assert fused.rows[0]["name"] == "Ada Okafor"

    def test_PER_FIELD_beats_per_type(self):
        """The CRM may have the better address and the worse phone."""
        type_def = {**TYPE, "survivorship": {"prefer": ["crm"]},
                     "fields": {**TYPE["fields"],
                                "phone": {"type": "data", "survivorship": {"prefer": [None]}}}}

        fused = _fuse(type_def,
                       [{"cust_pk": "c1", "email": "a@x", "region": "us-west",
                         "name": "Ada", "phone": "0113"}],
                       [{"contact_id": "9f2a", "email": "a@x", "region": "us-west",
                         "name": "Ada Okafor", "phone": "0114"}])

        assert fused.rows[0]["name"] == "Ada Okafor"
        assert fused.rows[0]["phone"] == "0113"

    def test_a_null_never_wins_over_a_value(self):
        """A source with nothing to say must not blank the property --
        'most complete' as the default."""
        type_def = {**TYPE, "survivorship": {"prefer": ["crm"]}}

        fused = _fuse(type_def,
                       [{"cust_pk": "c1", "email": "a@x", "region": "us-west", "name": "Ada"}],
                       [{"contact_id": "9f2a", "email": "a@x", "region": "us-west",
                         "name": None}])

        assert fused.rows[0]["name"] == "Ada"

    def test_an_unmerged_entity_keeps_its_own_values(self):
        fused = _fuse(TYPE,
                       [{"cust_pk": "c1", "email": "a@x", "region": "us-west", "name": "Ada"}],
                       [{"contact_id": "7c1b", "email": "z@x", "region": "eu", "name": "Zoe"}])

        rows = {row["customer_id"]: row for row in fused.rows}
        assert rows["c1"]["name"] == "Ada" and rows["crm:7c1b"]["name"] == "Zoe"

    def test_each_row_names_the_sources_it_came_from(self):
        fused = _fuse(TYPE,
                       [{"cust_pk": "c1", "email": "a@x", "region": "us-west", "name": "Ada"}],
                       [{"contact_id": "9f2a", "email": "a@x", "region": "us-west",
                         "name": "Ada"}])

        assert fused.rows[0]["_fused_from"] == "crm,primary"


class TestKeepingTheLosers:
    def test_a_disagreement_is_recorded_with_both_sides(self):
        fused = _fuse(TYPE,
                       [{"cust_pk": "c1", "email": "a@x", "region": "us-west", "name": "Ada"}],
                       [{"contact_id": "9f2a", "email": "a@x", "region": "us-west",
                         "name": "Ada Okafor"}])

        conflict = fused.conflicts[0]
        assert conflict.kind == PROPERTY_CONFLICT and conflict.field_name == "name"
        assert conflict.chosen == "Ada" and conflict.chosen_source == "primary"
        assert conflict.losing == "Ada Okafor" and conflict.losing_source == "crm"

    def test_a_source_holding_NOTHING_is_not_a_disagreement(self):
        """Beating a null is not winning an argument.

        WRITTEN BECAUSE A CONTROL PROVED NOTHING: removing the null
        guard changed no result when the empty source came FIRST, so
        the test passed against a mutation. It only shows when the
        empty source comes second -- and then the record fills with
        "Ada beat nothing", which is noise in exactly the table an
        operator reads to understand a disagreement.
        """
        fused = _fuse(TYPE,
                       [{"cust_pk": "c1", "email": "a@x", "region": "us-west", "name": "Ada"}],
                       [{"contact_id": "9f2a", "email": "a@x", "region": "us-west",
                         "name": None}])

        assert fused.rows[0]["name"] == "Ada"
        assert fused.conflicts == []

    def test_agreement_records_nothing(self):
        fused = _fuse(TYPE,
                       [{"cust_pk": "c1", "email": "a@x", "region": "us-west", "name": "Ada"}],
                       [{"contact_id": "9f2a", "email": "a@x", "region": "us-west",
                         "name": "Ada"}])

        assert fused.conflicts == []

    def test_a_refused_merge_is_recorded_as_one_too(self):
        """D2's refusals travel with the property conflicts, so an
        operator has one place to look."""
        fused = _fuse(TYPE,
                       [{"cust_pk": "c1", "email": "a@x", "region": "us-west"}],
                       [{"contact_id": "9f2a", "email": "a@x", "region": "eu"}])

        kinds = [conflict.kind for conflict in fused.conflicts]
        assert SECURITY_CONFLICT in kinds


@pytest.fixture
def two_databases(tmp_path):
    billing, crm = tmp_path / "b.db", tmp_path / "c.db"
    conn = sqlite3.connect(billing)
    conn.execute("CREATE TABLE customers (cust_pk TEXT PRIMARY KEY, email TEXT, "
                 "region TEXT, name TEXT)")
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?)",
                     [("c1", "ada@x.com", "us-west", "Ada"),
                      ("c2", "ben@x.com", "us-east", "Ben")])
    conn.commit()
    conn.close()
    conn = sqlite3.connect(crm)
    conn.execute("CREATE TABLE contacts (contact_id TEXT PRIMARY KEY, email TEXT, "
                 "region TEXT, name TEXT)")
    conn.executemany("INSERT INTO contacts VALUES (?,?,?,?)",
                     [("9f2a", "ada@x.com", "us-west", "Ada Okafor"),
                      ("7c1b", "zoe@x.com", "eu", "Zoe"),
                      ("3d0e", "ben@x.com", "eu", "Ben C")])
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "mirror", {
        "b": SQLiteReadAdapter({"path": billing}), "c": SQLiteReadAdapter({"path": crm})})
    columns = ["cust_pk", "email", "region", "name"]
    sync.sync_table("b", "customers", "cust_pk", columns, dict.fromkeys(columns, "string"))
    contact_columns = ["contact_id", "email", "region", "name"]
    sync.sync_table("c", "contacts", "contact_id", contact_columns,
                    dict.fromkeys(contact_columns, "string"))
    return sync


def _build(sync, type_def):
    silver = sync._catalog.load_table("b.customers").scan().to_arrow().to_pylist()
    crm = sync._catalog.load_table("c.contacts").scan().to_arrow().to_pylist()
    return build_gold(sync._catalog, "Customer", type_def, silver, additional_rows={"crm": crm})


class TestThroughARealBuild:
    def test_it_publishes_one_row_per_entity(self, two_databases):
        result = _build(two_databases, {**TYPE, "survivorship": {"prefer": ["crm"]}})

        assert result.published
        # c1 merged; c2 and the CRM's Ben left apart by D2; Zoe alone.
        assert result.rows == 4 and result.merged == 1 and result.refused_merges == 1

    def test_the_conflicts_are_WRITTEN_not_merely_counted(self, two_databases):
        """A record that exists only as a number is not a record."""
        _build(two_databases, {**TYPE, "survivorship": {"prefer": ["crm"]}})

        rows = two_databases._catalog.load_table(
            "gold_conflicts.Customer").scan().to_arrow().to_pylist()

        kinds = {row["kind"] for row in rows}
        assert kinds == {PROPERTY_CONFLICT, SECURITY_CONFLICT}
        name_conflict = next(row for row in rows if row["field"] == "name")
        assert name_conflict["chosen"] == "Ada Okafor" and name_conflict["losing"] == "Ada"

    def test_conflicts_accumulate_rather_than_being_rewritten(self, two_databases):
        type_def = {**TYPE, "survivorship": {"prefer": ["crm"]}}
        _build(two_databases, type_def)
        _build(two_databases, type_def)

        rows = two_databases._catalog.load_table(
            "gold_conflicts.Customer").scan().to_arrow().to_pylist()

        assert len(rows) == 4

    def test_the_merged_entity_keeps_the_primary_sources_id(self, two_databases):
        _build(two_databases, {**TYPE, "survivorship": {"prefer": ["crm"]}})

        rows = {row["customer_id"] for row in two_databases._catalog.load_table(
            "gold.Customer").scan().to_arrow().to_pylist()}

        assert "c1" in rows and "crm:9f2a" not in rows
