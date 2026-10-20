"""Numbers and dates as a source's people write them (DEP-1).

The owner's requirement (2026-10-12): numbers and dates load, "either
US format, or South American format, depending on where the Elysium
system is deployed". Measured against CLDR, "South American" is not one
format -- Peru writes numbers as the US does -- so a deployment names a
LOCALE, and a silo may override it. core/ontology/localised_values.py
has the table.
"""

import datetime
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.ontology.field_types import coerce
from core.ontology.localised_values import normalise_locale


class TestTheRules:
    @pytest.mark.parametrize("text, locale, expected", [
        ("1.234,56", "pt_BR", Decimal("1234.56")),
        ("1,234.56", "en_US", Decimal("1234.56")),
        ("1.234,56", "es_AR", Decimal("1234.56")),
        ("1,234.56", "es_PE", Decimal("1234.56")),   # Peru: the US's numbers
        ("-1.234,5", "pt_BR", Decimal("-1234.5")),
        ("12,5%", "pt_BR", Decimal("0.125")),         # a percentage is a fraction
        ("5%", "en_US", Decimal("0.05")),
    ])
    def test_a_decimal(self, text, locale, expected):
        assert coerce(text, "decimal", locale=locale) == expected

    def test_an_integer_written_with_grouping(self):
        assert coerce("1.234", "integer", locale="pt_BR") == 1234
        assert coerce("1,234", "integer", locale="en_US") == 1234

    @pytest.mark.parametrize("text, locale, expected", [
        ("02/01/2024", "pt_BR", datetime.date(2024, 1, 2)),
        ("02/01/2024", "en_US", datetime.date(2024, 2, 1)),   # month first
        ("02-01-2024", "es_CL", datetime.date(2024, 1, 2)),   # Chile: dashes
        ("2/1/2024", "es_PE", datetime.date(2024, 1, 2)),     # Peru: day first
        ("2024-01-02", "en_US", datetime.date(2024, 1, 2)),   # ISO, always
    ])
    def test_a_date(self, text, locale, expected):
        assert coerce(text, "date", locale=locale) == expected

    def test_a_timestamp_on_either_clock(self):
        assert coerce("1/2/2024 2:30 PM", "timestamp", locale="en_US") == \
            datetime.datetime(2024, 1, 2, 14, 30)
        assert coerce("02/01/2024 14:30", "timestamp", locale="pt_BR") == \
            datetime.datetime(2024, 1, 2, 14, 30)

    @pytest.mark.parametrize("text, data_type, locale, says", [
        ("1.5", "number", "pt_BR", "pt_BR"),            # malformed grouping, not 15
        ("1234.5", "number", "pt_BR", "pt_BR"),         # machine text in a pt_BR silo
        ("1,5", "number", "en_US", "en_US"),
        ("1/2/24", "date", "en_US", "two-digit year"),  # a century would be a guess
        ("31/02/2024", "date", "pt_BR", "real date"),
        ("5%", "integer", "en_US", "percentage"),
    ])
    def test_what_is_refused_rather_than_guessed(self, text, data_type, locale, says):
        with pytest.raises(ValueError, match=says):
            coerce(text, data_type, locale=locale)

    def test_without_a_locale_nothing_changes(self):
        """THE CONTROL, and the upgrade path."""
        with pytest.raises(ValueError):
            coerce("1.234,56", "decimal")


class TestTheDeclaration:
    def test_a_locale_is_named_as_cldr_names_it(self):
        assert normalise_locale("pt-BR", "x") == "pt_BR"
        assert normalise_locale("none", "x") is None

    def test_an_unknown_locale_is_refused_at_load(self):
        with pytest.raises(ValueError, match="not a locale"):
            normalise_locale("pt_BRR", "config.yaml source_locale")

    def test_a_silo_overrides_the_deployment(self, tmp_path):
        """A deployment in Sao Paulo reading a US export: the locale is
        the SOURCE's, so one silo can differ."""
        import shutil

        from core.deployment_loader import load_deployment

        shutil.copytree(Path("tests/integration/fixtures"), tmp_path / "etc",
                        ignore=shutil.ignore_patterns("other_deployment"))
        etc = tmp_path / "etc"
        (etc / "config.yaml").write_text((etc / "config.yaml").read_text()
                                         + "\nsource_locale: pt_BR\n")
        silos = (etc / "data_silos.yaml").read_text()
        (etc / "data_silos.yaml").write_text(
            silos.replace("  support_crm:\n", "  support_crm:\n    locale: en_US\n", 1))

        locales = load_deployment(etc).source_locales

        assert locales["primary_sql"] == "pt_BR"
        assert locales["support_crm"] == "en_US"


