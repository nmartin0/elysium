"""Which source tends to be right when two disagree, as evidence (R60).

With two sources a snapshot cannot say who is right. How a disagreement
ENDS can: the source that changed its value to match the other moved,
and the other's value is the one both now hold.
"""

from types import SimpleNamespace

import pytest

from core.mirror.identity import Resolution
from core.mirror.source_record import (
    SHOWN_FROM,
    Ended,
    SourceRecordStore,
    TrackRecord,
    current_values,
    ended_disagreements,
)


def conflict(entity="c1", field="city", chosen="Leeds", chosen_source="billing",
             losing="Hull", losing_source="crm", at="2026-10-01", kind="property"):
    return {"entity_id": entity, "kind": kind, "field": field, "chosen": chosen,
            "chosen_source": chosen_source, "losing": losing, "losing_source": losing_source,
            "recorded_at": at}


def now(billing, crm, entity="c1", field="city"):
    return {entity: {field: {"billing": billing, "crm": crm}}}


class TestHowADisagreementEnds:
    def test_the_preferred_source_moving_means_the_other_held(self):
        [ended] = ended_disagreements([conflict()], now("Hull", "Hull"))

        assert (ended.held_source, ended.moved_source) == ("crm", "billing")

    def test_the_outranked_source_moving_means_the_preferred_held(self):
        [ended] = ended_disagreements([conflict()], now("Leeds", "Leeds"))

        assert (ended.held_source, ended.moved_source) == ("billing", "crm")

    def test_both_moving_to_a_third_value_is_no_evidence(self):
        assert ended_disagreements([conflict()], now("York", "York")) == []

    def test_a_disagreement_still_open_is_not_ended(self):
        assert ended_disagreements([conflict()], now("Leeds", "Hull")) == []

    def test_one_side_falling_silent_is_not_agreement(self):
        assert ended_disagreements([conflict()], now("Hull", None)) == []

    def test_a_gone_entity_or_source_says_nothing(self):
        assert ended_disagreements([conflict()], {}) == []
        assert ended_disagreements([conflict()], {"c1": {"city": {"billing": "Hull"}}}) == []

    def test_the_latest_row_is_the_disagreement_that_ended(self):
        """Leeds/Hull, then Leeds/York, then both York: the CRM's LAST
        value held, whatever it said first."""
        rows = [conflict(losing="Hull", at="2026-10-01"), conflict(losing="York", at="2026-10-05")]

        [ended] = ended_disagreements(rows, now("York", "York"))

        assert ended.held_source == "crm" and ended.last_recorded_at == "2026-10-05"

    def test_a_security_conflict_or_a_fill_is_not_a_disagreement_about_a_value(self):
        rows = [conflict(kind="security"), conflict(kind="filled")]

        assert ended_disagreements(rows, now("Hull", "Hull")) == []

    def test_values_compare_as_the_table_stores_them(self):
        """The conflicts table holds strings; silver holds types."""
        [ended] = ended_disagreements([conflict(chosen="10", losing="12")], now(12, 12))

        assert ended.held_source == "crm"


class TestWhatTheBrowserMaySee:
    def record(self, a, b):
        return TrackRecord("city", ("billing", "crm"), {"crm": a, "billing": b})

    def test_a_share_rounded_to_ten_per_cent_and_no_count(self):
        assert self.record(8, 3).shown() == {"source": "crm", "about_percent": 70}

    def test_nothing_below_the_minimum(self):
        assert SHOWN_FROM == 10
        assert self.record(7, 2).shown() is None
        assert self.record(7, 3).shown() is not None

    def test_a_tie_names_the_same_source_whichever_order_it_came_in(self):
        one = TrackRecord("city", ("billing", "crm"), {"crm": 5, "billing": 5})
        two = TrackRecord("city", ("billing", "crm"), {"billing": 5, "crm": 5})

        assert one.shown() == two.shown() == {"source": "billing", "about_percent": 50}


