"""Erasure and the tables of types the ontology no longer has, at the level of
the lake itself: a catalog built by hand, so each case is exactly one fact.

The end-to-end case (a real sync, a removed type, an erasure) is
tests/integration/test_erasure_after_removal.py.
"""

import json
import sqlite3

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
    gap_notice,
    record_key_columns,
    recorded_columns,
    recorded_key_columns,
    survey,
    table_key_columns,
    unmapped_columns,
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
FULL = {"Customer": CUSTOMER,
        "Ticket": _type("tickets", "ticket_id", customer=_link("Customer", "cust"), body={"type": "string"})}
#: The same, but the ontology does not map the tickets' `body` column: a table
#: with a column like that is never recorded as completely known.
BODY_UNMAPPED = {"Customer": CUSTOMER,
                 "Ticket": _type("tickets", "ticket_id", customer=_link("Customer", "cust"))}
WITHOUT_TICKET = {"Customer": CUSTOMER}


def _rows(catalog, identifier):
    return catalog.load_table(identifier).scan().to_arrow().to_pylist()


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
    lake.make("gold_conflicts.Ticket", [{"entity_id": "t1", "field": "c1 text"}])
    lake.make("quarantine_s.tickets", [{"object_id": "t1", "value": "c1 text"}])
    lake.make("cleaning_s.tickets", [{"object_id": "t1", "column": "body"}])
    return lake


class TestAFormerLinkingTypesRowsAreFoundThroughItsLinks:
    @pytest.fixture
    def removed_ticket(self, ticket_lake):
        record_key_columns(ticket_lake, FULL)       # a sync that made them
        record_key_columns(ticket_lake, WITHOUT_TICKET)   # and one after the removal
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
        record_key_columns(lake, shared)
        after = {name: shared[name] for name in ("Customer", "Account")}
        record_key_columns(lake, after)

        assert cascade(lake, after, [("Customer", "c1")]) == [("Customer", "c1")]

    def test_a_table_that_never_recorded_its_links_cannot_be_followed_and_says_so(self, ticket_lake):
        _legacy(ticket_lake, FULL, {"s.tickets"})

        assert cascade(ticket_lake, WITHOUT_TICKET, [("Customer", "c1")]) == [("Customer", "c1")]
        assert "s.tickets" in survey(ticket_lake, WITHOUT_TICKET).partly_known


