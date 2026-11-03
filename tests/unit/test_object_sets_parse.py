"""
Parsing the object-set wire form (core/ontology/object_sets.py).

Parsing knows the grammar and the caps and nothing about any deployment,
so these need none. Each refusal is asserted by the words that name the
mistake, because a message that says "invalid" is not one a caller can fix.
What a set MEANS for a particular caller is tested beside the deployment
fixtures, in tests/integration/test_object_sets_evaluation.py.
"""

import pytest

from core.ontology import object_sets as sets
from core.ontology.object_sets import (
    Base,
    Combine,
    Compare,
    Filter,
    In,
    IsNull,
    Junction,
    Not,
    ObjectSetError,
    SearchAround,
    Static,
    Text,
    parse_filter,
    parse_metrics,
    parse_object_set,
    parse_order_by,
    parse_order_by_text,
    parse_select,
)

BASE = {"type": "base", "objectType": "Customer"}
LEAF = {"type": "eq", "field": "region", "value": "us-west"}


class TestTheSetKinds:
    def test_every_kind_parses_to_its_typed_node(self):
        tree = parse_object_set({
            "type": "searchAround", "link": "transactions", "objectSet": {
                "type": "filter", "where": LEAF, "objectSet": {
                    "type": "subtract", "objectSets": [
                        {"type": "union", "objectSets": [BASE, {"type": "static", "objectType": "Customer",
                                                                 "primaryKeys": ["cust_001", 2, "cust_001"]}]},
                        {"type": "intersect", "objectSets": [BASE, BASE]},
                    ]}}})

        assert isinstance(tree, SearchAround) and tree.link == "transactions"
        assert isinstance(tree.object_set, Filter)
        subtract = tree.object_set.object_set
        assert isinstance(subtract, Combine) and subtract.kind == "subtract"
        union = subtract.object_sets[0]
        assert isinstance(union, Combine) and union.kind == "union"
        # Keys are text, de-duplicated, in the order given.
        assert union.object_sets[1] == Static("Customer", ("cust_001", "2"))
        assert union.object_sets[0] == Base("Customer")

    @pytest.mark.parametrize("kind", ["reference", "similarTo", "withProperties", "", None, 3])
    def test_a_kind_this_slice_does_not_have_is_refused_naming_those_that_exist(self, kind):
        with pytest.raises(ObjectSetError) as refused:
            parse_object_set({"type": kind, "objectType": "Customer"})

        assert "Unknown object set type" in str(refused.value)
        for known in sets.SET_TYPES:
            assert known in str(refused.value)
        assert "reference" not in sets.SET_TYPES and "similarTo" not in sets.SET_TYPES

    @pytest.mark.parametrize("raw, words", [
        ("base", "must be an object"),
        ({"type": "base"}, "needs `objectType`"),
        ({"type": "base", "objectType": ""}, "needs `objectType`"),
        ({"type": "base", "objectType": "Customer", "where": LEAF}, "does not take"),
        ({"type": "filter", "objectSet": BASE}, "needs `objectSet` and `where`"),
        ({"type": "searchAround", "objectSet": BASE}, "needs `link`"),
        ({"type": "union", "objectSets": [BASE]}, "at least two"),
        ({"type": "union", "objectSets": "x"}, "at least two"),
        ({"type": "static", "objectType": "Customer", "primaryKeys": "cust_001"}, "needs `primaryKeys`"),
        ({"type": "static", "objectType": "Customer", "primaryKeys": [True]}, "string or an integer"),
        ({"type": "static", "objectType": "Customer", "primaryKeys": [["a"]]}, "string or an integer"),
    ])
    def test_a_malformed_set_says_what_is_wrong(self, raw, words):
        with pytest.raises(ObjectSetError, match=words):
            parse_object_set(raw)


