"""Erasure and the tables of types the ontology no longer has, at the level of
the lake itself: a catalog built by hand, so each case is exactly one fact.

The end-to-end case (a real sync, a removed type, an erasure) is
tests/integration/test_erasure_after_removal.py.
"""

import copy
import json
import sqlite3

import pyarrow as pa
import pytest

from core.mirror.catalog import open_mirror_catalog
from core.mirror.erasure import (
    ErasureRegister,
    apply_erasures,
    cascade,
    erased_mask,
    record_key_columns,
    recorded_columns,
    recorded_key_columns,
    survey,
    table_key_columns,
)


@pytest.fixture
def lake(tmp_path):
    catalog = open_mirror_catalog(tmp_path / "mirror")

    def make(identifier, rows):
        try:
            catalog.create_namespace(identifier.split(".")[0])
        except Exception:  # noqa: BLE001 - already there
            pass
        data = pa.Table.from_pylist(rows)
        catalog.create_table(identifier, schema=data.schema).append(data)

    catalog.make = make
    catalog.dir = tmp_path
    return catalog


def _type(table, id_column, **fields):
    return {"id_field": id_column, "storage": {"silo": "s", "table": table, "id_column": id_column},
            "fields": {id_column: {"type": "string"}, **fields}}


def _link(target, column=None):
    return {"type": "link", "target": target, "cardinality": "one", **({"column": column} if column else {})}


CUSTOMER = _type("customers", "customer_id")
FULL = {"Customer": CUSTOMER, "Ticket": _type("tickets", "ticket_id", customer=_link("Customer", "cust"))}
WITHOUT_TICKET = {"Customer": CUSTOMER}


def _rows(catalog, identifier):
    return catalog.load_table(identifier).scan().to_arrow().to_pylist()


def _erase(lake, schema, keys):
    register = ErasureRegister(lake.dir / "erasures.db")
    register.record(keys, "tester", "test")
    return register, apply_erasures(lake, schema, register, lake.dir / "mirror")


class TestAFormerLinkingTypesRowsAreFoundThroughItsLinks:
    @pytest.fixture
    def removed_ticket(self, lake):
        lake.make("s.customers", [{"customer_id": "c1"}, {"customer_id": "c2"}])
        lake.make("s.tickets", [{"ticket_id": "t1", "cust": "c1", "body": "c1 text"},
                                {"ticket_id": "t2", "cust": "c2", "body": "x"}])
        lake.make("changelog_s.tickets", [{"ticket_id": "t1", "cust": "c1", "_change": "update"}])
        lake.make("gold.Customer", [{"customer_id": "c1"}, {"customer_id": "c2"}])
        lake.make("gold.Ticket", [{"ticket_id": "t1", "customer": "c1"}, {"ticket_id": "t2", "customer": "c2"}])
        lake.make("gold_history.Ticket", [{"ticket_id": "t1", "values": json.dumps({"customer": "c1"})}])
        lake.make("gold_conflicts.Ticket", [{"entity_id": "t1", "detail": "c1 text"}])
        lake.make("quarantine_s.tickets", [{"object_id": "t1", "value": "c1 text"}])
        lake.make("cleaning_s.tickets", [{"object_id": "t1", "column": "body"}])
        record_key_columns(lake, FULL)                      # a sync while Ticket existed
        record_key_columns(lake, WITHOUT_TICKET)            # a sync after it was removed
        return lake

    def test_the_cascade_reaches_the_removed_types_rows(self, removed_ticket):
        assert cascade(removed_ticket, WITHOUT_TICKET, [("Customer", "c1")]) == [
            ("Customer", "c1"), ("Ticket", "t1")]

    def test_erasing_the_customer_takes_the_removed_types_history_conflicts_and_findings(
            self, removed_ticket):
        keys = cascade(removed_ticket, WITHOUT_TICKET, [("Customer", "c1")])

        register, result = _erase(removed_ticket, WITHOUT_TICKET, keys)

        for table in ("s.tickets", "changelog_s.tickets", "gold.Ticket", "gold_history.Ticket",
                      "gold_conflicts.Ticket", "quarantine_s.tickets", "cleaning_s.tickets"):
            assert all("t1" not in map(str, row.values()) for row in _rows(removed_ticket, table)), table
        assert [row["ticket_id"] for row in _rows(removed_ticket, "gold.Ticket")] == ["t2"]    # CONTROL
        assert result.reach.incomplete == [] and register.incomplete() == []

    def test_a_table_that_never_recorded_its_links_cannot_be_followed_and_says_so(self, lake):
        lake.make("s.customers", [{"customer_id": "c1"}])
        lake.make("s.tickets", [{"ticket_id": "t1", "cust": "c1"}])
        # recorded once, as the first version of the record (keys only)
        with lake.load_table("s.tickets").transaction() as tx:
            tx.set_properties({"elysium.erasure_keys": json.dumps({"ticket_id": ["Ticket"], "cust": ["Customer"]})})

        assert cascade(lake, WITHOUT_TICKET, [("Customer", "c1")]) == [("Customer", "c1")]
        assert "s.tickets" in survey(lake, WITHOUT_TICKET).partly_known


