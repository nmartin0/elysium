"""
A live read returns the type the ontology declares.

MEASURED BEFORE THE FIX, same field and same ontology:

    mirror  ->  Decimal('49.990000000')
    silo    ->  49.99                    as a FLOAT

The sync coerces on the way into silver, so a mirror read already
returns what was promised. A live read handed back whatever the driver
produced.

THAT MATTERS MORE WITH A REAL DATABASE, which is why this comes before
the PostgreSQL adapter rather than after. SQLite has few types and
returns str, int and float. psycopg returns Decimal, datetime, date
and UUID objects -- none of which the ontology's vocabulary names --
so a PostgreSQL adapter would WIDEN this gap rather than reveal it.
"""

import datetime
import decimal

import pytest

from core.intermediate_layer.auth import UserRecord


@pytest.fixture
def mediator(tmp_path):
    from core.deployment_loader import build_generation, resolve_runtime_paths

    paths = resolve_runtime_paths()
    return build_generation(
        paths.config_dir, data_dir=tmp_path, log_dir=tmp_path / "log",
    ).mediator


@pytest.fixture
def user():
    return UserRecord("debug", "us-west", "debug")


class TestARawValueBecomesItsDeclaredType:
    def test_a_float_becomes_a_decimal(self, mediator):
        assert mediator._as_declared("Transaction", "amount", 49.99) == (
            decimal.Decimal("49.99")
        )

    def test_a_string_becomes_a_date(self, mediator):
        assert mediator._as_declared(
            "Transaction", "transaction_date", "2026-05-01",
        ) == datetime.date(2026, 5, 1)

    def test_an_already_correct_value_is_unchanged(self, mediator):
        value = decimal.Decimal("10.50")

        assert mediator._as_declared("Transaction", "amount", value) == value


class TestWhereItDoesNotApply:
    def test_none_stays_none(self, mediator):
        # A real NULL is not a type error, here as in the sync.
        assert mediator._as_declared("Transaction", "amount", None) is None

    def test_an_undeclared_field_is_left_alone(self, mediator, caplog):
        """NO EXPECTATION TO VIOLATE. Declaring a type is how an author
        opts in, the same bargain the filter-operator check makes.

        AND IT MUST NOT COMPLAIN. A control removing the `declared is
        None` guard did not fail the first version of this test,
        because coerce() RAISES on an unknown type and the except
        clause swallowed it -- returning the right value while logging
        a warning about a field that had done nothing wrong.

        The value assertion could not see that. The log assertion can.
        """
        with caplog.at_level("WARNING"):
            assert mediator._as_declared("Transaction", "category", 42) == 42

        assert caplog.text == ""


class TestAFailureIsReportedAndServed:
    def test_a_value_that_cannot_be_coerced_passes_through(self, mediator, caplog):
        """THE SYNC CAN REFUSE A WHOLE TABLE because a refused sync
        leaves the previous snapshot standing. A READ has no previous
        value to fall back on, and refusing would turn a type
        disagreement into an unreadable object.
        """
        assert mediator._as_declared("Transaction", "amount", "banana") == "banana"

    def test_and_it_says_so(self, mediator, caplog):
        # SILENT WOULD BE WORSE THAN WRONG. The value is served, and
        # the log is the only trace that it should not have been.
        with caplog.at_level("WARNING"):
            mediator._as_declared("Transaction", "amount", "banana")

        assert "does not match the declared type" in caplog.text


def test_every_declared_type_survives_a_raw_value(mediator):
    """THE PROPERTY THAT MATTERS: a reader must not be able to tell
    which path served them by looking at the type of what came back.

    A FIRST VERSION READ AN ACTUAL OBJECT through get_field and
    compared the two paths. It failed on None -- the fixture builds
    against a FRESH data directory, so the mirror is empty and there
    is no object 1 to read. The measurement that motivated this commit
    was taken against a populated deployment; a unit test cannot
    assume one.

    So the raw shapes each adapter produces are driven through the
    coercer directly instead, which is the part this commit changed.
    """
    raw_shapes = {
        "amount": [49.99, "49.99", decimal.Decimal("49.99")],
        "transaction_date": ["2026-05-01", datetime.date(2026, 5, 1)],
    }
    expected = {"amount": decimal.Decimal, "transaction_date": datetime.date}

    for field, values in raw_shapes.items():
        for value in values:
            assert isinstance(
                mediator._as_declared("Transaction", field, value), expected[field],
            ), f"{field} did not honour its declared type for {value!r}"
