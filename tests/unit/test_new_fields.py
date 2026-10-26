"""Adding a data field to the ontology as a list of operations
(core/config_editing.apply_new_fields) -- the lines, the two files, and
what it refuses. The routes are in tests/integration/test_new_fields_from_the_ui.py.
"""

import pytest
import yaml

from core.config_editing import ConfigEditError
from core.config_editing import apply_new_fields as _apply_new_fields
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
  Tag:
    id_field: tag_id
    fields:
      label:
        type: data
"""

BINDINGS = """\
# Where it comes from.
object_types:
  Customer:
    storage:
      silo: primary_sql
      table: customers
      id_column: customer_id
  Tag:
    storage:
      silo: primary_sql
      table: tags
      id_column: tag_id
    fields:
      label:
        column: tag_label
"""


def apply_new_fields(ontology, bindings, additions):
    return _apply_new_fields(ontology, bindings, additions, FIELD_DATA_TYPES)


def _add(**given):
    return {"object_type": "Customer", "name": "nickname", **given}


class TestTheLinesItWrites:
    def test_a_field_goes_after_the_last_one_and_before_what_follows_it(self):
        ontology, _ = apply_new_fields(ONTOLOGY, None, [_add()])

        assert ontology.splitlines()[5:10] == [
            "      name:", "        type: data", "      nickname:", "        type: data",
            "      # Kept for last: a note that belongs after the final field."]

    def test_every_other_line_is_left_as_it_was(self):
        ontology, _ = apply_new_fields(ONTOLOGY, None, [_add(description="Another name")])

        kept = [line for line in ontology.splitlines(keepends=True)
                if line not in ("      nickname:\n", "        type: data\n", "        description: Another name\n")]
        assert "".join(kept) == ONTOLOGY.replace("        type: data\n", "")

    def test_the_data_type_description_and_labels_are_written_in_that_order(self):
        ontology, _ = apply_new_fields(ONTOLOGY, None, [
            _add(data_type="integer", display_name="Nick", description="Another name", labels=["pii", "contact"])])

        assert yaml.safe_load(ontology)["object_types"]["Customer"]["fields"]["nickname"] == {
            "type": "data", "data_type": "integer", "display_name": "Nick",
            "description": "Another name", "classification": ["pii", "contact"]}
        lines = ontology.splitlines()
        start = lines.index("      nickname:")
        assert [line.split(":")[0].strip() for line in lines[start + 1:start + 6]] == [
            "type", "data_type", "display_name", "description", "classification"]

    def test_text_that_yaml_would_read_as_something_else_is_quoted(self):
        ontology, _ = apply_new_fields(ONTOLOGY, None, [_add(description="yes", display_name="Item #3")])

        field = yaml.safe_load(ontology)["object_types"]["Customer"]["fields"]["nickname"]
        assert field["description"] == "yes" and field["display_name"] == "Item #3"

    def test_two_fields_to_one_type_land_in_the_order_given(self):
        ontology, _ = apply_new_fields(ONTOLOGY, None, [_add(name="b"), _add(name="a")])

        assert list(yaml.safe_load(ontology)["object_types"]["Customer"]["fields"]) == ["name", "b", "a"]

    def test_a_field_for_each_of_two_types(self):
        ontology, _ = apply_new_fields(ONTOLOGY, None, [_add(), {"object_type": "Tag", "name": "colour"}])

        loaded = yaml.safe_load(ontology)["object_types"]
        assert "nickname" in loaded["Customer"]["fields"] and "colour" in loaded["Tag"]["fields"]


class TestTheSourceColumn:
    def test_it_goes_to_the_bindings_when_there_is_a_bindings_file(self):
        ontology, bindings = apply_new_fields(ONTOLOGY, BINDINGS, [_add(column="nick_name")])

        assert "column" not in yaml.safe_load(ontology)["object_types"]["Customer"]["fields"]["nickname"]
        assert yaml.safe_load(bindings)["object_types"]["Customer"]["fields"] == {"nickname": {"column": "nick_name"}}

    def test_a_type_with_no_bound_fields_gets_its_fields_block(self):
        _, bindings = apply_new_fields(ONTOLOGY, BINDINGS, [_add(column="nick_name")])

        assert bindings.splitlines()[2:10] == [
            "  Customer:", "    storage:", "      silo: primary_sql", "      table: customers",
            "      id_column: customer_id", "    fields:", "      nickname:", "        column: nick_name"]

    def test_a_type_that_has_bound_fields_gains_one_beside_them(self):
        _, bindings = apply_new_fields(ONTOLOGY, BINDINGS, [{"object_type": "Tag", "name": "colour", "column": "hue"}])

        assert yaml.safe_load(bindings)["object_types"]["Tag"]["fields"] == {
            "label": {"column": "tag_label"}, "colour": {"column": "hue"}}

    def test_it_goes_in_the_field_when_the_deployment_has_one_file(self):
        ontology, bindings = apply_new_fields(ONTOLOGY, None, [_add(column="nick_name")])

        assert bindings is None
        assert yaml.safe_load(ontology)["object_types"]["Customer"]["fields"]["nickname"]["column"] == "nick_name"

    def test_a_column_named_like_the_field_is_not_written(self):
        ontology, bindings = apply_new_fields(ONTOLOGY, BINDINGS, [_add(column="nickname")])

        assert bindings == BINDINGS
        assert "column" not in yaml.safe_load(ontology)["object_types"]["Customer"]["fields"]["nickname"]

    def test_the_bindings_are_untouched_when_no_field_needs_them(self):
        assert apply_new_fields(ONTOLOGY, BINDINGS, [_add()])[1] == BINDINGS

    def test_a_type_the_bindings_do_not_bind_is_refused(self):
        with pytest.raises(ConfigEditError, match="does not bind Customer"):
            apply_new_fields(ONTOLOGY, "object_types:\n  Tag:\n    storage: {}\n", [_add(column="x")])

    def test_a_column_name_with_a_space_is_kept_whole(self):
        _, bindings = apply_new_fields(ONTOLOGY, BINDINGS, [_add(column="Nick Name")])

        assert yaml.safe_load(bindings)["object_types"]["Customer"]["fields"]["nickname"]["column"] == "Nick Name"


class TestWhatItRefuses:
    @pytest.mark.parametrize("addition, said", [
        ({"object_type": "Nobody", "name": "x"}, "no object type"),
        (_add(name="name"), "already a field"),
        (_add(name="customer_id"), "already a field"),
        (_add(name="Nick"), "not a field name"),
        (_add(name="2nd"), "not a field name"),
        (_add(name="a" * 64), "not a field name"),
        (_add(data_type="blob"), "data type"),
        (_add(labels=["PII"]), "not a label"),
        (_add(description=""), "is empty"),
        (_add(description="two\nlines"), "one line"),
        (_add(column="  "), "source column"),
        (_add(access="all"), "cannot be set"),
    ])
    def test_it_says_why(self, addition, said):
        with pytest.raises(ConfigEditError, match=said):
            apply_new_fields(ONTOLOGY, None, [addition])

    def test_the_same_field_twice(self):
        with pytest.raises(ConfigEditError, match="already a field"):
            apply_new_fields(ONTOLOGY, None, [_add(), _add()])

    def test_nothing_to_add(self):
        with pytest.raises(ConfigEditError, match="Nothing to add"):
            apply_new_fields(ONTOLOGY, None, [])

    def test_more_than_a_migration(self):
        with pytest.raises(ConfigEditError, match="At most 20"):
            apply_new_fields(ONTOLOGY, None, [_add(name=f"f{i}") for i in range(21)])

    def test_a_type_with_no_fields_block(self):
        with pytest.raises(ConfigEditError, match="no `fields:` block"):
            apply_new_fields("object_types:\n  Bare:\n    id_field: id\n", None,
                             [{"object_type": "Bare", "name": "x"}])

    def test_a_refusal_leaves_the_texts_alone(self):
        with pytest.raises(ConfigEditError):
            apply_new_fields(ONTOLOGY, BINDINGS, [_add(), _add(name="name")])
        assert ONTOLOGY.count("nickname") == 0