class TestThroughARealSync:
    @pytest.fixture
    def synced(self, tmp_path):
        source = tmp_path / "s.db"
        conn = sqlite3.connect(source)
        # `typed` IS A REAL NUMBER COLUMN: the database already says what
        # it is, so the locale must never touch it.
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, amount TEXT, typed REAL, seen TEXT)")
        conn.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", [
            ("1", "1.234,56", 1234.5, "02/01/2024"),
            ("2", "10,00", 0.25, "2024-03-04"),
        ])
        conn.commit()
        conn.close()

        def sync(locale):
            mirror = tmp_path / f"mirror-{locale}"
            sync = IcebergMirrorSync(mirror, {"s": SQLiteReadAdapter({"path": source})},
                                     on_type_mismatch="quarantine")
            sync.locales = {"s": locale}
            sync.sync_table("s", "t", "id", ["id", "amount", "typed", "seen"],
                            {"id": "string", "amount": "decimal", "typed": "number",
                             "seen": "date"})
            rows = sync._catalog.load_table("s.t").scan().to_arrow().to_pylist()
            return {row["id"]: row for row in rows}

        return sync

    def test_a_brazilian_silo_loads_its_numbers_and_dates(self, synced):
        rows = synced("pt_BR")

        assert rows["1"]["amount"] == Decimal("1234.56")
        assert rows["1"]["seen"] == datetime.date(2024, 1, 2)
        assert rows["2"]["seen"] == datetime.date(2024, 3, 4)

    def test_a_number_the_database_typed_is_never_read_through_the_locale(self, synced):
        """Bronze turns 1234.5 into the string "1234.5", which pt_BR
        would refuse. The column is judged by what the SOURCE sent."""
        rows = synced("pt_BR")

        assert rows["1"]["typed"] == 1234.5
        assert rows["2"]["typed"] == 0.25

    def test_with_no_locale_the_same_rows_are_set_aside(self, synced):
        """THE CONTROL: without the declaration, as before."""
        assert "1" not in synced(None)


class TestExponentFormIntegers:
    """ZOO-15: `1e3` is 1000, written unambiguously."""

    @pytest.mark.parametrize("text, expected", [("1e3", 1000), ("1E+03", 1000),
                                                ("-2.5E+04", -25000)])
    def test_an_exactly_whole_one_loads(self, text, expected):
        assert coerce(text, "integer") == expected

    @pytest.mark.parametrize("text", ["1.5e0", "1e-1"])
    def test_one_that_is_not_whole_is_refused_not_rounded(self, text):
        with pytest.raises(ValueError):
            coerce(text, "integer")


class TestExcelDateSerials:
    """ZOO-22: Excel's day count, only where a silo declares it."""

    def test_declared_a_serial_is_the_day_excel_means(self):
        assert coerce("45292", "date", excel_dates=True) == datetime.date(2024, 1, 1)
        assert coerce(45292, "date", excel_dates=True) == datetime.date(2024, 1, 1)
        assert coerce("45292.75", "timestamp", excel_dates=True) == \
            datetime.datetime(2024, 1, 1, 18, 0)

    def test_undeclared_a_serial_is_still_refused(self):
        """THE CONTROL: a bare number in a date column is ambiguous."""
        with pytest.raises(ValueError, match="ISO-8601"):
            coerce("45292", "date")

    @pytest.mark.parametrize("text, says", [
        ("60", "real day"),            # Excel's phantom 29 February 1900
        ("45292.5", "time of day"),    # a time, into a date field
    ])
    def test_what_is_refused(self, text, says):
        with pytest.raises(ValueError, match=says):
            coerce(text, "date", excel_dates=True)

    def test_the_declaration_must_be_a_boolean(self):
        from core.deployment_loader import _excel_date_silos

        assert _excel_date_silos({"a": {"excel_dates": True}, "b": {}}) == frozenset({"a"})
        with pytest.raises(ValueError, match="true or false"):
            _excel_date_silos({"a": {"excel_dates": "yes"}})

    def test_through_a_real_sync(self, tmp_path):
        source = tmp_path / "x.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, seen TEXT, typed REAL)")
        conn.execute("INSERT INTO t VALUES ('1', '45292', 45293)")
        conn.commit()
        conn.close()
        sync = IcebergMirrorSync(tmp_path / "mirror", {"x": SQLiteReadAdapter({"path": source})},
                                 on_type_mismatch="quarantine")
        sync.excel_date_silos = frozenset({"x"})

        sync.sync_table("x", "t", "id", ["id", "seen", "typed"],
                        {"id": "string", "seen": "date", "typed": "date"})

        (row,) = sync._catalog.load_table("x.t").scan().to_arrow().to_pylist()
        assert row["seen"] == datetime.date(2024, 1, 1)
        assert row["typed"] == datetime.date(2024, 1, 2)


