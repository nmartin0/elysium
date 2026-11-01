"""apply_removal: taking a stored field or a link type out of the ontology
file by its lines (the removal design, 28 October).

Each test reads the result with a plain YAML parser, as the loader does, so
what is asserted is what the deployment would mean, not what the text looks
like. The route's rules (deprecated first, nothing names it) are not here:
this module judges only that the edit is exact (tests/integration/
test_removal_from_the_ui.py has the rest).
"""

from pathlib import Path

import pytest
import yaml

from core.config_editing import ConfigEditError, apply_removal

FILE = Path(__file__).resolve().parents[1] / "integration" / "fixtures" / "ontology_schema.yaml"
TEXT = FILE.read_text()

SMALL = """\
# the header
object_types:
  A:
    id_field: id
    fields:
      # about x
      x: {type: data}
      y:
        type: data   # why y
        description: >
          foldedone
          foldedtwo
      # a note that belongs to z
      z:
        type: data
      # a note after the last field
  B:
    id_field: id
    fields: {p: {type: data}, q: {type: data}}
  C:
    id_field: id
    fields:
      only:
        type: data
link_types:
  L:
    display_name: L
  # the second
  M:
    display_name: M
"""


def field(object_type="Customer", name="email"):
    return {"kind": "field", "object_type": object_type, "field": name}


def meaning(text):
    return yaml.safe_load(text)


def removed(text, change, bindings=None):
    return apply_removal(text, bindings, change)


def test_a_field_goes_and_nothing_else_changes():
    after, _ = removed(TEXT, field("Account", "currency"))
    before = meaning(TEXT)

    del before["object_types"]["Account"]["fields"]["currency"]
    assert meaning(after) == before


def test_its_own_lines_go_with_a_comment_directly_above_it_and_not_the_one_after():
    after, _ = removed(SMALL, field("A", "x"))
    assert "# about x" not in after and "x:" not in after
    assert "# the header" in after

    after, _ = removed(SMALL, field("A", "z"))
    assert "# a note that belongs to z" not in after
    assert "# a note after the last field" in after


def test_a_field_written_over_several_lines_goes_whole_with_its_inline_comment():
    after, _ = removed(SMALL, field("A", "y"))

    assert "why y" not in after and "foldedone" not in after and "foldedtwo" not in after
    assert meaning(after)["object_types"]["A"]["fields"].keys() == {"x", "z"}


def test_every_other_comment_in_the_file_survives():
    after, _ = removed(TEXT, field("Account", "currency"))

    gone = {line for line in TEXT.splitlines() if "currency" in line}
    kept = [line for line in TEXT.splitlines() if line.strip().startswith("#")]
    assert all(line in after.splitlines() for line in kept if line not in gone)


def test_a_link_type_goes_with_the_comment_above_it():
    after, _ = removed(SMALL, {"kind": "link", "link": "M"})

    assert meaning(after)["link_types"].keys() == {"L"}
    assert "# the second" not in after


def test_the_last_link_type_takes_link_types_with_it():
    once, _ = removed(SMALL, {"kind": "link", "link": "M"})
    twice, _ = removed(once, {"kind": "link", "link": "L"})

    assert "link_types" not in meaning(twice)
    assert meaning(twice)["object_types"] == meaning(SMALL)["object_types"]


def test_a_real_link_type_is_taken_out_of_the_fixture():
    after, _ = removed(TEXT, {"kind": "link", "link": "CustomerTags"})
    before = meaning(TEXT)

    del before["link_types"]["CustomerTags"]
    assert meaning(after) == before


def test_an_entry_inside_a_braced_mapping_is_refused_with_a_message():
    with pytest.raises(ConfigEditError, match=r"inside a \{\.\.\.\} on one line"):
        removed(SMALL, field("B", "p"))


def test_the_only_field_of_a_type_is_refused():
    with pytest.raises(ConfigEditError, match="only entry under `fields:`"):
        removed(SMALL, field("C", "only"))


