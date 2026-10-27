"""Adding an object type (core/config_editing.apply_new_type) -- the lines,
the two file layouts, and what it refuses. The routes are in
tests/integration/test_new_type_from_the_ui.py.
"""

import pytest
import yaml

from core.config_editing import ConfigEditError
from core.config_editing import apply_new_type as _apply_new_type
from core.ontology.field_types import FIELD_DATA_TYPES

ONTOLOGY = """\
# The ontology.
object_types:
  Customer:
    id_field: customer_id
    fields:
      name:
        type: data
      # Kept for last: a note that belongs after the final field.
"""

BINDINGS = """\
# Where it comes from.
object_types:
  Customer:
    storage:
      silo: primary_sql
      table: customers
      id_column: customer_id
"""

SILOS = {"primary_sql": {"field": "region"}, "open_sql": None}


def apply_new_type(addition, bindings=BINDINGS, ontology=ONTOLOGY, silos=SILOS):
    return _apply_new_type(ontology, bindings, addition, FIELD_DATA_TYPES, silos)


def _type(**given):
    return {"name": "Ticker", "silo": "primary_sql", "table": "tickers", "id_column": "symbol",
            "fields": [{"name": "company"}, {"name": "sector"}], "security": "inherit", **given}


class TestTheLinesItWrites:
    def test_the_type_goes_last_and_the_comment_after_customer_stays(self):
        ontology, _ = apply_new_type(_type())

        assert ontology.startswith(ONTOLOGY)
        declared = yaml.safe_load(ontology)["object_types"]["Ticker"]
        assert declared == {"id_field": "symbol", "security": "inherit",
                            "fields": {"company": {"type": "data"}, "sector": {"type": "data"}}}

    def test_the_source_goes_to_the_bindings_file_when_there_is_one(self):
        ontology, bindings = apply_new_type(_type())

        assert "storage" not in yaml.safe_load(ontology)["object_types"]["Ticker"]
        assert yaml.safe_load(bindings)["object_types"]["Ticker"] == {
            "storage": {"silo": "primary_sql", "table": "tickers", "id_column": "symbol"}}
        assert bindings.startswith(BINDINGS)

    def test_with_no_bindings_file_the_source_sits_in_the_type(self):
        ontology, bindings = apply_new_type(_type(), bindings=None)

        assert bindings is None
        assert yaml.safe_load(ontology)["object_types"]["Ticker"]["storage"] == {
            "silo": "primary_sql", "table": "tickers", "id_column": "symbol"}

    def test_a_field_named_otherwise_than_its_column_is_bound(self):
        fields = [{"name": "company", "column": "co_name", "data_type": "string"},
                  {"name": "price", "data_type": "decimal"}]
        ontology, bindings = apply_new_type(_type(fields=fields))

        assert yaml.safe_load(bindings)["object_types"]["Ticker"]["fields"] == {
            "company": {"column": "co_name"}}
        declared = yaml.safe_load(ontology)["object_types"]["Ticker"]["fields"]
        assert declared["price"] == {"type": "data", "data_type": "decimal"}
        assert "column" not in declared["company"]

        inline, _ = apply_new_type(_type(fields=fields), bindings=None)
        assert yaml.safe_load(inline)["object_types"]["Ticker"]["fields"]["company"]["column"] == "co_name"

    def test_a_column_named_like_its_field_is_not_bound_twice(self):
        ontology, bindings = apply_new_type(_type(fields=[{"name": "company", "column": "company"}]))

        assert "fields" not in yaml.safe_load(bindings)["object_types"]["Ticker"]

    def test_names_title_listing_and_id_type_are_written(self):
        ontology, bindings = apply_new_type(_type(
            display_name="Stock ticker", plural_display_name="Stock tickers",
            description="yes", title_field="company", discoverable=True,
            id_field="ticker_symbol", id_type="integer"))

        declared = yaml.safe_load(ontology)["object_types"]["Ticker"]
        assert declared["display_name"] == "Stock ticker" and declared["plural_display_name"] == "Stock tickers"
        assert declared["description"] == "yes" and declared["title_field"] == "company"
        assert declared["discoverable"] is True and declared["id_field"] == "ticker_symbol"
        assert yaml.safe_load(bindings)["object_types"]["Ticker"]["storage"]["id_type"] == "integer"

    def test_a_type_is_not_listed_unless_asked(self):
        ontology, _ = apply_new_type(_type())
        assert "discoverable" not in yaml.safe_load(ontology)["object_types"]["Ticker"]