class TestWhatRecordingNeverForgets:
    SHARED = {"Account": _type("people", "acct"),
              "Lead": {**_type("people", "lead_ref"), "id_field": "lead_ref"}}
    AFTER = {"Account": SHARED["Account"]}

    def test_a_narrower_but_nonempty_answer_does_not_narrow_the_record(self, lake):
        lake.make("s.people", [{"acct": "a1", "lead_ref": "L1"}])
        record_key_columns(lake, self.SHARED)
        record_key_columns(lake, self.AFTER)                # Lead removed; Account still reads the table

        assert recorded_key_columns(lake.load_table("s.people")) == {
            "acct": {"Account"}, "lead_ref": {"Lead"}}

    def test_and_so_the_removed_types_column_is_searched(self, lake):
        lake.make("s.people", [{"acct": "a1", "lead_ref": "L1"}, {"acct": "a2", "lead_ref": "L2"}])
        record_key_columns(lake, self.SHARED)
        record_key_columns(lake, self.AFTER)

        _register, _result = _erase(lake, self.AFTER, [("Lead", "L1")])

        assert [row["acct"] for row in _rows(lake, "s.people")] == ["a2"]

    def test_a_shared_table_written_before_the_record_is_reported_partly_known(self, lake):
        """The removed type's other columns cannot be known, and the schema's
        non-empty answer must not read as 'searched'."""
        lake.make("s.people", [{"acct": "a1", "lead_ref": "L1"}])
        lake.make("changelog_s.people", [{"acct": "a1", "lead_ref": "L1", "_change": "update"}])

        register, result = _erase(lake, self.AFTER, [("Lead", "L1")])

        assert result.partly_known_tables == ["changelog_s.people", "s.people"]
        assert result.unreachable_tables == {}
        assert register.incomplete() == ["changelog_s.people", "s.people"]
        assert not register.unpurged()
        assert [row["lead_ref"] for row in _rows(lake, "s.people")] == ["L1"]   # honestly: not erased

    def test_the_next_sync_that_records_it_clears_the_report(self, lake):
        lake.make("s.people", [{"acct": "a1", "lead_ref": "L1"}])
        register, _result = _erase(lake, self.AFTER, [("Account", "a1")])
        assert register.incomplete() == ["s.people"]

        record_key_columns(lake, self.AFTER)
        apply_erasures(lake, self.AFTER, register, lake.dir / "mirror")

        assert register.incomplete() == []


class TestAColumnRePointedAtAnotherType:
    def _schema(self, owner_target):
        return {"Customer": _type("customers", "cid"), "Employee": _type("employees", "eid"),
                "Ticket": _type("tickets", "ticket_id", owner=_link(owner_target))}

    def test_the_over_erasure_is_shown_not_hidden_and_not_narrowed(self, lake):
        lake.make("s.tickets", [{"ticket_id": "t1", "owner": "5"}, {"ticket_id": "t2", "owner": "6"}])
        record_key_columns(lake, self._schema("Customer"))
        record_key_columns(lake, self._schema("Employee"))

        assert survey(lake, self._schema("Employee"), {"Customer"}).stale == [
            ("s.tickets", "owner", "Customer")]
        assert survey(lake, self._schema("Employee"), {"Employee"}).stale == []
        _register, result = _erase(lake, self._schema("Employee"), [("Customer", "5")])

        assert result.reach.stale == [("s.tickets", "owner", "Customer")]
        assert [row["ticket_id"] for row in _rows(lake, "s.tickets")] == ["t2"]   # the documented limit


