"""
A decimal leaves the API exactly, as a string, at its declared scale
(PA001-G12).

MEASURED BEFORE THE FIX, on this FastAPI (0.143) and pydantic (2.13):

    route without a response model   {"v": 10.5}            a float
    route with one (Any field)       {"v": "10.500000000"}  storage scale

The first is a different number in general; the second is the right
number written the way silver stores it, not the way the ontology
declares it -- while the live path gave "10.50".
"""

import ast
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.ontology.decimal_text import decimal_text, exact_decimals

ROOT = Path(__file__).resolve().parents[2]


class TestTheText:
    @pytest.mark.parametrize(("value", "places", "text"), [
        ("10.500000000", None, "10.5"),
        ("10.500000000", 2, "10.50"),
        ("0E-9", 2, "0.00"),
        ("-0.5", 3, "-0.500"),
        ("1E+2", None, "100"),
        ("100.000000000", 2, "100.00"),
    ])
    def test_padded_to_the_declared_scale_in_plain_notation(self, value, places, text):
        assert decimal_text(Decimal(value), places) == text

    def test_never_rounded_to_the_declared_scale(self):
        """EXACT WINS OVER DECLARED. Rounding here would send a number
        other than the one stored and the one a filter compares with."""
        assert decimal_text(Decimal("10.555"), 2) == "10.555"

    def test_a_38_digit_value_survives(self):
        """silver's decimal(38, 9) at full width -- more digits than the
        default context's 28, which normalize() would have rounded."""
        value = Decimal("12345678901234567890123456789.123456789")
        assert Decimal(decimal_text(value, 2)) == value

    def test_a_value_that_is_not_finite_is_named_not_crashed(self):
        assert decimal_text(Decimal("NaN"), 2) == "NaN"
        assert decimal_text(Decimal("-Infinity")) == "-Infinity"

    def test_an_undeclarable_scale_falls_back_to_exact(self):
        assert decimal_text(Decimal("1.50"), "two") == "1.5"

    def test_only_decimals_are_touched(self):
        fields = {"amount": Decimal("10.500000000"), "count": 3, "name": "x", "gone": None}
        assert exact_decimals(fields, {"amount": {"decimal_places": 2}}) == {
            "amount": "10.50", "count": 3, "name": "x", "gone": None}


class TestTheApi:
    def test_a_route_without_a_response_model_sends_a_string(self):
        """THE FLOAT HALF. Installed by importing the app, for every
        route in the process -- so this builds a route of its own."""
        import api.app  # noqa: F401 -- installs the encoder

        app = FastAPI()

        @app.get("/v")
        def value():
            return {"v": Decimal("12345678901234567.89")}

        assert TestClient(app).get("/v").json() == {"v": "12345678901234567.89"}

    @pytest.mark.parametrize("route", ["search_objects_route", "get_object_detail_route"])
    def test_the_object_routes_send_the_declared_scale(self, route):
        """THE SCALE HALF, for the two routes that serve object fields.
        Checked in the source: what is at stake is that each route's
        answer goes through exact_decimals, and a behavioural test of
        that would be a test of exact_decimals again."""
        tree = ast.parse((ROOT / "api" / "routes.py").read_text())
        function = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == route)
        called = {node.func.id for node in ast.walk(function)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert {"exact_decimals", "_declared_fields"} <= called


def test_the_detail_route_answers_at_the_declared_scale():
    """BEHAVIOURAL, end to end through the route and its response model:
    a mediator serving silver's storage-scale Decimal, a field declaring
    two places, and the JSON the client would receive."""
    from types import SimpleNamespace

    from api.routes import ObjectDetailResponse, get_object_detail_route
    from core.intermediate_layer.auth import UserRecord

    declared = {"amount": {"type": "data", "data_type": "decimal", "decimal_places": 2},
                "note": {"type": "data"}}

    class Mediator:
        schema = {"Payment": {"fields": declared}}

        def visible_schema(self, user):
            return {"Payment": {"fields": declared}}

        def get_object(self, user, object_type, object_id, field_names, context=None):
            return {"amount": Decimal("10.500000000"), "note": "x"}

        def overlaid_fields(self, object_type, object_id, names):
            return {}

    request = SimpleNamespace(state=SimpleNamespace(
        generation=SimpleNamespace(mediator=Mediator())))
    answer = get_object_detail_route("Payment", "p1", request,
                                     UserRecord("u", "us-west", "r"))
    body = ObjectDetailResponse(**answer).model_dump(mode="json")
    assert body["fields"] == {"amount": "10.50", "note": "x"}
