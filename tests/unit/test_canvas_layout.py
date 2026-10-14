"""The canvas layout: presentation kept apart from the declaration, and
kept to what its owner may see (DEV_UI 14)."""

import math

import pytest

from core.canvas_layout import (
    MAX_AREAS,
    CanvasLayoutError,
    CanvasLayoutStore,
    clean_layout,
    security_chains,
)

VISIBLE = {"Customer", "Transaction"}


class TestCleaning:
    def test_a_layout_of_visible_types_is_kept(self):
        doc = {"positions": {"Customer": {"x": 10, "y": -4.5}},
               "areas": [{"name": " Billing ", "types": ["Transaction", "Customer"]}]}
        assert clean_layout(doc, VISIBLE) == {
            "positions": {"Customer": {"x": 10.0, "y": -4.5}},
            "areas": [{"name": "Billing", "types": ["Customer", "Transaction"]}],
        }

    def test_a_type_they_cannot_see_is_DROPPED_not_refused(self):
        """Refusing would answer "is there a type called Payroll?"."""
        doc = {"positions": {"Payroll": {"x": 1, "y": 1}, "Customer": {"x": 2, "y": 2}},
               "areas": [{"name": "Mixed", "types": ["Payroll", "Customer"]}]}
        cleaned = clean_layout(doc, VISIBLE)
        assert set(cleaned["positions"]) == {"Customer"}
        assert cleaned["areas"][0]["types"] == ["Customer"]

    def test_an_area_left_empty_by_a_lost_grant_keeps_its_name(self):
        cleaned = clean_layout({"areas": [{"name": "Payroll things", "types": ["Payroll"]}]}, VISIBLE)
        assert cleaned["areas"] == [{"name": "Payroll things", "types": []}]

    @pytest.mark.parametrize("point", [
        {"x": "1", "y": 2}, {"x": True, "y": 2}, {"x": math.inf, "y": 0},
        {"x": math.nan, "y": 0}, {"x": 1e9, "y": 0}, {"y": 0},
    ])
    def test_a_coordinate_must_be_an_ordinary_number(self, point):
        with pytest.raises(CanvasLayoutError):
            clean_layout({"positions": {"Customer": point}}, VISIBLE)

    def test_a_malformed_point_is_refused_even_for_an_invisible_type(self):
        """Shape is checked before visibility, so the answer to a bad
        payload does not depend on which types exist."""
        with pytest.raises(CanvasLayoutError):
            clean_layout({"positions": {"Payroll": {"x": "a", "y": 0}}}, VISIBLE)

    def test_two_areas_of_one_name_are_refused(self):
        with pytest.raises(CanvasLayoutError, match="two subject areas"):
            clean_layout({"areas": [{"name": "A", "types": []}, {"name": "a", "types": []}]}, VISIBLE)

    def test_too_many_areas_are_refused(self):
        areas = [{"name": f"Area {i}", "types": []} for i in range(MAX_AREAS + 1)]
        with pytest.raises(CanvasLayoutError, match="at most"):
            clean_layout({"areas": areas}, VISIBLE)

    @pytest.mark.parametrize("doc", [[], "x", {"positions": []}, {"areas": {}},
                                     {"areas": [{"types": []}]}, {"areas": [{"name": "A", "types": "Customer"}]}])
    def test_the_wrong_shape_is_refused(self, doc):
        with pytest.raises(CanvasLayoutError):
            clean_layout(doc, VISIBLE)


class TestTheStore:
    def test_one_layout_per_person(self, tmp_path):
        store = CanvasLayoutStore(tmp_path / "canvas.db")
        store.put("alice", {"positions": {"Customer": {"x": 1, "y": 2}}, "areas": []})
        store.put("bob", {"positions": {}, "areas": [{"name": "Mine", "types": []}]})
        store.put("alice", {"positions": {"Customer": {"x": 5, "y": 6}}, "areas": []})

        assert store.get("alice")["positions"]["Customer"] == {"x": 5, "y": 6}
        assert store.get("bob")["areas"][0]["name"] == "Mine"
        assert store.get("carol") == {}


class TestSecurityChains:
    SCHEMA = {
        "Customer": {"security": {"field": "region"}},
        "Transaction": {"security": {"via_field": "customer"}},
        "Ticket": {"security": {"via_field": "owner"}},
    }

    def _visible(self, **overrides):
        visible = {
            "Customer": {"fields": {"region": {"type": "data"}}},
            "Transaction": {"fields": {"customer": {"type": "link", "target": "Customer"}}},
            "Ticket": {"fields": {"owner": {"type": "link", "target": "Customer"}}},
        }
        visible.update(overrides)
        return visible

    def test_each_type_says_where_its_security_comes_from(self):
        assert security_chains(self.SCHEMA, self._visible()) == [
            {"type": "Customer", "kind": "field", "field": "region"},
            {"type": "Ticket", "kind": "via", "field": "owner", "target": "Customer"},
            {"type": "Transaction", "kind": "via", "field": "customer", "target": "Customer"},
        ]

    def test_a_chain_through_something_unseen_is_left_out_not_half_drawn(self):
        visible = self._visible(Ticket={"fields": {}})  # the via field is not visible
        assert [c["type"] for c in security_chains(self.SCHEMA, visible)] == ["Customer", "Transaction"]

        del visible["Customer"]  # the target type is not visible
        assert [c["type"] for c in security_chains(self.SCHEMA, visible)] == []