class TestZeroDates:
    """MySQL's and MariaDB's '0000-00-00' for "no date" (20 October),
    found by the first run of Elysium over a simulated MariaDB."""

    @pytest.mark.parametrize("text", ["0000-00-00", "0000-00-00 00:00:00",
                                      "0000-00-00 00:00:00.000000", "0000-00-00T00:00:00"])
    @pytest.mark.parametrize("declared", ["date", "timestamp", "timestamptz"])
    def test_declared_they_are_empty(self, text, declared):
        assert coerce(text, declared, "UTC", zero_dates=True) is None

    def test_undeclared_they_are_refused_as_before(self):
        with pytest.raises(ValueError):
            coerce("0000-00-00", "date")

    @pytest.mark.parametrize("text", ["0000-01-01", "2026-00-00", "0000-00-00 10:00:00"])
    def test_only_a_wholly_zero_date_is_empty(self, text):
        with pytest.raises(ValueError):
            coerce(text, "timestamp", zero_dates=True)

    def test_a_text_field_keeps_it_as_written(self):
        assert coerce("0000-00-00", "string", zero_dates=True) == "0000-00-00"

    def test_the_declaration_is_read_per_silo_and_must_be_a_boolean(self):
        from core.deployment_loader import _excel_date_silos

        assert _excel_date_silos({"a": {"zero_dates_as_null": True}, "b": {}},
                                 key="zero_dates_as_null") == frozenset({"a"})
        with pytest.raises(ValueError, match="zero_dates_as_null must be true or false"):
            _excel_date_silos({"a": {"zero_dates_as_null": "yes"}}, key="zero_dates_as_null")

    def test_through_a_real_sync_and_the_refusal_says_how(self, tmp_path):
        source = tmp_path / "z.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, shipped TEXT)")
        conn.executemany("INSERT INTO t VALUES (?, ?)",
                         [("1", "0000-00-00 00:00:00"), ("2", "2026-01-02 03:04:05")])
        conn.commit()
        conn.close()

        def sync(declared):
            sync = IcebergMirrorSync(tmp_path / f"m-{declared}",
                                     {"s": SQLiteReadAdapter({"path": source})})
            sync.zero_date_silos = frozenset({"s"}) if declared else frozenset()
            return sync.sync_table("s", "t", "id", ["id", "shipped"],
                                   {"id": "string", "shipped": "timestamp"}), sync

        result, done = sync(True)
        rows = {r["id"]: r for r in done._catalog.load_table("s.t").scan().to_arrow().to_pylist()}
        assert rows["1"]["shipped"] is None
        assert rows["2"]["shipped"] == datetime.datetime(2026, 1, 2, 3, 4, 5)

        with pytest.raises(ValueError, match="zero_dates_as_null: true"):
            sync(False)


    def test_the_advice_is_for_a_wholly_zero_date_only(self):
        from core.mirror.transform import DriftedColumn, describe_drift

        def advice(value):
            return "zero_dates_as_null" in describe_drift("s", "t", [DriftedColumn(
                column="c", declared_type="timestamp", example_value=value,
                row_count_checked=1)])

        assert advice("0000-00-00 00:00:00")
        assert not advice("0000-00-00 12:00:00"), "not a zero date; declaring it would not help"
