"""src/elysium/core/ontology/retype.py: which tables a retype touches, which silver
tables the sync now refuses, what names the field, and the sentences the
dialog shows (slice R1). The sentences are also pinned against a real sync in
tests/integration/test_retype_from_the_ui.py; this checks their shape and the
derivations."""

from types import SimpleNamespace

import pyarrow as pa

from elysium.core.ontology import retype
from elysium.core.ontology.field_types import changed_column_types, same_arrow_type, schema_for_columns
from elysium.core.ontology.retype import changed_tables, places_naming, stored_data, tables_needing_rebuild
from elysium.core.ontology.used_by import used_by_field
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

    def test_a_column_the_source_no_longer_has_is_not_compared_as_the_sync_does_not(self):
        """The sync drops a vanished column before it compares, so listing
        the table would discard history for a refusal the sync never makes."""
        silver = pa.schema([("id", pa.string()), ("amount", pa.float64())])
        gone = [target(types={"amount": "decimal"})]

        assert tables_needing_rebuild(gone, lake(s__t=silver), lambda _: {"id"}) == []
        assert tables_needing_rebuild(gone, lake(s__t=silver), lambda _: {"id", "amount"}) == ["s.t"]

    def test_nothing_recorded_about_the_source_columns_compares_every_declared_column(self):
        silver = pa.schema([("id", pa.string()), ("amount", pa.float64())])

        assert tables_needing_rebuild([target(types={"amount": "decimal"})], lake(s__t=silver),
                                      lambda _: None) == ["s.t"]

    def test_only_the_tables_that_differ_are_listed_and_sorted(self):
        targets = [target(table="b", types={"amount": "decimal"}), target(table="a", types={"amount": "integer"}),
                   target(table="c")]
        text = pa.schema([("id", pa.string()), ("amount", pa.string())])
        silver = lake(s__a=self.SILVER, s__b=self.SILVER, s__c=text)

        assert tables_needing_rebuild(targets, silver) == ["s.a", "s.b"]


class TestTheSharedComparison:
    def test_it_is_the_one_the_sync_uses(self):
        import inspect

        from elysium.core.mirror import iceberg_sync

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
        said = stored_data(["silo.table"], ["Transaction"], "decimal", owed=["silo.table"])

        text = " ".join(said)
        assert said[0].startswith("Nothing is deleted from your source")
        assert "Silver of silo.table cannot take the new type in place" in text
        assert "rebuilt from bronze" in text and "snapshot history is discarded" in text
        assert "Bronze is not touched" in text
        assert "Gold of Transaction, if it was built, is rebuilt from the new silver" in text
        assert "publication tags from the first" in text
        assert "changelog and its history of publications are kept" in text
        assert "keep the values they had, in the old type" in text
        assert "first publication afterwards records no difference" in text
        assert "Until the rebuild, the sync refuses silver" in text

    def test_several_tables_are_all_named(self):
        text = " ".join(stored_data(["a.x", "b.y"], ["T"], "date", owed=["a.x", "b.y"]))

        assert "Silver of a.x, b.y cannot" in text and "refuses them until" in text

    def test_with_no_table_changed_it_does_not_claim_that_no_table_is_read(self):
        said = stored_data([], ["T"], "date", owed=[])

        assert any("does not change, so no silver or gold is rebuilt" in line for line in said)
        assert "shared table" in " ".join(said) and "later declaration" in " ".join(said)
        assert not any("No table is read" in line or "Gold of" in line for line in said)

    def test_a_table_not_built_or_already_matching_is_said_not_to_be_rebuilt_and_nothing_is_refused(self):
        said = " ".join(stored_data(["a.x", "b.y"], ["T"], "date", owed=["b.y"]))

        assert "Silver of b.y cannot take the new type" in said
        assert "Silver of a.x is not built yet or already has the new type, so nothing there is rebuilt" in said
        none = " ".join(stored_data(["a.x"], ["T"], "date", owed=[]))
        assert "Until the rebuild" not in none and "cannot take the new type" not in none

    def test_when_the_mirror_could_not_be_read_it_says_so_and_does_not_guess(self):
        said = " ".join(stored_data(["a.x"], ["T"], "date", owed=None))

        assert "could not be read" in said and "cannot say whether silver of a.x" in said

    def test_a_shared_table_names_every_type_whose_gold_is_skipped_and_rebuilt(self):
        said = " ".join(stored_data(["s.t"], ["Customer", "Vip"], "integer", owed=["s.t"]))

        assert "s.t is shared by Customer, Vip" in said and "gold of every one of them" in said
        assert "Gold of Customer, Vip" in said
        assert "shared by" not in " ".join(stored_data(["s.t"], ["Customer"], "integer", owed=["s.t"]))

    def test_under_refuse_a_value_that_cannot_convert_stops_the_sync_until_the_data_or_the_type_is_fixed(self):
        for mode in ("refuse", None):
            said = " ".join(stored_data(["s.t"], ["T"], "integer", owed=["s.t"], on_type_mismatch=mode))

            assert "stops with an error naming it" in said and "and so does the rebuild" in said
            assert "until the data at the source or the type is fixed" in said
            assert "set aside" not in said and "nothing is lost by waiting" not in said

    def test_under_quarantine_such_rows_are_set_aside_at_each_sync(self):
        said = " ".join(stored_data(["s.t"], ["T"], "integer", owed=["s.t"], on_type_mismatch="quarantine"))

        assert "its row is set aside in the quarantine table at every sync" in said
        assert "stops with an error" not in said and "nothing is lost by waiting" not in said