class TestTheStore:
    def test_an_ended_disagreement_is_kept_once(self, tmp_path):
        store = SourceRecordStore(tmp_path / "r.db")
        ended = Ended("c1", "city", "t1", "crm", "billing")

        assert store.record("Customer", [ended]) == 1
        assert store.record("Customer", [ended]) == 0
        record = store.track_records("Customer")[("city", frozenset(("crm", "billing")))]
        assert record.held == {"crm": 1}

    def test_the_same_entity_disagreeing_again_later_counts_again(self, tmp_path):
        store = SourceRecordStore(tmp_path / "r.db")

        store.record("Customer", [Ended("c1", "city", "t1", "crm", "billing"),
                                  Ended("c1", "city", "t9", "billing", "crm")])

        record = store.track_records("Customer")[("city", frozenset(("crm", "billing")))]
        assert record.held == {"crm": 1, "billing": 1}

    def test_types_and_fields_are_kept_apart(self, tmp_path):
        store = SourceRecordStore(tmp_path / "r.db")
        store.record("Customer", [Ended("c1", "city", "t", "crm", "billing"),
                                  Ended("c1", "phone", "t", "billing", "crm")])
        store.record("Supplier", [Ended("s1", "city", "t", "billing", "crm")])

        records = store.track_records("Customer")
        assert {key[0] for key in records} == {"city", "phone"}
        assert records[("city", frozenset(("crm", "billing")))].held == {"crm": 1}


class TestCurrentValues:
    def test_each_source_by_the_name_the_conflicts_table_uses(self):
        type_def = {"fields": {"city": {"type": "data"},
                               "phone": {"type": "data", "storage": "crm"}},
                    "additional_storage": {"crm": {}}}
        resolution = Resolution(entities={"c1": {
            None: {"city": "Leeds"}, "crm": {"city": "Hull", "phone": "0113"}}})

        assert current_values(type_def, resolution) == {"c1": {
            "city": {"primary": "Leeds", "crm": "Hull"},
            # Declared to live in the CRM only, so only the CRM speaks.
            "phone": {"crm": "0113"}}}


class TestTheSync:
    TYPE = {"id_field": "customer_id",
            "storage": {"silo": "b", "table": "customers", "id_column": "pk"},
            "additional_storage": {"crm": {"silo": "c", "table": "contacts", "id_column": "cid"}},
            "identity": {"match_on": ["email"]},
            "fields": {"email": {"type": "data"}, "city": {"type": "data"}}}

    def catalog(self, rows):
        table = SimpleNamespace(scan=lambda: SimpleNamespace(
            to_arrow=lambda: SimpleNamespace(to_pylist=lambda: rows)))
        return SimpleNamespace(load_table=lambda identifier: table)

    def test_an_ended_disagreement_is_kept_after_a_build(self, tmp_path):
        from scripts.run_sync import _record_ended_disagreements

        store = SourceRecordStore(tmp_path / "r.db")
        rows = {None: [{"pk": "c1", "email": "a@x", "city": "Hull"}],
                "crm": [{"cid": "9", "email": "a@x", "city": "Hull"}]}
        history = [conflict(entity="c1", chosen_source="primary", losing_source="crm")]

        added = _record_ended_disagreements(store, self.catalog(history), "Customer",
                                            self.TYPE, rows, [])

        assert added == 1
        assert store.track_records("Customer")[
            ("city", frozenset(("crm", "primary")))].held == {"crm": 1}

    def test_a_failure_is_reported_and_never_breaks_the_sync(self, tmp_path, capsys):
        from scripts.run_sync import _record_ended_disagreements

        def broken(identifier):
            raise RuntimeError("disk on fire")

        added = _record_ended_disagreements(
            SourceRecordStore(tmp_path / "r.db"), SimpleNamespace(load_table=broken),
            "Customer", self.TYPE, {None: []}, [])

        assert added == 0
        assert "track record not updated" in capsys.readouterr().err

    def test_a_type_without_a_rule_has_nothing_to_record(self, tmp_path):
        from scripts.run_sync import _record_ended_disagreements

        plain = {k: v for k, v in self.TYPE.items() if k != "identity"}

        assert _record_ended_disagreements(SourceRecordStore(tmp_path / "r.db"), None,
                                           "Customer", plain, {None: []}, []) == 0


class TestTheServerSideReport:
    def test_it_gives_the_counts_the_panel_leaves_out(self, tmp_path):
        from scripts.source_track_record import report

        store = SourceRecordStore(tmp_path / "r.db")
        store.record("Customer", [Ended(f"c{i}", "city", "t", "crm", "billing")
                                  for i in range(7)]
                     + [Ended("x", "city", "t", "billing", "crm")])

        text = report(store, ["Customer"])

        assert "city, billing vs crm: 8 ended" in text
        assert "crm's value held 7" in text and "billing's value held 1" in text
        assert "not on the panel until 10 have ended" in text


@pytest.mark.parametrize("held", [{"crm": 3}, {}])
def test_an_empty_record_does_not_divide_by_zero(held):
    assert TrackRecord("city", ("billing", "crm"), held).leader()[0] in ("billing", "crm")