class TestWhatIsRefused:
    @pytest.mark.parametrize("change, message", [
        (field("Customer", "tags"), "removing the link type"),
        (field("Customer", "transactions"), "removing the link type"),
        (field("Customer", "nope"), "has no field"),
        (field("Nobody", "email"), "no object type"),
        ({"kind": "link", "link": "Nobody"}, "no link type"),
        ({"kind": "type", "object_type": "Tag"}, "A type is not removed here"),
        ({"kind": "link", "link": "CustomerTags", "object_type": "Tag"}, "named by `link` alone"),
        ({**field("Customer", "email"), "link": "CustomerTags"}, "named by `object_type` and `field`"),
        ({**field("Customer", "email"), "reason": "x"}, "cannot be set here"),
    ])
    def test_it_says_why(self, change, message):
        with pytest.raises(ConfigEditError, match=message):
            removed(TEXT, change)

    def test_nothing_to_remove(self):
        with pytest.raises(ConfigEditError):
            apply_removal(TEXT, None, [])  # type: ignore[arg-type]

    def test_the_identifier_is_never_removed_even_when_the_file_lists_it_as_a_field(self):
        text = TEXT.replace("    fields:\n      region:\n        type: data\n      name:",
                            "    fields:\n      customer_id:\n        type: data\n      region:\n        type: data\n"
                            "      name:", 1)
        assert "customer_id:\n        type: data" in text

        with pytest.raises(ConfigEditError, match="identifier"):
            removed(text, field("Customer", "customer_id"))

    def test_a_field_written_as_a_link_is_sent_to_its_link_type(self):
        text = TEXT.replace("      email:\n        type: data\n", "      email:\n        type: link\n", 1)

        with pytest.raises(ConfigEditError, match="Remove the link type"):
            removed(text, field("Customer", "email"))


class TestBindings:
    BOUND = TEXT
    BINDINGS = """\
object_types:
  Account:
    storage: {silo: primary_sql, table: accounts, id_column: account_id}
    fields:
      currency:
        column: ccy
      balance:
        column: bal
  Tag:
    storage: {silo: primary_sql, table: tags, id_column: tag_id}
    fields:
      label:
        column: name
"""

    def test_the_binding_goes_with_its_field(self):
        text, bindings = removed(self.BOUND, field("Account", "currency"), self.BINDINGS)

        assert "currency" not in meaning(text)["object_types"]["Account"]["fields"]
        assert meaning(bindings)["object_types"]["Account"]["fields"] == {"balance": {"column": "bal"}}

    def test_the_last_binding_takes_the_empty_fields_block_with_it(self):
        _, bindings = removed(self.BOUND, field("Tag", "label"), self.BINDINGS)

        assert "fields" not in meaning(bindings)["object_types"]["Tag"]
        assert meaning(bindings)["object_types"]["Tag"]["storage"]["table"] == "tags"

    def test_a_field_with_no_binding_leaves_the_bindings_text_untouched(self):
        _, bindings = removed(self.BOUND, field("Account", "balance"), self.BINDINGS.replace(
            "      balance:\n        column: bal\n", ""))

        assert bindings == self.BINDINGS.replace("      balance:\n        column: bal\n", "")

    def test_without_a_bindings_file_there_is_none_back(self):
        assert removed(self.BOUND, field("Account", "currency"))[1] is None

    def test_a_link_type_leaves_the_bindings_untouched(self):
        assert removed(self.BOUND, {"kind": "link", "link": "CustomerTags"}, self.BINDINGS)[1] == self.BINDINGS

    def test_a_binding_in_the_flat_form_is_found_too(self):
        flat = self.BINDINGS.replace("object_types:\n", "", 1).replace("\n  ", "\n")
        flat = flat.lstrip()

        _, bindings = removed(self.BOUND, field("Account", "currency"), flat)

        assert "currency" not in meaning(bindings)["Account"]["fields"]

    def test_a_binding_inside_a_braced_mapping_is_refused(self):
        braced = self.BINDINGS.replace("      currency:\n        column: ccy\n      balance:\n        column: bal\n",
                                       "      currency: {column: ccy}\n      balance: {column: bal}\n")
        both = "{currency: {column: ccy}, balance: {column: bal}}\n"
        braced = braced.replace("    fields:\n", "    fields: ", 1).replace(
            "      currency: {column: ccy}\n      balance: {column: bal}\n", both, 1)

        with pytest.raises(ConfigEditError, match="inside a"):
            removed(self.BOUND, field("Account", "currency"), braced)