class TestTheFilterGrammar:
    def test_every_operator_parses(self):
        tree = parse_filter({"type": "and", "value": [
            {"type": "or", "value": [
                {"type": "lt", "field": "a", "value": 1}, {"type": "lte", "field": "a", "value": 1},
                {"type": "gt", "field": "a", "value": 1}, {"type": "gte", "field": "a", "value": 1}]},
            {"type": "not", "value": {"type": "isNull", "field": "b", "value": True}},
            {"type": "in", "field": "c", "value": ["x", 2]},
            {"type": "contains", "field": "d", "value": "x"},
            {"type": "startsWith", "field": "d", "value": "x"},
            LEAF]})

        assert isinstance(tree, Junction) and tree.operator == "and"
        ors, negation, member, contains, starts, equals = tree.children
        assert [child.operator for child in ors.children] == ["lt", "lte", "gt", "gte"]
        assert negation == Not(IsNull("b", True))
        assert member == In("c", ("x", 2))
        assert contains == Text("contains", "d", "x") and starts == Text("startsWith", "d", "x")
        assert equals == Compare("eq", "region", "us-west")

    def test_the_operator_list_is_the_documented_one(self):
        assert set(sets.FILTER_TYPES) == {"eq", "in", "lt", "lte", "gt", "gte", "isNull", "contains",
                                          "startsWith", "and", "or", "not"}

    @pytest.mark.parametrize("raw, words", [
        ({"type": "like", "field": "a", "value": "x"}, "Unknown filter type"),
        ({"type": "eq", "value": 1}, "needs `field`"),
        ({"type": "eq", "field": "a"}, "needs `value`"),
        ({"type": "eq", "field": "a", "value": None}, "isNull"),
        ({"type": "eq", "field": "a", "value": [1]}, "string, number or boolean"),
        ({"type": "in", "field": "a", "value": []}, "non-empty list"),
        ({"type": "in", "field": "a", "value": "x"}, "non-empty list"),
        ({"type": "in", "field": "a", "value": [None]}, "isNull"),
        ({"type": "isNull", "field": "a", "value": "yes"}, "true or false"),
        ({"type": "contains", "field": "a", "value": 3}, "non-empty string"),
        ({"type": "startsWith", "field": "a", "value": ""}, "non-empty string"),
        ({"type": "and", "value": []}, "non-empty list of filters"),
        ({"type": "not", "value": [LEAF]}, "must be an object"),
        ({"type": "not"}, "needs `value`"),
        ({"type": "eq", "field": "a", "value": 1, "extra": 2}, "does not take"),
    ])
    def test_a_malformed_filter_says_what_is_wrong(self, raw, words):
        with pytest.raises(ObjectSetError, match=words):
            parse_filter(raw)


