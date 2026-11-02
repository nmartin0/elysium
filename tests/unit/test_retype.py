"""core/ontology/retype.py: which tables a retype touches, which silver
tables the sync now refuses, what names the field, and the sentences the
dialog shows (slice R1). The sentences are also pinned against a real sync in
tests/integration/test_retype_from_the_ui.py; this checks their shape and the
derivations."""

from types import SimpleNamespace

import pyarrow as pa

from core.ontology import retype
from core.ontology.field_types import changed_column_types, same_arrow_type, schema_for_columns
from core.ontology.retype import changed_tables, places_naming, stored_data, tables_needing_rebuild
from core.ontology.used_by import used_by_field
from tests.unit import test_used_by as built


def target(silo="s", table="t", columns=("id", "amount"), types=None):
    return SimpleNamespace(silo_name=silo, table_name=table, columns=list(columns), column_types=types or {})


def lake(**tables):
    """silver_schema_of over {"silo.table": pa.schema}; absent is None."""
    return lambda identifier: tables.get(identifier.replace(".", "__"))


class TestWhichTablesARetypeTouches:
    def test_the_table_whose_declared_types_differ(self):
        before = [target(types={}), target(table="u", types={"x": "number"})]
        after = [target(types={"amount": "decimal"}), target(table="u", types={"x": "number"})]

        assert changed_tables(before, after) == ["s.t"]

    def test_nothing_when_nothing_differs(self):
        assert changed_tables([target()], [target()]) == []

    def test_a_table_new_in_one_configuration_is_not_a_retype(self):
        assert changed_tables([], [target(types={"amount": "decimal"})]) == []

    def test_a_table_two_types_share_is_listed_once(self):
        assert changed_tables([target(types={"a": "number"})],
                              [target(types={"a": "decimal", "b": "date"})]) == ["s.t"]


class TestWhichSilverTablesNeedARebuild:
    SILVER = pa.schema([("id", pa.string()), ("amount", pa.float64())])

    def test_a_table_whose_silver_has_the_old_type(self):
        found = tables_needing_rebuild([target(types={"amount": "decimal"})], lake(s__t=self.SILVER))

        assert found == ["s.t"]

    def test_a_table_that_matches_is_not_listed(self):
        assert tables_needing_rebuild([target(types={"amount": "number"})], lake(s__t=self.SILVER)) == []

    def test_large_string_is_string_so_an_unchanged_text_column_never_asks_for_a_rebuild(self):
        """Iceberg returns large_string for what we wrote as string: the
        spelling rule the sync uses, or every table would be listed."""
        iceberg = pa.schema([("id", pa.large_string()), ("amount", pa.large_string())])

        assert tables_needing_rebuild([target()], lake(s__t=iceberg)) == []

    def test_a_table_never_built_has_nothing_to_rebuild(self):
        assert tables_needing_rebuild([target(types={"amount": "decimal"})], lake()) == []

    def test_a_column_on_one_side_only_is_a_new_column_not_a_type_change(self):
        silver = pa.schema([("id", pa.string())])

        assert tables_needing_rebuild([target(types={"amount": "decimal"})], lake(s__t=silver)) == []

    def test_the_source_zone_of_a_timestamptz_is_not_part_of_the_type(self):
        silver = pa.schema([("id", pa.string()), ("at", pa.timestamp("us", tz="UTC"))])

        assert tables_needing_rebuild(
            [target(columns=("id", "at"), types={"at": "timestamptz@Europe/Paris"})], lake(s__t=silver)) == []

    def test_only_the_tables_that_differ_are_listed_and_sorted(self):
        targets = [target(table="b", types={"amount": "decimal"}), target(table="a", types={"amount": "integer"}),
                   target(table="c")]
        text = pa.schema([("id", pa.string()), ("amount", pa.string())])
        silver = lake(s__a=self.SILVER, s__b=self.SILVER, s__c=text)

        assert tables_needing_rebuild(targets, silver) == ["s.a", "s.b"]


class TestTheSharedComparison:
    def test_it_is_the_one_the_sync_uses(self):
        import inspect

        from core.mirror import iceberg_sync

        assert "changed_column_types" in inspect.getsource(iceberg_sync._refuse_a_changed_declared_type)
        assert "schema_for_columns" in inspect.getsource(iceberg_sync.IcebergMirrorSync._to_arrow)

    def test_spellings(self):
        assert same_arrow_type(pa.string(), pa.large_string()) and same_arrow_type(pa.large_binary(), pa.binary())
        assert not same_arrow_type(pa.string(), pa.int64())

    def test_the_schema_for_columns_defaults_to_string(self):
        schema = schema_for_columns(["a", "b"], {"b": "integer"})

        assert [(f.name, f.type) for f in schema] == [("a", pa.string()), ("b", pa.int64())]
        assert schema_for_columns(["a"]).field("a").type == pa.string()

    def test_changed_column_types_reports_what_it_has_and_what_is_declared(self):
        have = pa.schema([("a", pa.string()), ("b", pa.float64())])
        want = pa.schema([("a", pa.large_string()), ("b", pa.decimal128(38, 9)), ("c", pa.int64())])

        assert changed_column_types(have, want) == [("b", "double", "decimal128(38, 9)")]


class TestWhatItSaysAboutStoredData:
    def test_what_changes_and_what_stays(self):
        said = stored_data(["silo.table"], "Transaction")

        text = " ".join(said)
        assert said[0].startswith("Nothing is deleted from your source")
        assert "Silver of silo.table cannot take the new type in place" in text
        assert "rebuilt from bronze" in text and "snapshot history is discarded" in text
        assert "Bronze is not touched" in text
        assert "Gold of Transaction is rebuilt from the new silver" in text
        assert "publication tags from the first" in text
        assert "changelog and its history of publications are kept" in text
        assert "keep the values they had, in the old type" in text
        assert "first publication afterwards records no difference" in text
        assert "not counted yet" in text

    def test_several_tables_are_all_named(self):
        text = " ".join(stored_data(["a.x", "b.y"], "T"))

        assert "Silver of a.x, b.y cannot" in text and "refuses them until" in text

    def test_with_no_table_read_it_says_there_is_nothing_to_rebuild(self):
        said = stored_data([], "T")

        assert any("no silver or gold to rebuild" in line for line in said)
        assert not any("Gold of" in line for line in said)


def test_the_places_that_name_a_field_are_the_used_by_report_and_no_second_reading():
    triggers = [built._trigger([{"field": "price"}])]
    args = (built._schema(), built.ROLES, built.ACTIONS, triggers, "Order", "price")

    found = places_naming(*args)

    assert found == used_by_field(*args)
    assert {item.kind for item in found} >= {"grant", "derived", "rule", "predicted", "unusual", "action",
                                              "trigger"}


def test_the_module_says_where_gold_goes_while_silver_is_refused():
    assert "SKIPPED" in retype.__doc__
