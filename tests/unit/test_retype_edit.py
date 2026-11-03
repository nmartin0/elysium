"""apply_retype: changing ONE data field's `data_type` line in the ontology
file (slice R1 of the retype design, BLOCKING.md "RETYPE, CHECKED AND
SLICED"). Like test_remove_edit.py: each result is read with a plain YAML
parser, as the loader reads it, so what is asserted is what the deployment
would mean. What the change does to the lake is core/ontology/retype.py's.
"""

from pathlib import Path

import pytest
import yaml

from elysium.core.config_editing import ConfigEditError, apply_retype
from elysium.core.ontology.field_types import FIELD_DATA_TYPES

TYPES = tuple(FIELD_DATA_TYPES)
FIXTURE = (Path(__file__).resolve().parents[1] / "integration" / "fixtures" / "ontology_schema.yaml").read_text()

SMALL = """\
# the header
object_types:
  A:
    id_field: id
    fields:
      # about amount
      amount:
        type: data
        data_type: number   # why number
        description: >
          foldedone
          foldedtwo
      # about plain, which declares no data_type
      plain:
        type: data
        display_name: Plain   # shown
      other:
        type: data
        data_type: string
      owner:
        type: link
        link_type: L
      # a note after the last field
link_types:
  L:
    display_name: L
"""


def change(field="amount", data_type="decimal", object_type="A"):
    return {"object_type": object_type, "field": field, "data_type": data_type}


def meaning(text):
    return yaml.safe_load(text)


def retyped(text, **given):
    return apply_retype(text, change(**given), TYPES)


def test_the_value_on_the_line_changes_and_nothing_else_does():
    after = retyped(SMALL)

    expected = meaning(SMALL)
    expected["object_types"]["A"]["fields"]["amount"]["data_type"] = "decimal"
    assert meaning(after) == expected


def test_every_comment_stays_and_so_does_the_one_after_the_value():
    after = retyped(SMALL)

    # (the editor writes two spaces before an inline comment, as everywhere else)
    assert [line for line in after.splitlines() if "#" in line] == [
        "# the header", "      # about amount", "        data_type: decimal  # why number",
        "      # about plain, which declares no data_type", "        display_name: Plain   # shown",
        "      # a note after the last field"]


def test_only_the_one_line_differs():
    after = retyped(SMALL)

    changed = [(a, b) for a, b in zip(SMALL.splitlines(), after.splitlines(), strict=True) if a != b]
    assert changed == [("        data_type: number   # why number", "        data_type: decimal  # why number")]


def test_a_field_with_no_data_type_gets_the_line_under_its_type():
    after = retyped(SMALL, field="plain", data_type="integer")

    assert meaning(after)["object_types"]["A"]["fields"]["plain"] == {
        "type": "data", "data_type": "integer", "display_name": "Plain"}
    lines = after.splitlines()
    assert lines[lines.index("      plain:") + 1:][:3] == [
        "        type: data", "        data_type: integer", "        display_name: Plain   # shown"]


def test_a_field_with_no_data_type_counts_as_string_so_string_is_refused_for_it():
    with pytest.raises(ConfigEditError, match="already string"):
        retyped(SMALL, field="plain", data_type="string")


def test_going_back_to_string_writes_string():
    after = retyped(SMALL, data_type="string")

    assert meaning(after)["object_types"]["A"]["fields"]["amount"]["data_type"] == "string"


def test_a_real_field_of_the_fixture_is_retyped():
    after = apply_retype(FIXTURE, {"object_type": "Account", "field": "balance", "data_type": "decimal"}, TYPES)

    assert meaning(after)["object_types"]["Account"]["fields"]["balance"]["data_type"] == "decimal"
    assert len(after.splitlines()) == len(FIXTURE.splitlines())


class TestLineEnds:
    def test_a_file_with_crlf_keeps_crlf_on_every_line_including_the_one_added(self):
        crlf = SMALL.replace("\n", "\r\n")

        for field, data_type in (("amount", "decimal"), ("plain", "integer")):
            after = retyped(crlf, field=field, data_type=data_type)
            assert "\n" not in after.replace("\r\n", "")
            assert meaning(after)["object_types"]["A"]["fields"][field]["data_type"] == data_type

    def test_a_crlf_file_differs_from_its_original_in_one_line_only(self):
        crlf = SMALL.replace("\n", "\r\n")

        after = retyped(crlf)

        assert [(a, b) for a, b in zip(crlf.split("\r\n"), after.split("\r\n"), strict=True) if a != b] == [
            ("        data_type: number   # why number", "        data_type: decimal  # why number")]

    def test_a_file_that_mixes_the_two_is_refused_not_half_converted(self):
        mixed = SMALL.replace("\n", "\r\n", 3)

        with pytest.raises(ConfigEditError, match="mixes CRLF and LF"):
            retyped(mixed)

    def test_a_file_without_a_final_newline_is_edited(self):
        after = retyped(SMALL.rstrip("\n"))

        assert meaning(after)["object_types"]["A"]["fields"]["amount"]["data_type"] == "decimal"