def test_the_places_that_name_a_field_are_the_used_by_report_and_no_second_reading():
    triggers = [built._trigger([{"field": "price"}])]
    args = (built._schema(), built.ROLES, built.ACTIONS, triggers, "Order", "price")

    found = places_naming(*args)

    assert found == used_by_field(*args)
    assert {item.kind for item in found} >= {"grant", "derived", "rule", "predicted", "unusual", "action",
                                              "trigger"}


def test_the_module_says_where_gold_goes_while_silver_is_refused():
    assert "SKIPPED" in retype.__doc__


class TestWhyAColumnIsNotRetyped:
    """retype.refusal: judged on the loaded schema and per column."""

    @staticmethod
    def schema(**fields):
        return {"A": {"storage": {"silo": "s", "table": "t", "id_column": "id"}, "id_field": "id",
                      "security": {"field": "region"},
                      "fields": {"region": {"type": "data"}, "plain": {"type": "data"}, **fields}}}

    @staticmethod
    def targets(security_column="region"):
        return [SimpleNamespace(silo_name="s", table_name="t", id_column="id", security_column=security_column,
                                object_types=frozenset({"A"}))]

    def test_a_plain_field_is_not_refused(self):
        assert retype.refusal(self.schema(), self.targets(), "A", "plain") is None

    def test_a_computed_field_is_refused_by_its_rule(self):
        schema = self.schema(c={"type": "data", "derived": {"add": ["plain", 1]}})

        assert "what its rule produces" in retype.refusal(schema, self.targets(), "A", "c")

    def test_the_security_field_of_the_loaded_schema_is_refused(self):
        assert "who may see each row" in retype.refusal(self.schema(), self.targets(), "A", "region")

    def test_a_column_the_targets_use_for_the_id_is_refused_under_any_field_name(self):
        schema = self.schema(ref={"type": "data", "column": "id"})

        assert "identifies the rows of A" in retype.refusal(schema, self.targets(), "A", "ref")

    def test_a_column_the_targets_use_for_security_is_refused_under_any_field_name(self):
        schema = self.schema(copy={"type": "data", "column": "region"})
        schema["A"]["security"] = "not a mapping here"

        assert "decides who may see the rows of A" in retype.refusal(schema, self.targets(), "A", "copy")

    def test_a_link_key_column_is_refused(self):
        schema = self.schema(owner={"type": "link", "link_type": "L", "column": "owner_id"},
                             raw={"type": "data", "column": "owner_id"})

        assert "joins on" in retype.refusal(schema, self.targets(), "A", "raw")

    def test_a_reverse_links_key_in_the_other_table_is_refused(self):
        schema = self.schema(others={"type": "link", "link_type": "L", "via_table": "t", "via_column": "fk",
                                     "via_target_column": "tag"},
                             raw={"type": "data", "column": "tag"})

        assert "joins on" in retype.refusal(schema, self.targets(), "A", "raw")

    def test_the_same_column_name_in_another_table_is_not_refused(self):
        schema = self.schema(copy={"type": "data", "column": "id", "storage": "other"})
        schema["A"]["additional_storage"] = {"other": {"silo": "s", "table": "u", "id_column": "k"}}

        assert retype.refusal(schema, self.targets(), "A", "copy") is None