class TestTheCaps:
    """Every cap is a NAMED constant, and each is a refusal that says so,
    never a quiet truncation."""

    def test_set_nesting_stops_at_the_depth_cap(self):
        node = BASE
        for _ in range(sets.MAX_SET_DEPTH - 1):
            node = {"type": "filter", "objectSet": node, "where": LEAF}
        parse_object_set(node)  # exactly at the cap

        with pytest.raises(ObjectSetError, match=f"at most {sets.MAX_SET_DEPTH} deep"):
            parse_object_set({"type": "filter", "objectSet": node, "where": LEAF})

    def test_filter_nesting_stops_at_the_depth_cap(self):
        node = LEAF
        for _ in range(sets.MAX_FILTER_DEPTH - 1):
            node = {"type": "not", "value": node}
        parse_filter(node)

        with pytest.raises(ObjectSetError, match=f"at most {sets.MAX_FILTER_DEPTH} deep"):
            parse_filter({"type": "not", "value": node})

    def test_width_alone_cannot_make_a_request_huge(self):
        parse_object_set({"type": "union", "objectSets": [BASE] * (sets.MAX_SET_NODES - 1)})
        with pytest.raises(ObjectSetError, match=f"At most {sets.MAX_SET_NODES} object set nodes"):
            parse_object_set({"type": "union", "objectSets": [BASE] * sets.MAX_SET_NODES})

        parse_filter({"type": "and", "value": [LEAF] * (sets.MAX_FILTER_NODES - 1)})
        with pytest.raises(ObjectSetError, match=f"At most {sets.MAX_FILTER_NODES} filter nodes"):
            parse_filter({"type": "and", "value": [LEAF] * sets.MAX_FILTER_NODES})

    def test_value_lists_and_text_are_capped(self):
        parse_filter({"type": "in", "field": "a", "value": list(range(sets.MAX_IN_VALUES))})
        with pytest.raises(ObjectSetError, match=f"at most {sets.MAX_IN_VALUES} values"):
            parse_filter({"type": "in", "field": "a", "value": list(range(sets.MAX_IN_VALUES + 1))})

        parse_filter({"type": "eq", "field": "a", "value": "x" * sets.MAX_VALUE_LENGTH})
        with pytest.raises(ObjectSetError, match="characters"):
            parse_filter({"type": "eq", "field": "a", "value": "x" * (sets.MAX_VALUE_LENGTH + 1)})

    def test_a_static_set_is_capped(self):
        keys = [f"k{i}" for i in range(sets.MAX_STATIC_KEYS)]
        parse_object_set({"type": "static", "objectType": "Customer", "primaryKeys": keys})
        with pytest.raises(ObjectSetError, match=f"at most {sets.MAX_STATIC_KEYS} keys"):
            parse_object_set({"type": "static", "objectType": "Customer", "primaryKeys": [*keys, "more"]})

    def test_order_by_select_and_metrics_are_capped(self):
        terms = [{"field": f"f{i}"} for i in range(sets.MAX_ORDER_BY)]
        assert len(parse_order_by(terms)) == sets.MAX_ORDER_BY
        with pytest.raises(ObjectSetError, match=f"at most {sets.MAX_ORDER_BY}"):
            parse_order_by([*terms, {"field": "one_more"}])

        parse_select([f"f{i}" for i in range(sets.MAX_SELECT_FIELDS)])
        with pytest.raises(ObjectSetError, match=f"at most {sets.MAX_SELECT_FIELDS}"):
            parse_select([f"f{i}" for i in range(sets.MAX_SELECT_FIELDS + 1)])

        parse_metrics([{"type": "count", "name": f"c{i}"} for i in range(sets.MAX_METRICS)])
        with pytest.raises(ObjectSetError, match=f"1 to {sets.MAX_METRICS}"):
            parse_metrics([{"type": "count", "name": f"c{i}"} for i in range(sets.MAX_METRICS + 1)])


class TestOrderingSelectingAndMetrics:
    def test_order_by_both_forms(self):
        assert parse_order_by([{"field": "amount", "direction": "desc"}, {"field": "name"}]) == (
            sets.OrderTerm("amount", True), sets.OrderTerm("name", False))
        assert parse_order_by_text("amount:DESC, name") == (
            sets.OrderTerm("amount", True), sets.OrderTerm("name", False))
        assert parse_order_by_text(None) == () and parse_order_by(None) == ()

    def test_a_direction_that_is_neither_is_refused(self):
        with pytest.raises(ObjectSetError, match="asc"):
            parse_order_by([{"field": "a", "direction": "sideways"}])

    def test_select_is_de_duplicated_and_checked(self):
        assert parse_select(["a", "b", "a"]) == ("a", "b")
        with pytest.raises(ObjectSetError):
            parse_select("a")
        with pytest.raises(ObjectSetError):
            parse_select([""])

    def test_metrics_are_named_and_checked(self):
        metrics = parse_metrics([{"type": "count"}, {"type": "sum", "field": "amount"},
                                 {"type": "avg", "field": "amount", "name": "mean"}])
        assert [(m.name, m.aggregate, m.field) for m in metrics] == [
            ("count", "count", None), ("sum_amount", "sum", "amount"), ("mean", "avg", "amount")]

    @pytest.mark.parametrize("raw, words", [
        ([{"type": "median", "field": "a"}], "Unknown metric type"),
        ([{"type": "sum"}], "needs `field`"),
        ([{"type": "count", "field": "a"}], "takes no field"),
        ([{"type": "count", "name": "Not Ok"}], "lower-case"),
        ([{"type": "count"}, {"type": "count"}], "same name"),
        ([], "1 to"),
        ("count", "1 to"),
    ])
    def test_a_bad_metric_says_what_is_wrong(self, raw, words):
        with pytest.raises(ObjectSetError, match=words):
            parse_metrics(raw)