class TestWhatIsRefused:
    @pytest.mark.parametrize("given,match", [
        ({"object_type": "Nope"}, "no object type"),
        ({"field": "nope"}, "no field 'nope'"),
        ({"field": "owner", "data_type": "string"}, "not a data field"),
        ({"field": "id"}, "is the type's identifier"),
        ({"data_type": "varchar"}, "data type is one of"),
        ({"data_type": "number"}, "already number"),
        ({"data_type": None}, "data type is one of"),
        ({"object_type": None}, "no object type"),
        ({"field": None}, "no field"),
    ])
    def test_it_says_why(self, given, match):
        with pytest.raises(ConfigEditError, match=match):
            retyped(SMALL, **given)

    def test_the_types_identifier_is_never_retyped_even_when_the_file_lists_it_as_a_field(self):
        text = SMALL.replace("    fields:\n", "    fields:\n      id:\n        type: data\n", 1)

        with pytest.raises(ConfigEditError, match="identifier"):
            retyped(text, field="id", data_type="integer")

    def test_the_identifier_not_listed_as_a_field_is_not_said_to_be_a_links_value(self):
        with pytest.raises(ConfigEditError) as e:
            retyped(SMALL, field="id", data_type="integer")

        assert "identifier" in str(e.value) and "link" not in str(e.value)

    @pytest.mark.parametrize("rule", ["derived: {formula: amount}", "enrich: {from: x}", "predict: {model: m}"])
    def test_a_computed_field_is_refused_whatever_its_rule_is(self, rule):
        text = SMALL.replace("    fields:\n", f"    fields:\n      computed:\n        type: data\n        {rule}\n", 1)

        with pytest.raises(ConfigEditError, match="what its rule produces"):
            retyped(text, field="computed", data_type="integer")

    def test_the_field_that_decides_who_may_see_a_row_is_refused(self):
        text = SMALL.replace("    id_field: id\n", "    id_field: id\n    security:\n      field: other\n", 1)

        with pytest.raises(ConfigEditError, match="who may see each row"):
            retyped(text, field="other", data_type="integer")

    def test_a_type_off_the_callers_list_is_refused_though_the_mirror_knows_it(self):
        with pytest.raises(ConfigEditError, match="data type is one of date, number"):
            apply_retype(SMALL, change(data_type="decimal"), ("date", "number"))

    def test_extra_keys_and_nothing_to_change(self):
        with pytest.raises(ConfigEditError, match="cannot be set here"):
            apply_retype(SMALL, {**change(), "column": "x"}, TYPES)
        with pytest.raises(ConfigEditError, match="Nothing to change"):
            apply_retype(SMALL, [], TYPES)  # type: ignore[arg-type]

    def test_a_file_with_no_object_types(self):
        with pytest.raises(ConfigEditError, match="declares no object_types"):
            retyped("link_types: {}\n")


MERGED = """\
shared: &shared
  stamp: {type: data, data_type: number}
object_types:
  A:
    id_field: id
    fields:
      <<: *shared
      mine:
        type: data
        data_type: number
"""


class TestWhatCannotBeEditedByLine:
    def test_a_field_that_arrives_through_a_merge_is_refused_with_where_to_go(self):
        with pytest.raises(ConfigEditError, match="merge") as e:
            retyped(MERGED, field="stamp", data_type="decimal")
        assert "where it is defined" in str(e.value)

    def test_an_own_field_beside_a_merge_is_retyped(self):
        after = retyped(MERGED, field="mine", data_type="decimal")

        assert meaning(after)["object_types"]["A"]["fields"]["mine"]["data_type"] == "decimal"

    def test_a_data_type_taken_from_a_merge_inside_the_field_is_refused(self):
        text = ("base: &base\n  data_type: number\nobject_types:\n  A:\n    id_field: id\n    fields:\n"
                "      x:\n        <<: *base\n        type: data\n")

        with pytest.raises(ConfigEditError, match="merge"):
            retyped(text, field="x", data_type="decimal")

    def test_a_field_written_on_one_line_is_refused_both_ways(self):
        text = ("object_types:\n  A:\n    id_field: id\n    fields:\n"
                "      flow: {type: data, data_type: number}\n      bare: {type: data}\n")

        for field, data_type in (("flow", "decimal"), ("bare", "integer")):
            with pytest.raises(ConfigEditError, match=r"\{\.\.\.\} on one line"):
                retyped(text, field=field, data_type=data_type)

    def test_a_whole_fields_block_in_flow_style_is_refused(self):
        text = "object_types:\n  A:\n    id_field: id\n    fields: {x: {type: data}}\n"

        with pytest.raises(ConfigEditError, match=r"\{\.\.\.\} on one line"):
            retyped(text, field="x", data_type="decimal")

    def test_a_field_with_an_anchor_is_refused_rather_than_changing_what_aliases_it(self):
        text = ("object_types:\n  A:\n    id_field: id\n    fields:\n      x: &x\n        type: data\n"
                "        data_type: number\n      y: *x\n")

        with pytest.raises(ConfigEditError, match="anchor"):
            retyped(text, field="x", data_type="decimal")