class TestQuarantineAndCleaningOfOtherStorages:
    ADDITIONAL = {"Customer": {**CUSTOMER, "additional_storage": {
        "crm": {"silo": "s", "table": "details", "id_column": "cust_ref"}}}}

    def test_an_additional_storages_findings_are_keyed_by_the_type(self):
        for layer in ("quarantine_s.details", "cleaning_s.details"):
            assert table_key_columns(self.ADDITIONAL, layer) == {"object_id": {"Customer"}}

    def test_a_join_tables_findings_name_both_ends_and_the_composite_id_is_split(self, lake):
        schema = {"C": {**_type("c", "id"), "fields": {"id": {"type": "string"}, "tags": {
            "type": "link", "target": "T", "via_table": "c_t", "via_column": "cid",
            "via_target_column": "tid"}}}, "T": _type("t", "tid2")}
        assert table_key_columns(schema, "quarantine_s.c_t") == {"object_id": {"C", "T"}}
        lake.make("quarantine_s.c_t", [{"object_id": "c9\x1ft9"}, {"object_id": "c1\x1ft1"}])
        register = ErasureRegister(lake.dir / "erasures.db")
        register.record([("T", "t9")], "tester", "test")
        table = lake.load_table("quarantine_s.c_t").scan().to_arrow()

        assert erased_mask(table, {"object_id": {"C", "T"}}, register.hasher(),
                           register.hashes_by_type()) == [True, False]


class TestAGoldJoinCopyWhoseNameTwoSilosShare:
    def test_it_is_reported_partly_known_not_guessed(self, lake):
        def join(silo):
            return {"fields": {"tags": {"type": "link", "target": "T", "via_table": "links",
                                        "via_column": "cid", "via_target_column": "tid"}},
                    "id_field": "id", "storage": {"silo": silo, "table": "c", "id_column": "id"}}
        schema = {"C1": join("s1"), "C2": join("s2"), "T": _type("t", "tid")}
        lake.make("gold.links", [{"cid": "c", "tid": "t"}])
        record_key_columns(lake, schema)

        assert survey(lake, schema).partly_known == ["gold.links"]


class TestATableThatCannotBeRead:
    def test_it_is_named_with_the_kind_and_erasure_goes_on(self, lake):
        lake.make("s.customers", [{"customer_id": "c1"}, {"customer_id": "c2"}])
        lake.make("s.broken", [{"x": 1}])
        record_key_columns(lake, WITHOUT_TICKET)
        for path in (lake.dir / "mirror").rglob("*.metadata.json"):
            if "broken" in str(path):
                path.unlink()

        register, result = _erase(lake, WITHOUT_TICKET, [("Customer", "c1")])

        assert list(result.unreachable_tables) == ["s.broken"]
        assert "cannot be read" in result.unreachable_tables["s.broken"]
        assert str(lake.dir) not in result.unreachable_tables["s.broken"]       # the kind, never the path
        assert [row["customer_id"] for row in _rows(lake, "s.customers")] == ["c2"]
        assert register.incomplete() == ["s.broken"]


class TestTheRegisterAcrossAnUpgrade:
    def test_a_register_made_before_the_column_existed_still_works(self, tmp_path):
        path = tmp_path / "erasures.db"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE erasures (key_hash TEXT NOT NULL, object_type TEXT NOT NULL, "
                         "erasure_id TEXT NOT NULL, requested_by TEXT NOT NULL, reason TEXT NOT NULL, "
                         "requested_at REAL NOT NULL, purged_at REAL, source_cleared_at REAL, "
                         "PRIMARY KEY (key_hash, object_type))")
            conn.execute("INSERT INTO erasures VALUES ('h', 'Customer', 'e1', 'u', 'r', 1.0, 2.0, NULL)")
        register = ErasureRegister(path)

        assert register.incomplete() == [] and register.erasures()[0].incomplete_tables == ()
        register.mark_purged(["gold.Tag"])
        assert register.erasures()[0].incomplete_tables == ("gold.Tag",)
        register.mark_purged([])
        assert register.incomplete() == []

    def test_what_is_recorded_names_tables_only(self, tmp_path):
        register = ErasureRegister(tmp_path / "erasures.db")
        register.record([("Customer", "c1")], "tester", "test")
        register.mark_purged(["gold.Tag"])

        assert b"c1" not in (tmp_path / "erasures.db").read_bytes()


def test_the_record_carries_the_identity_and_links_of_the_tables_own_rows(lake):
    lake.make("s.tickets", [{"ticket_id": "t1", "cust": "c1"}])
    record_key_columns(lake, FULL)

    recorded = recorded_columns(lake.load_table("s.tickets"))
    assert recorded.ids == {"ticket_id": {"Ticket"}} and recorded.links == {"cust": {"Customer"}}
    assert recorded.present
    assert copy.deepcopy(recorded.keys) == {"ticket_id": {"Ticket"}, "cust": {"Customer"}}