class TestWhatASyncCanAndCannotMakeKnown:
    """A record holds what the schema mapped the day it was written. It cannot
    recover the columns of a type removed before: only an operator can."""

    def test_a_table_whose_every_column_is_mapped_is_complete(self, ticket_lake):
        record_key_columns(ticket_lake, FULL)

        assert recorded_columns(ticket_lake.load_table("s.tickets")).complete
        assert survey(ticket_lake, FULL).partly_known == []

    def test_a_table_with_a_column_the_ontology_does_not_map_is_partial_whatever_its_age(
            self, ticket_lake):
        record_key_columns(ticket_lake, BODY_UNMAPPED)

        assert not recorded_columns(ticket_lake.load_table("s.tickets")).complete
        reach = survey(ticket_lake, BODY_UNMAPPED)
        assert "s.tickets" in reach.partly_known
        assert reach.unmapped["s.tickets"] == ["body"]
        assert {"quarantine_s.tickets", "cleaning_s.tickets"} <= set(reach.partly_known)   # inherited
        assert "columns the ontology does not map: body" in " ".join(gap_notice(reach))

    def test_findings_with_no_source_table_in_the_lake_are_partial(self, lake):
        lake.make("quarantine_s.orphans", [{"object_id": "o1", "value": "x"}])
        schema = {"Orphan": _type("orphans", "oid")}

        record_key_columns(lake, schema)

        assert "quarantine_s.orphans" in survey(lake, schema).partly_known

    def test_the_pipelines_own_columns_and_the_fixed_shapes_count_as_mapped(self, ticket_lake):
        record_key_columns(ticket_lake, FULL)

        for identifier in TICKET_TABLES:
            assert unmapped_columns(ticket_lake, FULL, identifier,
                                    ticket_lake.load_table(identifier)) == [], identifier

    def test_a_later_sync_never_raises_it(self, ticket_lake):
        record_key_columns(ticket_lake, BODY_UNMAPPED)
        record_key_columns(ticket_lake, FULL)        # now `body` is mapped: still partial
        record_key_columns(ticket_lake, WITHOUT_TICKET)

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
        record_key_columns(ticket_lake, WITHOUT_TICKET)   # "the upgrade's sync"

        register, result = _erase(ticket_lake, WITHOUT_TICKET, [("Customer", "c1")])

        assert "gold_history.Ticket" in result.reach.partly_known
        assert "s.tickets" in register.incomplete()
        # and a second sync does not change that
        record_key_columns(ticket_lake, WITHOUT_TICKET)
        apply_erasures(ticket_lake, WITHOUT_TICKET, register, ticket_lake.dir / "mirror")
        assert "s.tickets" in register.incomplete()
        assert [row["ticket_id"] for row in _rows(ticket_lake, "gold_history.Ticket")] == ["t1"]

    def test_adopting_the_tables_first_lets_the_erasure_find_what_depended_on_the_person(
            self, ticket_lake):
        _legacy(ticket_lake, FULL)
        record_key_columns(ticket_lake, WITHOUT_TICKET)

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

    def test_a_link_stated_alone_also_makes_its_column_a_key_of_the_target(self, ticket_lake):
        record = adopt_table(ticket_lake, WITHOUT_TICKET, "s.tickets", {}, None,
                             {"cust": {("Ticket", "Customer")}})

        assert record.keys["cust"] == {"Customer"}
        keys = cascade(ticket_lake, WITHOUT_TICKET, [("Customer", "c1")])
        assert ("Ticket", "t1") not in keys        # ids were not stated: the row itself is found by key
        register, _result = _erase(ticket_lake, WITHOUT_TICKET, keys, seeds=[("Customer", "c1")])
        assert [row["ticket_id"] for row in _rows(ticket_lake, "s.tickets")] == ["t2"]

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
        record_key_columns(lake, TestWhatRecordingNeverForgets.SHARED)

        record = adopt_table(lake, TestWhatRecordingNeverForgets.AFTER, "s.people", {"acct": {"Account"}})

        assert record.keys == {"acct": {"Account"}, "lead_ref": {"Lead"}}


class TestAnErasureIsWorkedOutAgainFromItsSeeds:
    def test_restoring_the_type_and_syncing_finishes_what_was_waiting(self, ticket_lake):
        """Ticket removed before any table recorded it; erase c1; restore Ticket; sync."""
        record_key_columns(ticket_lake, WITHOUT_TICKET)
        register, first = _erase(ticket_lake, WITHOUT_TICKET, [("Customer", "c1")],
                                 seeds=[("Customer", "c1")])
        assert "gold_history.Ticket" in first.reach.unreachable

        record_key_columns(ticket_lake, FULL)
        apply_erasures(ticket_lake, FULL, register, ticket_lake.dir / "mirror")

        for table in ("gold_history.Ticket", "quarantine_s.tickets", "gold_conflicts.Ticket", "s.tickets"):
            assert all("t1" not in map(str, row.values()) for row in _rows(ticket_lake, table)), table
        assert [row["ticket_id"] for row in _rows(ticket_lake, "gold.Ticket")] == ["t2"]
        # every column of every table is mapped again, so nothing is left partly known
        assert register.incomplete() == []


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

        record_key_columns(lake, self.AFTER)
        apply_erasures(lake, self.AFTER, register, lake.dir / "mirror")

        assert register.incomplete() == ["s.people"]


