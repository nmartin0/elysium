"""Counting the stored values that will not convert to a new type, from
bronze (core/mirror/retype_count; slice R3 of the retype design).

Real bronze, written by a real sync (the `synced_deployment` fixture).
"""

from datetime import UTC, datetime

import pyarrow as pa
import pytest

from core.mirror.catalog import open_mirror_catalog
from core.mirror.incremental import TEXT_COLUMNS_PROPERTY
from core.mirror.retype_count import count_unconvertible
from core.ontology.retype import stored_data


@pytest.fixture
def lake(synced_deployment):
    return open_mirror_catalog(synced_deployment.data_dir / "mirror")


def _count(lake, column, declared, **given):
    return count_unconvertible(lake, "primary_sql", "transactions", column, declared, **given)


class TestTheCount:
    def test_values_that_are_not_numbers_are_counted_out_of_all_the_values_read(self, lake):
        found = _count(lake, "currency", "integer")

        assert found.counted and found.checked > 1
        assert found.failing == found.checked        # 'USD' and 'EUR' are no integer
        assert found.as_of is not None and found.as_of <= datetime.now(UTC)

    def test_values_that_do_convert_are_not_counted(self, lake):
        found = _count(lake, "amount", "decimal")

        assert found.counted and found.checked > 1 and found.failing == 0

    def test_the_count_is_of_the_values_that_fail_not_of_all_of_them(self, lake):
        # 'USD'/'EUR' as text is nothing to convert, as a number it is everything.
        assert _count(lake, "currency", "string").failing == 0
        assert _count(lake, "currency", "number").failing == _count(lake, "currency", "number").checked > 0

    def test_a_cleaning_rule_of_the_column_is_applied_as_the_sync_would(self, lake):
        # The sync standardises before it coerces: a sentinel becomes a real NULL, which converts.
        rules = {"currency": {"unicode": False, "collapse_whitespace": False, "trim": False,
                              "null_if": ["USD", "EUR"]}}

        found = _count(lake, "currency", "integer", standardisation=rules)

        assert found.counted and found.failing == 0

    def test_text_that_arrived_as_text_is_read_through_the_silos_locale_as_the_sync_does(self, lake):
        lake.create_namespace("bronze_pt")
        table = lake.create_table("bronze_pt.prices", schema=pa.schema([("price", pa.string())]),
                                  properties={TEXT_COLUMNS_PROPERTY: '["price"]'})
        table.append(pa.table({"price": ["1.234,50", "10,5", "abc"]}))

        brazilian = count_unconvertible(lake, "pt", "prices", "price", "decimal", locale="pt_BR")
        unlocalised = count_unconvertible(lake, "pt", "prices", "price", "decimal")

        assert (brazilian.checked, brazilian.failing) == (3, 1)         # only "abc"
        assert (unlocalised.checked, unlocalised.failing) == (3, 3)     # without the locale none of the three reads

    def test_a_table_bronze_does_not_hold_is_not_counted_and_says_why_never_zero(self, lake):
        found = count_unconvertible(lake, "primary_sql", "no_such_table", "amount", "decimal")

        assert not found.counted and found.failing == 0 and "nothing to count" in (found.why_not or "")

    def test_a_column_bronze_does_not_hold_is_not_counted(self, lake):
        found = _count(lake, "no_such_column", "decimal")

        assert not found.counted and "no_such_column" in (found.why_not or "")

    def test_a_table_too_large_to_count_while_waiting_is_not_counted_not_part_counted(self, lake):
        found = _count(lake, "currency", "integer", max_rows=1)

        assert not found.counted and "more than is counted" in (found.why_not or "")

    def test_a_catalog_that_fails_is_not_counted(self):
        class Broken:
            def load_table(self, name):
                raise RuntimeError("no catalog")

        found = count_unconvertible(Broken(), "s", "t", "c", "integer")

        assert not found.counted and "RuntimeError" in (found.why_not or "")


class TestWhatTheDialogSays:
    def test_a_count_is_said_with_where_it_is_from_and_as_of_when(self, lake):
        found = _count(lake, "currency", "integer")

        said = stored_data(["primary_sql.transactions"], ["Transaction"], "integer", owed=[],
                           on_type_mismatch="quarantine", conversions=[found])

        line = next(each for each in said if each.startswith("Counted in bronze"))
        assert f"{found.failing:,} of {found.checked:,} values of currency in primary_sql.transactions" in line
        assert f"{found.as_of:%d %b %Y %H:%M} UTC" in line and "changed at the source since" in line
        assert said[-1].startswith("If a stored value cannot be read as integer, its row is set aside")

    def test_a_count_that_could_not_be_made_says_so_instead_of_a_number(self, lake):
        found = _count(lake, "currency", "integer", max_rows=1)

        said = stored_data(["primary_sql.transactions"], ["Transaction"], "integer", owed=[],
                           on_type_mismatch="refuse", conversions=[found])

        assert any(each.startswith("The values that will not convert were NOT counted for primary_sql.transactions")
                   for each in said)
        assert not any(each.startswith("Counted in bronze") for each in said)
        assert said[-1].startswith("If a stored value cannot be read as integer, the sync of that table stops")