class TestItsRowRuleIsAlwaysChosen:
    def test_inherit_needs_a_source_that_declares_one(self):
        with pytest.raises(ConfigEditError, match="open_sql declares no row rule"):
            apply_new_type(_type(silo="open_sql"))

    def test_unrestricted_is_written_as_the_word(self):
        ontology, _ = apply_new_type(_type(security="unrestricted", silo="open_sql"))
        assert yaml.safe_load(ontology)["object_types"]["Ticker"]["security"] == "unrestricted"

    def test_a_field_rule_must_be_one_of_the_fields(self):
        ontology, _ = apply_new_type(_type(security={"field": "sector"}))
        assert yaml.safe_load(ontology)["object_types"]["Ticker"]["security"] == {"field": "sector"}
        with pytest.raises(ConfigEditError, match="Choose who may see"):
            apply_new_type(_type(security={"field": "nope"}))

    @pytest.mark.parametrize("missing", [None, "", "public", {"via_field": "x"}, 3])
    def test_there_is_no_default(self, missing):
        with pytest.raises(ConfigEditError, match="Choose who may see"):
            apply_new_type(_type(security=missing))


class TestWhatItRefuses:
    @pytest.mark.parametrize("given, match", [
        ({"name": "ticker"}, "not a type name"),
        ({"name": "Customer"}, "already an object type"),
        ({"silo": "nowhere"}, "no source"),
        ({"table": None}, "needs a table"),
        ({"fields": []}, "at least one field"),
        ({"fields": [{"name": "a"}, {"name": "a"}]}, "named twice"),
        ({"fields": [{"name": "symbol"}]}, "named twice"),
        ({"fields": [{"name": "Bad Name"}]}, "not a field name"),
        ({"fields": [{"name": "a", "data_type": "blob"}]}, "data type is one of"),
        ({"fields": [{"name": "a", "colour": "red"}]}, "A field is"),
        ({"title_field": "nope"}, "title column"),
        ({"id_type": "blob"}, "id type is one of"),
        ({"id_column": "Bad Col"}, "not be the id's name"),
        ({"discoverable": "yes"}, "on or off"),
        ({"surprise": 1}, "cannot be set"),
    ])
    def test_it_refuses(self, given, match):
        with pytest.raises(ConfigEditError, match=match):
            apply_new_type(_type(**given))

    def test_a_deployment_with_no_bindings_to_add_to_is_refused(self):
        with pytest.raises(ConfigEditError, match="binds no object types"):
            apply_new_type(_type(), bindings="# empty\nobject_types: {}\n".replace(" {}", ""))


class TestWhereItLands:
    def test_the_comment_that_ends_the_previous_type_stays_with_it(self):
        """A note at the end of Customer's block belongs to Customer; the
        new type goes after it, not between Customer and its own note."""
        ontology, _ = apply_new_type(_type())
        lines = ontology.splitlines()

        assert lines.index("      # Kept for last: a note that belongs after the final field.") \
            < lines.index("  Ticker:")

    def test_a_note_at_the_edge_of_the_file_stays_after_the_blocks(self):
        trailing = ONTOLOGY + "# end of file\n"
        ontology, _ = apply_new_type(_type(), ontology=trailing)

        assert ontology.endswith("# end of file\n") and ontology.index("  Ticker:") < ontology.index("# end of file")


def test_a_frozen_silo_map_is_read_like_a_plain_one():
    """The running configuration holds its silos as read-only mappings."""
    from types import MappingProxyType

    from core.ontology.silo_security import silo_rules

    frozen = {"data_silos": MappingProxyType({"a": MappingProxyType({"security": MappingProxyType({"field": "x"})})})}
    assert silo_rules(frozen) == {"a": {"field": "x"}}