class TestAPartlyKnownTableMarksEveryErasure:
    """Its unmapped columns may hold ids of ANY type (a removed link's column
    can name a customer), so no erasure is complete while one exists."""

    def test_an_erasure_of_an_unrelated_type_is_marked_too(self, lake):
        lake.make("s.people", [{"acct": "a1", "memo": "m"}])
        lake.make("s.customers", [{"customer_id": "c1"}])
        schema = {"Customer": CUSTOMER, "Account": _type("people", "acct")}
        record_key_columns(lake, schema)       # s.people has `memo`: partial

        register = ErasureRegister(lake.dir / "erasures.db")
        register.record([("Customer", "c1")], "tester", "test")
        register.record([("Lead", "L1")], "tester", "test")        # a type the ontology no longer has
        apply_erasures(lake, schema, register, lake.dir / "mirror")

        listed = {erasure.object_type: erasure.incomplete_tables for erasure in register.erasures()}
        assert listed == {"Customer": ("s.people",), "Lead": ("s.people",)}


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

    def test_a_table_whose_data_cannot_be_read_is_named_and_neither_crashes_nor_stops_the_rest(
            self, ticket_lake):
        """The metadata loads; a data file is gone (n3)."""
        record_key_columns(ticket_lake, FULL)
        record_key_columns(ticket_lake, WITHOUT_TICKET)
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
    record_key_columns(lake, FULL)

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
        record_key_columns(lake, BODY_UNMAPPED)       # tickets: partial
        lake.make("s.unmapped", [{"x": 1}])

        adopted, unresolved = adopt_all_current(lake, WITHOUT_TICKET, confirmed=True)

        assert "s.customers" in adopted and "gold.Customer" in adopted
        record = recorded_columns(lake.load_table("s.customers"))
        assert record.complete and record.adopted and record.statement
        # the removed Ticket's tables recorded a type the schema no longer has: not this path's to adopt
        assert {"s.tickets", "gold.Ticket", "gold_history.Ticket", "s.unmapped"} <= set(unresolved)
        assert not recorded_columns(lake.load_table("s.unmapped")).present
        assert not recorded_columns(lake.load_table("s.tickets")).complete
        # nor does the stronger statement adopt what the ontology does not know at all
        _adopted, still = adopt_all_current(lake, WITHOUT_TICKET, confirmed=True, including_unmapped=True)
        assert still["s.unmapped"] == "the ontology does not map this table"
        assert not recorded_columns(lake.load_table("s.unmapped")).present

    def test_a_table_with_columns_the_ontology_does_not_map_needs_the_stronger_statement(self, lake):
        lake.make("s.customers", [{"customer_id": "c1", "memo": "x"}])
        lake.make("gold.Customer", [{"customer_id": "c1"}])

        adopted, unresolved = adopt_all_current(lake, WITHOUT_TICKET, confirmed=True)

        assert adopted == ["gold.Customer"]
        assert unresolved == {"s.customers": "columns the ontology does not map: memo"}
        assert not recorded_columns(lake.load_table("s.customers")).complete

        adopted, unresolved = adopt_all_current(lake, WITHOUT_TICKET, confirmed=True,
                                                including_unmapped=True)

        assert "s.customers" in adopted and unresolved == {}
        record = recorded_columns(lake.load_table("s.customers"))
        assert record.complete and record.adopted and "hold no person ids" in record.statement

    def test_a_table_that_recorded_a_removed_type_is_not_adopted_even_with_the_stronger_statement(self, lake):
        lake.make("s.people", [{"acct": "a1", "lead_ref": "L1"}])
        record_key_columns(lake, TestWhatRecordingNeverForgets.SHARED)

        adopted, unresolved = adopt_all_current(lake, TestWhatRecordingNeverForgets.AFTER, confirmed=True,
                                                including_unmapped=True)

        assert "s.people" not in adopted
        assert unresolved["s.people"] == "it recorded a type the ontology no longer has"

    def test_it_never_narrows(self, lake):
        """The id column was renamed in the ontology; the old one still holds ids."""
        lake.make("s.people", [{"acct": "a1", "account_ref": "a1"}])
        record_key_columns(lake, {"Account": _type("people", "acct")})

        renamed = {"Account": _type("people", "account_ref")}
        _adopted, unresolved = adopt_all_current(lake, renamed, confirmed=True)
        assert unresolved == {"s.people": "columns the ontology does not map: acct"}
        adopt_all_current(lake, renamed, confirmed=True, including_unmapped=True)

        assert recorded_key_columns(lake.load_table("s.people")) == {
            "acct": {"Account"}, "account_ref": {"Account"}}
