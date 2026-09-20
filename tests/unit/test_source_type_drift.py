"""
What the source SAID its columns were, kept and compared.

COERCION CANNOT SEE A TYPE CHANGE. Three silent failures were measured
earlier: timestamptz -> timestamp loses the offset, numeric -> float
loses scale, and integer -> text is absorbed by int() with the
whitespace along with it. Every one produces plausible data and no
error.

SO THE PREVIOUS SYNC'S ANSWER IS KEPT on the bronze table and compared
against the next one. Debezium's schema history is the same idea, and
Elysium already has config_history doing it for the other side of the
same question.

VERBATIM, NOT NORMALISED. Normalising means deciding NUMERIC(12,2) and
DECIMAL(12,2) are the same thing, and being wrong about that on an
engine nobody here has met. "The source said NUMERIC(12,2)" is a fact;
"the source said decimal" is an interpretation.
"""

import json
import logging
import sqlite3

import pytest

from core.mirror.iceberg_sync import (
    SOURCE_TYPES_PROPERTY,
    _report_type_drift,
    _source_types_json,
)


class _Adapter:
    def __init__(self, types):
        self._types = types

    def source_column_types(self, table_name):
        return self._types


class _BrokenAdapter:
    def source_column_types(self, table_name):
        raise RuntimeError("the source is unreachable")


class TestCapturingWhatTheSourceSaid:
    def test_it_serialises_the_types(self):
        captured = _source_types_json(
            _Adapter({"amount": "NUMERIC(12,2)"}), "t",
        )

        assert json.loads(captured) == {"amount": "NUMERIC(12,2)"}

    def test_an_adapter_that_cannot_say_yields_nothing(self):
        """EMPTY IS A THIRD STATE beside "same" and "changed". Storing
        {} would make the NEXT sync report every column as removed."""
        assert _source_types_json(_Adapter({}), "t") == ""

    def test_a_failing_adapter_costs_only_the_comparison(self):
        # DRIFT REPORTING IS NOT A READ PATH. A source that cannot
        # answer this must not stop the sync that is reading it.
        assert _source_types_json(_BrokenAdapter(), "t") == ""


class TestReportingWhatChanged:
    def test_a_changed_type_is_reported(self, caplog):
        with caplog.at_level(logging.WARNING):
            _report_type_drift(
                "s", "t",
                json.dumps({"amount": "NUMERIC(12,2)"}),
                json.dumps({"amount": "REAL"}),
            )

        assert "amount" in caplog.text
        assert "NUMERIC(12,2)" in caplog.text

    def test_it_says_why_that_matters(self, caplog):
        """"COERCION CANNOT SEE THIS" is the part somebody needs. A
        line saying a type changed reads as bookkeeping."""
        with caplog.at_level(logging.WARNING):
            _report_type_drift(
                "s", "t", json.dumps({"a": "INTEGER"}), json.dumps({"a": "TEXT"}),
            )

        assert "Coercion cannot see this" in caplog.text

    def test_an_unchanged_schema_is_silent(self, caplog):
        with caplog.at_level(logging.WARNING):
            _report_type_drift(
                "s", "t", json.dumps({"a": "INTEGER"}), json.dumps({"a": "INTEGER"}),
            )

        assert caplog.text == ""

    def test_a_widening_is_named_as_one(self, caplog):
        """THE CANONICAL SEVERITY MODEL puts a removed column and an
        incompatible narrowing in one band, and widening -- INT to
        BIGINT -- in a lesser one. Reporting both identically wastes
        the distinction."""
        with caplog.at_level(logging.WARNING):
            _report_type_drift(
                "s", "t",
                json.dumps({"n": "INTEGER"}), json.dumps({"n": "BIGINT"}),
            )

        assert "widened" in caplog.text

    def test_anything_else_is_a_plain_change(self, caplog):
        # DELIBERATELY SHALLOW. A full compatibility matrix per dialect
        # is a library's job; this recognises the obvious widenings and
        # is honest about the rest.
        with caplog.at_level(logging.WARNING):
            _report_type_drift(
                "s", "t", json.dumps({"a": "TEXT"}), json.dumps({"a": "INTEGER"}),
            )

        assert "CHANGED" in caplog.text

    def test_a_new_column_is_not_a_type_change(self, caplog):
        """THE ROW-LEVEL DRIFT POLICY ALREADY HANDLES columns appearing
        and disappearing. This answers the question that policy cannot
        see: whether a column still present still MEANS the same."""
        with caplog.at_level(logging.WARNING):
            _report_type_drift(
                "s", "t", json.dumps({"a": "TEXT"}),
                json.dumps({"a": "TEXT", "b": "INTEGER"}),
            )

        assert caplog.text == ""

    def test_unreadable_stored_types_are_skipped(self, caplog):
        with caplog.at_level(logging.WARNING):
            _report_type_drift("s", "t", "not json", json.dumps({"a": "TEXT"}))

        assert caplog.text == ""


class TestWhatEachAdapterCanSay:
    def test_sqlite_cannot_say(self, tmp_path):
        """SQLITE CANNOT REPORT TYPES THROUGH A READ-ONLY CONNECTION.
        PRAGMA returns "not authorized" -- the authorizer denying
        everything but SELECT is the guarantee that a read adapter
        cannot write -- and `SELECT * LIMIT 0` carries names without
        types, verified.

        Routing around that to answer a diagnostic would trade a
        structural write guarantee for a nicety.
        """
        from adapters.sqlite_adapter import SQLiteReadAdapter

        db = tmp_path / "t.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE t (a NUMERIC(12,2))")
        conn.commit()
        conn.close()

        assert SQLiteReadAdapter({"path": db}).source_column_types("t") == {}

    def test_postgresql_can(self):
        """A REAL DATABASE ANSWERS PROPERLY, through Core's Inspector,
        uniformly across every dialect -- and a customer's data lives
        there while SQLite is the embedded fixture case."""
        pytest.importorskip("pgserver")
        import tempfile

        import pgserver
        import psycopg

        from adapters.sqlalchemy_adapter import SQLAlchemyReadAdapter

        server = pgserver.get_server(tempfile.mkdtemp())
        with psycopg.connect(server.get_uri()) as conn, conn.cursor() as cur:
            cur.execute("CREATE TABLE t (amount numeric(12,2))")
            conn.commit()

        adapter = SQLAlchemyReadAdapter({
            "url": server.get_uri().replace(
                "postgresql://", "postgresql+psycopg://"),
        })

        assert adapter.source_column_types("t") == {"amount": "NUMERIC(12, 2)"}


def test_the_property_lives_on_bronze():
    """BRONZE, NOT SILVER: bronze is what the source looked like, and
    this is a fact about the SOURCE rather than about the mirror."""
    assert SOURCE_TYPES_PROPERTY.startswith("elysium.")
