"""
A malformed decimal is drift, not a crash (PA001-C1, PR001-R36).

THE MECHANISM IS A TYPE HIERARCHY DETAIL. `decimal.InvalidOperation`
derives from ArithmeticError, NOT from ValueError -- so it sailed
straight through core/mirror/transform.py's

    except (ValueError, TypeError):

which is the handler that turns a bad value into a named
DriftedColumn. No column, no example value, no row count. run_sync
recorded the entire table's refusal as:

    "[<class 'decimal.ConversionSyntax'>]"

ONE BAD CELL IN TEN THOUSAND GOOD ONES DOES THIS, and the values that
cause it are the ordinary contents of a money column somebody has been
typing into by hand: "$5.00", "N/A", "1,234", "TBD".

THE TABLE WAS ALWAYS GOING TO BE REFUSED -- that part was right, and
PR001-R22 is the separate question of whether ONE bad cell should
refuse every row. What was wrong was that the operator was told
nothing they could act on. A refusal nobody can diagnose is an outage
with extra steps.

AND DECIMAL WAS THE ONLY ONE. Every declared type was run against
sixteen kinds of junk; nothing else escapes as anything but a
ValueError. The last test here keeps it that way.
"""

import decimal
import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.transform import transform_rows
from core.ontology.field_types import coerce

BAD_MONEY = ["$5.00", "N/A", "1,234", "TBD", "5%", "(3.00)", "3.00 USD"]


class TestTheValueIsReportedAsDrift:
    @pytest.mark.parametrize("value", BAD_MONEY)
    def test_coercion_raises_a_ValueError(self, value):
        """The type the whole pipeline catches."""
        with pytest.raises(ValueError):
            coerce(value, "decimal")

    @pytest.mark.parametrize("value", BAD_MONEY)
    def test_the_transform_reports_drift_rather_than_raising(self, value):
        result = transform_rows([{"id": "1", "v": value}], ["id", "v"],
                                 {"v": "decimal"}, {})

        assert result.has_drift
        assert result.drift[0].column == "v"

    def test_the_message_names_the_value(self):
        """So the operator can go and look at it."""
        with pytest.raises(ValueError, match=r"\$5\.00"):
            coerce("$5.00", "decimal")


class TestThroughARealSync:
    def test_the_refusal_names_the_column_the_value_and_the_count(self, tmp_path):
        """THE REGRESSION TEST. This message used to be
        "[<class 'decimal.ConversionSyntax'>]"."""
        source = tmp_path / "s.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT, price TEXT)")
        conn.executemany("INSERT INTO t VALUES (?,?)",
                         [(str(i), "9.99") for i in range(99)] + [("x", "$5.00")])
        conn.commit()
        conn.close()
        sync = IcebergMirrorSync(tmp_path / "m",
                                  {"p": SQLiteReadAdapter({"path": source})})

        with pytest.raises(ValueError) as raised:
            sync.sync_table("p", "t", "id", ["id", "price"], {"price": "decimal"})

        message = str(raised.value)
        assert "price" in message
        assert "$5.00" in message
        assert "100 rows" in message

    def test_the_mirror_is_left_alone(self, tmp_path):
        """Refusing is correct; refusing AND half-writing would not
        be."""
        source = tmp_path / "s2.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT, price TEXT)")
        conn.execute("INSERT INTO t VALUES ('1','9.99')")
        conn.commit()
        conn.close()
        sync = IcebergMirrorSync(tmp_path / "m2",
                                  {"p": SQLiteReadAdapter({"path": source})})
        sync.sync_table("p", "t", "id", ["id", "price"], {"price": "decimal"})

        conn = sqlite3.connect(source)
        conn.execute("INSERT INTO t VALUES ('2','$5.00')")
        conn.commit()
        conn.close()
        with pytest.raises(ValueError):
            sync.sync_table("p", "t", "id", ["id", "price"], {"price": "decimal"})

        served = sync.catalog.load_table("p.t").scan().to_arrow().to_pylist()
        assert [r["id"] for r in served] == ["1"]


class TestGoodValuesStillWork:
    @pytest.mark.parametrize("value,expected", [
        ("9.99", "9.99"), ("0", "0"), ("-3.50", "-3.50"),
        ("1E+2", "100"), (" 4.25 ", "4.25"),
    ])
    def test_ordinary_money_parses(self, value, expected):
        assert coerce(value, "decimal") == decimal.Decimal(expected)


class TestNoOtherTypeLeaks:
    """DECIMAL WAS THE ONLY ONE, checked rather than assumed: every
    declared type against sixteen kinds of junk. A future type whose
    parser raises its own exception class would reintroduce exactly
    this defect, silently, and this is where that shows up."""

    JUNK = ["", " ", "N/A", "$5", "1e999", "--1", "0x1F", "１２", "1,5",
            "\u221e", "\x00", "None", "[]", "{}", "TBD", "5%"]

    @pytest.mark.parametrize("data_type", [
        "integer", "number", "boolean", "date", "decimal",
        "timestamp", "timestamptz", "string",
    ])
    def test_junk_only_ever_produces_drift_or_a_value_error(self, data_type):
        for junk in self.JUNK:
            try:
                transform_rows([{"id": "1", "v": junk}], ["id", "v"],
                                {"v": data_type}, {})
            except ValueError:
                pass
            except Exception as e:  # noqa: BLE001 - the point of the test
                pytest.fail(f"{data_type} raised {type(e).__module__}."
                            f"{type(e).__name__} for {junk!r}: the drift handler "
                            f"catches ValueError and TypeError only")
