"""Erasure and the tables of types the ontology no longer has, at the level of
the lake itself: a catalog built by hand, so each case is exactly one fact.

The end-to-end case (a real sync, a removed type, an erasure) is
tests/integration/test_erasure_after_removal.py.
"""

import json
import sqlite3
import time

import pyarrow as pa
import pytest

from core.mirror.catalog import open_mirror_catalog
from core.mirror.erasure import (
    ErasureRegister,
    adopt_all_current,
    adopt_table,
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


#: A time no table is newer than, and one every table is: the first says "these
#: tables existed before the sync that records them", the second "it made them".
EXISTED_BEFORE = time.time() + 3600
CREATED_BY_IT = 0.0


def _erase(lake, schema, keys, seeds=None):
    register = ErasureRegister(lake.dir / "erasures.db")
    register.record(keys, "tester", "test", seeds=seeds)
    return register, apply_erasures(lake, schema, register, lake.dir / "mirror")


def _legacy(lake, schema, identifiers=None):
    """Tables as a sync BEFORE the record left them: the first form, keys only."""
    for namespace in lake.list_namespaces():
        for parts in lake.list_tables(namespace):
            identifier = ".".join(parts)
            if identifiers is None or identifier in identifiers:
                with lake.load_table(identifier).transaction() as tx:
                    tx.set_properties({"elysium.erasure_keys": json.dumps(
                        {c: sorted(t) for c, t in table_key_columns(schema, identifier).items()})})


TICKET_TABLES = ("s.tickets", "changelog_s.tickets", "gold.Ticket", "gold_history.Ticket",
                 "gold_conflicts.Ticket", "quarantine_s.tickets", "cleaning_s.tickets")


@pytest.fixture
def ticket_lake(lake):
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
    return lake


class TestAFormerLinkingTypesRowsAreFoundThroughItsLinks:
    @pytest.fixture
    def removed_ticket(self, ticket_lake):
        record_key_columns(ticket_lake, FULL, created_since=CREATED_BY_IT)       # a sync that made them
        record_key_columns(ticket_lake, WITHOUT_TICKET, created_since=CREATED_BY_IT)   # and one after the removal
        return ticket_lake

    def test_the_cascade_reaches_the_removed_types_rows(self, removed_ticket):
        assert cascade(removed_ticket, WITHOUT_TICKET, [("Customer", "c1")]) == [
            ("Customer", "c1"), ("Ticket", "t1")]

    def test_erasing_the_customer_takes_the_removed_types_history_conflicts_and_findings(
            self, removed_ticket):
        keys = cascade(removed_ticket, WITHOUT_TICKET, [("Customer", "c1")])

        register, result = _erase(removed_ticket, WITHOUT_TICKET, keys, seeds=[("Customer", "c1")])

        for table in TICKET_TABLES:
            assert all("t1" not in map(str, row.values()) for row in _rows(removed_ticket, table)), table
        assert [row["ticket_id"] for row in _rows(removed_ticket, "gold.Ticket")] == ["t2"]    # CONTROL
        assert result.reach.incomplete == [] and register.incomplete() == []

    def test_only_the_links_the_removed_type_owns_are_followed(self, lake):
        """Account (still there) links Customer; Lead (removed) shares the table and has no link."""
        shared = {"Customer": CUSTOMER, "Account": _type("people", "acct", owner=_link("Customer")),
                  "Lead": _type("people", "lead_ref")}
        lake.make("s.people", [{"acct": "a1", "lead_ref": "L1", "owner": "c1"}])
        record_key_columns(lake, shared, created_since=CREATED_BY_IT)
        after = {name: shared[name] for name in ("Customer", "Account")}
        record_key_columns(lake, after, created_since=CREATED_BY_IT)

        assert cascade(lake, after, [("Customer", "c1")]) == [("Customer", "c1")]

    def test_a_table_that_never_recorded_its_links_cannot_be_followed_and_says_so(self, ticket_lake):
        _legacy(ticket_lake, FULL, {"s.tickets"})

        assert cascade(ticket_lake, WITHOUT_TICKET, [("Customer", "c1")]) == [("Customer", "c1")]
        assert "s.tickets" in survey(ticket_lake, WITHOUT_TICKET).partly_known


class TestWhatASyncCanAndCannotMakeKnown:
    """A record holds what the schema mapped the day it was written. It cannot
    recover the columns of a type removed before: only an operator can."""

    def test_a_table_the_recording_sync_created_is_complete(self, ticket_lake):
        record_key_columns(ticket_lake, FULL, created_since=CREATED_BY_IT)

        assert recorded_columns(ticket_lake.load_table("s.tickets")).complete
        assert survey(ticket_lake, FULL).partly_known == []

    def test_a_table_that_already_held_data_is_partial(self, ticket_lake):
        record_key_columns(ticket_lake, FULL, created_since=EXISTED_BEFORE)

        assert not recorded_columns(ticket_lake.load_table("s.tickets")).complete
        assert "s.tickets" in survey(ticket_lake, FULL).partly_known

    def test_a_later_sync_never_raises_it(self, ticket_lake):
        record_key_columns(ticket_lake, FULL, created_since=EXISTED_BEFORE)
        record_key_columns(ticket_lake, FULL, created_since=CREATED_BY_IT)
        record_key_columns(ticket_lake, WITHOUT_TICKET, created_since=CREATED_BY_IT)

        assert "s.tickets" in survey(ticket_lake, WITHOUT_TICKET).partly_known

    def test_the_first_form_and_the_one_without_owners_are_not_a_record_to_rely_on(self, ticket_lake):
        _legacy(ticket_lake, FULL, {"s.tickets"})
        with ticket_lake.load_table("gold.Ticket").transaction() as tx:
            tx.set_properties({"elysium.erasure_keys": json.dumps(
                {"v": 2, "keys": {"ticket_id": ["Ticket"]}, "ids": {"ticket_id": ["Ticket"]},
                 "links": {"customer": ["Customer"]}})})

        for identifier in ("s.tickets", "gold.Ticket"):
            assert not recorded_columns(ticket_lake.load_table(identifier)).present

    def test_after_a_removal_the_legacy_tables_stay_partly_known_and_the_erasure_incomplete(
            self, ticket_lake):
        _legacy(ticket_lake, FULL)
        record_key_columns(ticket_lake, WITHOUT_TICKET, created_since=EXISTED_BEFORE)   # "the upgrade's sync"

        register, result = _erase(ticket_lake, WITHOUT_TICKET, [("Customer", "c1")])

        assert "gold_history.Ticket" in result.reach.partly_known
        assert "s.tickets" in register.incomplete()
        # and a second sync does not change that
        record_key_columns(ticket_lake, WITHOUT_TICKET, created_since=EXISTED_BEFORE)
        apply_erasures(ticket_lake, WITHOUT_TICKET, register, ticket_lake.dir / "mirror")
        assert "s.tickets" in register.incomplete()
        assert [row["ticket_id"] for row in _rows(ticket_lake, "gold_history.Ticket")] == ["t1"]

    def test_adopting_the_tables_first_lets_the_erasure_find_what_depended_on_the_person(
            self, ticket_lake):
        _legacy(ticket_lake, FULL)
        record_key_columns(ticket_lake, WITHOUT_TICKET, created_since=EXISTED_BEFORE)

        for identifier in survey(ticket_lake, WITHOUT_TICKET).partly_known:
            known = recorded_columns(ticket_lake.load_table(identifier)).keys
            ids = {"ticket_id": {"Ticket"}} if "ticket_id" in known else {}
            links = {"cust": {("Ticket", "Customer")}} if "cust" in known else {}
            adopt_table(ticket_lake, WITHOUT_TICKET, identifier, known, ids, links)
        keys = cascade(ticket_lake, WITHOUT_TICKET, [("Customer", "c1")])
        register, _result = _erase(ticket_lake, WITHOUT_TICKET, keys, seeds=[("Customer", "c1")])

        for table in ("gold_history.Ticket", "quarantine_s.tickets", "s.tickets"):
            assert all("t1" not in map(str, row.values()) for row in _rows(ticket_lake, table)), table
        assert survey(ticket_lake, WITHOUT_TICKET).partly_known == []
        assert register.incomplete() == []

    def test_adopt_refuses_an_unknown_column_and_an_unknown_table_and_holds_none_when_told(self, lake):
        from pyiceberg.exceptions import NoSuchTableError

        lake.make("s.notes", [{"note": "x"}])
        with pytest.raises(KeyError):
            adopt_table(lake, WITHOUT_TICKET, "s.notes", {"nope": {"Customer"}})
        with pytest.raises(NoSuchTableError):
            adopt_table(lake, WITHOUT_TICKET, "s.missing", {"x": {"Customer"}})
        assert survey(lake, WITHOUT_TICKET).unreachable == {"s.notes": "no key columns known"}

        record = adopt_table(lake, WITHOUT_TICKET, "s.notes", {})

        assert record.adopted and record.complete
        assert survey(lake, WITHOUT_TICKET).unreachable == {}

    def test_adopting_never_narrows(self, lake):
        lake.make("s.people", [{"acct": "a1", "lead_ref": "L1"}])
        record_key_columns(lake, TestWhatRecordingNeverForgets.SHARED, created_since=CREATED_BY_IT)

        record = adopt_table(lake, TestWhatRecordingNeverForgets.AFTER, "s.people", {"acct": {"Account"}})

        assert record.keys == {"acct": {"Account"}, "lead_ref": {"Lead"}}


class TestAnErasureIsWorkedOutAgainFromItsSeeds:
    def test_restoring_the_type_and_syncing_finishes_what_was_waiting(self, ticket_lake):
        """Ticket removed before any table recorded it; erase c1; restore Ticket; sync."""
        record_key_columns(ticket_lake, WITHOUT_TICKET, created_since=EXISTED_BEFORE)
        register, first = _erase(ticket_lake, WITHOUT_TICKET, [("Customer", "c1")],
                                 seeds=[("Customer", "c1")])
        assert "gold_history.Ticket" in first.reach.unreachable

        record_key_columns(ticket_lake, FULL, created_since=EXISTED_BEFORE)
        apply_erasures(ticket_lake, FULL, register, ticket_lake.dir / "mirror")

        for table in ("gold_history.Ticket", "quarantine_s.tickets", "gold_conflicts.Ticket", "s.tickets"):
            assert all("t1" not in map(str, row.values()) for row in _rows(ticket_lake, table)), table
        assert [row["ticket_id"] for row in _rows(ticket_lake, "gold.Ticket")] == ["t2"]
        assert register.incomplete()            # still partly known: honest, and not for want of trying


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

    def test_recording_it_afterwards_does_not_clear_the_report(self, lake):
        lake.make("s.people", [{"acct": "a1", "lead_ref": "L1"}])
        register, _result = _erase(lake, self.AFTER, [("Account", "a1")])
        assert register.incomplete() == ["s.people"]

        record_key_columns(lake, self.AFTER, created_since=EXISTED_BEFORE)
        apply_erasures(lake, self.AFTER, register, lake.dir / "mirror")

        assert register.incomplete() == ["s.people"]


class TestEachErasureIsIncompleteForItsOwnTablesOnly:
    def test_an_unrelated_partly_known_table_does_not_mark_it(self, lake):
        lake.make("s.people", [{"acct": "a1"}])
        lake.make("s.customers", [{"customer_id": "c1"}])
        schema = {"Customer": CUSTOMER, "Account": _type("people", "acct")}
        record_key_columns(lake, schema, created_since=CREATED_BY_IT)
        with lake.load_table("s.people").transaction() as tx:
            tx.remove_properties("elysium.erasure_keys")
        record_key_columns(lake, schema, created_since=EXISTED_BEFORE)       # s.people: partial

        register = ErasureRegister(lake.dir / "erasures.db")
        register.record([("Customer", "c1")], "tester", "test")
        register.record([("Lead", "L1")], "tester", "test")        # a type the ontology no longer has
        apply_erasures(lake, schema, register, lake.dir / "mirror")

        listed = {erasure.object_type: erasure.incomplete_tables for erasure in register.erasures()}
        assert listed == {"Customer": (), "Lead": ("s.people",)}


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

    def test_it_is_shown_when_the_old_type_has_since_been_removed(self, lake):
        lake.make("s.tickets", [{"ticket_id": "t1", "owner": "5"}])
        record_key_columns(lake, self._schema("Customer"))
        without_customer = {name: self._schema("Employee")[name] for name in ("Employee", "Ticket")}

        assert survey(lake, without_customer, {"Customer"}).stale == [("s.tickets", "owner", "Customer")]


class TestQuarantineAndCleaningOfOtherStorages:
    ADDITIONAL = {"Customer": {**CUSTOMER, "additional_storage": {
        "crm": {"silo": "s", "table": "details", "id_column": "cust_ref"}}}}
    JOINED = {"C": {**_type("c", "id"), "fields": {"id": {"type": "string"}, "tags": {
        "type": "link", "target": "T", "via_table": "c_t", "via_column": "cid",
        "via_target_column": "tid"}}}, "T": _type("t", "tid2")}

    def test_an_additional_storages_findings_are_keyed_by_the_type(self):
        for layer in ("quarantine_s.details", "cleaning_s.details"):
            assert table_key_columns(self.ADDITIONAL, layer) == {"object_id": {"Customer"}}

    def test_a_join_tables_findings_test_each_part_against_the_type_that_owns_it(self, lake):
        assert table_key_columns(self.JOINED, "quarantine_s.c_t") == {
            "object_id#0": {"C"}, "object_id#1": {"T"}}
        lake.make("quarantine_s.c_t", [{"object_id": "c9\x1ft9"}, {"object_id": "c1\x1ft1"}])
        register = ErasureRegister(lake.dir / "erasures.db")
        register.record([("T", "t9"), ("C", "t1")], "tester", "test")   # t1 is a C's id, not a T's
        table = lake.load_table("quarantine_s.c_t").scan().to_arrow()
        columns = table_key_columns(self.JOINED, "quarantine_s.c_t")

        assert erased_mask(table, columns, register.hasher(), register.hashes_by_type()) == [True, False]

    def test_findings_of_a_table_several_types_keep_rows_in_are_reported_shared(self, lake):
        schema = {"A": _type("people", "acct"), "B": _type("people", "lead_ref")}
        lake.make("quarantine_s.people", [{"object_id": "a1"}])

        assert survey(lake, schema).shared_findings == ["quarantine_s.people"]


class TestAGoldJoinCopyWhoseNameTwoSilosShare:
    def test_it_is_reported_partly_known_not_guessed(self, lake):
        def join(silo):
            return {"fields": {"tags": {"type": "link", "target": "T", "via_table": "links",
                                        "via_column": "cid", "via_target_column": "tid"}},
                    "id_field": "id", "storage": {"silo": silo, "table": "c", "id_column": "id"}}
        schema = {"C1": join("s1"), "C2": join("s2"), "T": _type("t", "tid")}
        lake.make("gold.links", [{"cid": "c", "tid": "t"}])
        record_key_columns(lake, schema, created_since=CREATED_BY_IT)

        assert survey(lake, schema).partly_known == ["gold.links"]


class TestATableThatCannotBeRead:
    def test_it_is_named_with_the_kind_and_erasure_goes_on(self, lake):
        lake.make("s.customers", [{"customer_id": "c1"}, {"customer_id": "c2"}])
        lake.make("s.broken", [{"x": 1}])
        record_key_columns(lake, WITHOUT_TICKET, created_since=CREATED_BY_IT)
        for path in (lake.dir / "mirror").rglob("*.metadata.json"):
            if "broken" in str(path):
                path.unlink()

        register, result = _erase(lake, WITHOUT_TICKET, [("Customer", "c1")])

        assert list(result.unreachable_tables) == ["s.broken"]
        assert "cannot be read" in result.unreachable_tables["s.broken"]
        assert str(lake.dir) not in result.unreachable_tables["s.broken"]       # the kind, never the path
        assert [row["customer_id"] for row in _rows(lake, "s.customers")] == ["c2"]
        assert register.incomplete() == ["s.broken"]

    def test_a_table_whose_data_cannot_be_read_is_named_and_neither_crashes_nor_stops_the_rest(
            self, ticket_lake):
        """The metadata loads; a data file is gone (n3)."""
        record_key_columns(ticket_lake, FULL, created_since=CREATED_BY_IT)
        record_key_columns(ticket_lake, WITHOUT_TICKET, created_since=CREATED_BY_IT)
        for path in (ticket_lake.dir / "mirror").rglob("*.parquet"):
            if "/tickets/" in str(path) and "quarantine" not in str(path):
                path.unlink()

        keys = cascade(ticket_lake, WITHOUT_TICKET, [("Customer", "c1")])      # must not raise
        register, result = _erase(ticket_lake, WITHOUT_TICKET, keys)

        assert "data cannot be read" in result.unreachable_tables["s.tickets"]
        assert not register.unpurged()
        assert [row["customer_id"] for row in _rows(ticket_lake, "s.customers")] == ["c2"]
        assert "s.tickets" in register.incomplete()


class TestTheRegisterAcrossAnUpgrade:
    def test_a_register_made_before_the_columns_existed_still_works(self, tmp_path):
        path = tmp_path / "erasures.db"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE erasures (key_hash TEXT NOT NULL, object_type TEXT NOT NULL, "
                         "erasure_id TEXT NOT NULL, requested_by TEXT NOT NULL, reason TEXT NOT NULL, "
                         "requested_at REAL NOT NULL, purged_at REAL, source_cleared_at REAL, "
                         "PRIMARY KEY (key_hash, object_type))")
            conn.execute("INSERT INTO erasures VALUES ('h', 'Customer', 'e1', 'u', 'r', 1.0, 2.0, NULL)")
        register = ErasureRegister(path)

        assert register.incomplete() == [] and register.erasures()[0].incomplete_tables == ()
        assert register.seeds_by_erasure() == {"e1": {("Customer", "h")}}     # every old key is a seed
        register.mark_purged({"e1": ["gold.Tag"]})
        assert register.erasures()[0].incomplete_tables == ("gold.Tag",)
        assert register.incomplete_erasures() == ["e1"]
        register.mark_purged({})
        assert register.incomplete() == []

    def test_seeds_are_kept_apart_from_what_was_found_through_them(self, tmp_path):
        register = ErasureRegister(tmp_path / "erasures.db")
        erasure_id = register.record([("Customer", "c1"), ("Ticket", "t1")], "tester", "test",
                                     seeds=[("Customer", "c1")])
        key_hash = register.hasher()

        assert register.seeds_by_erasure() == {erasure_id: {("Customer", key_hash("Customer", "c1"))}}

    def test_what_is_recorded_names_tables_only(self, tmp_path):
        register = ErasureRegister(tmp_path / "erasures.db")
        erasure_id = register.record([("Customer", "customer-0001")], "tester", "test")

        register.mark_purged({erasure_id: ["gold.Tag"]})

        assert b"customer-0001" not in (tmp_path / "erasures.db").read_bytes()


def test_the_record_carries_the_identity_and_owned_links_of_the_tables_own_rows(lake):
    lake.make("s.tickets", [{"ticket_id": "t1", "cust": "c1"}])
    record_key_columns(lake, FULL, created_since=CREATED_BY_IT)

    recorded = recorded_columns(lake.load_table("s.tickets"))
    assert recorded.ids == {"ticket_id": {"Ticket"}}
    assert recorded.links == {"cust": {("Ticket", "Customer")}}
    assert recorded.present and recorded.complete
    assert recorded.keys == {"ticket_id": {"Ticket"}, "cust": {"Customer"}}


class TestAdoptAllCurrent:
    def test_it_refuses_without_the_confirmation(self, lake):
        lake.make("s.customers", [{"customer_id": "c1"}])
        with pytest.raises(ValueError):
            adopt_all_current(lake, WITHOUT_TICKET, confirmed=False)
        assert not recorded_columns(lake.load_table("s.customers")).present

    def test_it_adopts_what_the_schema_maps_and_only_that(self, ticket_lake):
        lake = ticket_lake
        record_key_columns(lake, FULL, created_since=EXISTED_BEFORE)       # all partial
        lake.make("s.unmapped", [{"x": 1}])

        adopted, unresolved = adopt_all_current(lake, WITHOUT_TICKET, confirmed=True)

        assert "s.customers" in adopted and "gold.Customer" in adopted
        record = recorded_columns(lake.load_table("s.customers"))
        assert record.complete and record.adopted and record.statement
        # the removed Ticket's tables recorded a type the schema no longer has: not this path's to adopt
        assert {"s.tickets", "gold.Ticket", "gold_history.Ticket", "s.unmapped"} <= set(unresolved)
        assert not recorded_columns(lake.load_table("s.unmapped")).present
        assert not recorded_columns(lake.load_table("s.tickets")).complete

    def test_it_never_narrows(self, lake):
        """The id column was renamed in the ontology; the old one still holds ids."""
        lake.make("s.people", [{"acct": "a1", "account_ref": "a1"}])
        record_key_columns(lake, {"Account": _type("people", "acct")}, created_since=CREATED_BY_IT)

        adopt_all_current(lake, {"Account": _type("people", "account_ref")}, confirmed=True)

        assert recorded_key_columns(lake.load_table("s.people")) == {
            "acct": {"Account"}, "account_ref": {"Account"}}
