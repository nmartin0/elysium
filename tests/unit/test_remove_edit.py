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


def test_a_comment_above_a_removed_field_stays_because_it_may_belong_to_something_else():
    """OWNER DECISION (fix round): comment lines are NEVER deleted. A
    section header or a commented-out neighbour above the entry is not the
    entry's."""
    after, _ = removed(SMALL, field("A", "x"))
    assert "x:" not in after
    assert "# about x" in after and "# the header" in after

    after, _ = removed(SMALL, field("A", "z"))
    assert "# a note that belongs to z" in after
    assert "# a note after the last field" in after

    section = SMALL.replace("      # about x\n", "      # --- identifiers ---\n      # old_x: {type: data}\n")
    after, _ = removed(section, field("A", "x"))
    assert "# --- identifiers ---" in after and "# old_x: {type: data}" in after


def test_a_field_written_over_several_lines_goes_whole_with_its_inline_comment():
    after, _ = removed(SMALL, field("A", "y"))

    assert "why y" not in after and "foldedone" not in after and "foldedtwo" not in after
    assert meaning(after)["object_types"]["A"]["fields"].keys() == {"x", "z"}


def test_every_other_comment_in_the_file_survives():
    after, _ = removed(TEXT, field("Account", "currency"))

    gone = {line for line in TEXT.splitlines() if "currency" in line}
    kept = [line for line in TEXT.splitlines() if line.strip().startswith("#")]
    assert all(line in after.splitlines() for line in kept if line not in gone)


def test_a_link_type_goes_and_the_comment_above_it_stays():
    after, _ = removed(SMALL, {"kind": "link", "link": "M"})

    assert meaning(after)["link_types"].keys() == {"L"}
    assert "# the second" in after


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
        ({"kind": "frobnicate"}, "What is removed is one of"),
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


MERGED = """\
object_types:
  A:
    id_field: id
    fields:
      <<: &shared
        stamp: {type: data}
      own: {type: data}
      other: {type: data}
  B:
    id_field: id
    fields:
      <<: *shared
      mine: {type: data}
"""


class TestWhatComesInThroughAMerge:
    def test_a_field_that_arrives_through_a_merge_key_is_refused_not_a_500(self):
        """Reproduced: KeyError out of node.lc.key (HTTP 500)."""
        with pytest.raises(ConfigEditError, match="merge") as e:
            removed(MERGED, field("B", "stamp"))
        assert "where it is defined" in str(e.value)

    def test_an_own_key_beside_a_merge_still_goes(self):
        after, _ = removed(MERGED, field("B", "mine"))
        assert "mine" not in meaning(after)["object_types"]["B"]["fields"]

    def test_a_binding_that_arrives_through_a_merge_is_refused_too(self):
        bindings = ("object_types:\n  Account:\n    storage: {t: 1}\n    fields:\n      <<: &s\n"
                    "        currency: {column: c}\n      balance: {column: b}\n"
                    "  Tag:\n    storage: {t: 2}\n    fields:\n      <<: *s\n      label: {column: m}\n")
        with pytest.raises(ConfigEditError, match="source_bindings.yaml.*merge|merge.*source_bindings.yaml"):
            removed(TEXT, field("Account", "currency"), bindings)

    def test_the_only_key_of_the_root_is_refused_not_an_index_error(self):
        """Reproduced: IndexError when the chain of only-children reaches the root."""
        only = "A:\n  fields:\n    x:\n      column: c\n"
        with pytest.raises(ConfigEditError, match="only"):
            removed(TEXT, field("Account", "currency"), only.replace("A:", "Account:").replace("x:", "currency:"))


class TestRemovingAWholeType:
    """kind: type -- the type's block out of the ontology, its entry out of the bindings."""

    TYPE = {"kind": "type", "object_type": "B"}

    def test_the_type_goes_and_nothing_else_changes(self):
        after, bindings = removed(SMALL, self.TYPE)
        before = meaning(SMALL)

        del before["object_types"]["B"]
        assert meaning(after) == before and bindings is None

    def test_a_real_type_is_taken_out_of_the_fixture(self):
        after, _ = removed(TEXT, {"kind": "type", "object_type": "Tag"})
        before = meaning(TEXT)

        del before["object_types"]["Tag"]
        assert meaning(after) == before

    def test_its_binding_goes_with_it_and_the_others_stay(self):
        bindings = "object_types:\n  A:\n    storage: {table: a}\n  B:\n    storage: {table: b}\n"

        after, bound = removed(SMALL, self.TYPE, bindings)

        assert meaning(bound) == {"object_types": {"A": {"storage": {"table": "a"}}}}
        assert "B" not in meaning(after)["object_types"]

    def test_a_bindings_file_without_the_root_key_is_edited_too(self):
        _after, bound = removed(SMALL, self.TYPE, "A:\n  storage: {table: a}\nB:\n  storage: {table: b}\n")

        assert meaning(bound) == {"A": {"storage": {"table": "a"}}}

    def test_every_comment_line_stays_including_the_ones_inside_the_type(self):
        text = SMALL.replace("  B:\n    id_field: id\n", "  B:\n    # inside B\n    id_field: id\n"
                             "    # between B's keys\n", 1)

        after, _ = removed(text, self.TYPE)

        comments = [line for line in text.splitlines() if line.lstrip().startswith("#")]
        assert all(line in after.splitlines() for line in comments)
        assert "B:" not in after and "p: {type" not in after

    def test_a_comment_inside_a_removed_field_stays_too(self):
        text = SMALL.replace("      z:\n        type: data\n", "      z:\n        # inside z\n        type: data\n", 1)

        after, _ = removed(text, field("A", "z"))

        assert "# inside z" in after and "z:" not in after.replace("# inside z", "")

    def test_the_only_type_is_refused_not_an_index_error(self):
        with pytest.raises(ConfigEditError, match="only"):
            removed("object_types:\n  A:\n    id_field: id\n    fields:\n      x: {type: data}\n",
                    {"kind": "type", "object_type": "A"})

    def test_the_only_entry_in_a_bindings_file_is_refused(self):
        with pytest.raises(ConfigEditError, match="only"):
            removed(SMALL, self.TYPE, "B:\n  storage: {table: b}\n")

    def test_a_type_that_comes_in_through_a_merge_is_refused(self):
        text = ("object_types:\n  <<: &shared\n    S:\n      id_field: id\n      fields: {x: {type: data}}\n"
                "  A:\n    id_field: id\n    fields: {y: {type: data}}\n")

        with pytest.raises(ConfigEditError, match="merge") as e:
            removed(text, {"kind": "type", "object_type": "S"})
        assert "where it is defined" in str(e.value)

    def test_a_type_whose_block_others_alias_is_refused_rather_than_breaking_them(self):
        text = ("object_types:\n  A: &base\n    id_field: id\n    fields: {x: {type: data}}\n"
                "  B:\n    <<: *base\n")

        with pytest.raises(ConfigEditError):
            removed(text, {"kind": "type", "object_type": "A"})

    def test_a_type_written_inside_a_braced_mapping_is_refused(self):
        with pytest.raises(ConfigEditError, match="inside a"):
            removed("object_types: {A: {id_field: id, fields: {x: {type: data}}}, B: {id_field: id}}\n",
                    {"kind": "type", "object_type": "B"})

    @pytest.mark.parametrize("change,match", [
        ({"kind": "type", "object_type": "Nobody"}, "no object type"),
        ({"kind": "type"}, "no object type"),
        ({"kind": "type", "object_type": "B", "field": "p"}, "alone"),
        ({"kind": "type", "object_type": "B", "link": "L"}, "alone"),
    ])
    def test_a_name_that_is_not_there_or_extra_names_are_refused(self, change, match):
        with pytest.raises(ConfigEditError, match=match):
            removed(SMALL, change)
