"""Describing the ontology in ontology_schema.yaml (core/config_editing.py,
DEV_UI 13.7): only the lines that change, and only the keys allowed."""

import pytest
import yaml

from core.config_editing import (
    REMOVED_MARK,
    ConfigEditError,
    apply_descriptions,
    apply_labels,
    current_descriptions,
    diff,
)

SCHEMA = """\
# The header comment, which is the file's explanation.
object_types:
  Customer:
    display_name: Customer
    description: >
      A person or organisation
      the business serves.
    id_field: customer_id
    title_field: name
    security:
      field: region
    fields:
      region:
        type: data
      name:
        type: data  # the one people search by
      account:
        type: link
        target: Account
  # Accounts are the money.
  Account:
    id_field: account_id
    fields:
      balance:
        type: data
"""


def _changed(changes):
    return [line for line in diff(SCHEMA, apply_descriptions(SCHEMA, changes))
            if line[:1] in "+-" and not line.startswith(("+++", "---"))]


class TestWhatItReads:
    def test_absent_is_none_and_fields_say_their_kind(self):
        described = current_descriptions(SCHEMA)

        assert described["Account"]["display_name"] is None
        assert described["Customer"]["title_field"] == "name"
        assert described["Customer"]["fields"]["account"]["kind"] == "link"
        assert described["Customer"]["fields"]["region"]["description"] is None


class TestOnlyItsLines:
    def test_a_new_key_goes_first_in_the_type_not_under_its_last_field(self):
        edited = apply_descriptions(SCHEMA, [{"object_type": "Account", "key": "description",
                                              "value": "Money held."}])

        lines = edited.splitlines()
        assert lines[lines.index("  Account:") + 1] == "    description: Money held."

    def test_a_folded_description_is_replaced_whole(self):
        edited = apply_descriptions(SCHEMA, [{"object_type": "Customer", "key": "description",
                                              "value": "Someone we serve."}])

        assert yaml.safe_load(edited)["object_types"]["Customer"]["description"] == "Someone we serve."
        assert "the business serves." not in edited

    def test_every_comment_survives(self):
        edited = apply_descriptions(SCHEMA, [
            {"object_type": "Customer", "field": "name", "key": "display_name", "value": "Full name"},
            {"object_type": "Account", "key": "group", "value": "Money"}])

        comments = [line for line in SCHEMA.splitlines() if "#" in line]
        assert all(any(c.split("#", 1)[1] in line for line in edited.splitlines()) for c in comments)

    def test_a_field_description_goes_after_its_type(self):
        assert _changed([{"object_type": "Customer", "field": "region", "key": "description",
                          "value": "Where they are."}]) == ["+        description: Where they are."]

    def test_removing_comments_it_out_and_restoring_reuses_the_line(self):
        removed = apply_descriptions(SCHEMA, [{"object_type": "Customer", "key": "title_field",
                                               "value": None}])
        assert f"# title_field: name  {REMOVED_MARK}" in removed
        assert "title_field" not in yaml.safe_load(removed)["object_types"]["Customer"]

        restored = apply_descriptions(removed, [{"object_type": "Customer", "key": "title_field",
                                                 "value": "region"}])
        assert restored.count("title_field") == 1


class TestTextThatYamlWouldMisread:
    @pytest.mark.parametrize("value", ["yes", "12", "null", "Item #3", "*star", "a: b", "'quoted'",
                                       "Ünïcode — fine"])
    def test_it_comes_back_as_written(self, value):
        edited = apply_descriptions(SCHEMA, [{"object_type": "Account", "key": "description",
                                              "value": value}])

        assert yaml.safe_load(edited)["object_types"]["Account"]["description"] == value

    def test_a_hash_inside_a_quoted_value_is_not_taken_for_a_comment(self):
        once = apply_descriptions(SCHEMA, [{"object_type": "Account", "key": "description",
                                            "value": "Item #3"}])
        twice = apply_descriptions(once, [{"object_type": "Account", "key": "description",
                                           "value": "Item #4"}])

        # THE LINE, not only its meaning: a "#3\"" taken for a comment and
        # carried over parses as the same value, and leaves junk behind.
        assert '    description: "Item #4"' in twice.splitlines()

    def test_a_real_comment_after_a_value_is_kept(self):
        edited = apply_descriptions(SCHEMA, [{"object_type": "Customer", "field": "name",
                                              "key": "description", "value": "x"}])

        assert "type: data  # the one people search by" in edited


class TestTheAllowlist:
    @pytest.mark.parametrize("change", [
        {"object_type": "Customer", "key": "security", "value": "x"},
        {"object_type": "Customer", "key": "id_field", "value": "region"},
        {"object_type": "Customer", "field": "region", "key": "type", "value": "link"},
        {"object_type": "Customer", "field": "region", "key": "title_field", "value": "name"},
        {"object_type": "Customer", "field": "region", "key": "classification", "value": "public"},
    ])
    def test_shape_and_access_are_out_of_reach(self, change):
        with pytest.raises(ConfigEditError, match="cannot be edited here"):
            apply_descriptions(SCHEMA, [change])

    @pytest.mark.parametrize("change, reason", [
        ({"object_type": "Nope", "key": "description", "value": "x"}, "no object type"),
        ({"object_type": "Customer", "field": "nope", "key": "description", "value": "x"}, "no field"),
        ({"object_type": "Customer", "key": "description", "value": "   "}, "empty"),
        ({"object_type": "Customer", "key": "description", "value": "two\nlines"}, "one line"),
        ({"object_type": "Customer", "key": "display_name", "value": "x" * 81}, "at most 80"),
        ({"object_type": "Customer", "key": "description", "value": 3}, "is text"),
    ])
    def test_what_is_refused_and_why(self, change, reason):
        with pytest.raises(ConfigEditError, match=reason):
            apply_descriptions(SCHEMA, [change])

    def test_the_same_key_twice_is_refused(self):
        with pytest.raises(ConfigEditError, match="twice"):
            apply_descriptions(SCHEMA, [{"object_type": "Account", "key": "group", "value": "a"},
                                        {"object_type": "Account", "key": "group", "value": "b"}])

    def test_nothing_is_refused(self):
        with pytest.raises(ConfigEditError, match="Nothing"):
            apply_descriptions(SCHEMA, [])


class TestTheMeaningCheck:
    def test_a_layout_it_cannot_edit_cleanly_is_refused_not_mangled(self):
        """A field written in flow style, `{type: data}`, has no line of
        its own to add a key under. The edit must refuse, not write a
        file that means something else."""
        flow = SCHEMA.replace("      balance:\n        type: data\n", "      balance: {type: data}\n")

        with pytest.raises(ConfigEditError):
            apply_descriptions(flow, [{"object_type": "Account", "field": "balance",
                                       "key": "description", "value": "x"}])


class TestLabels:
    """apply_labels: a field's `classification:`, by the same line editor."""

    def test_one_label_is_a_word_and_several_a_list_on_one_line(self):
        one = apply_labels(SCHEMA, [{"object_type": "Account", "field": "balance", "labels": ["financial"]}])
        two = apply_labels(SCHEMA, [{"object_type": "Account", "field": "balance",
                                     "labels": ["financial", "pii"]}])

        assert "        classification: financial" in one.splitlines()
        assert "        classification: [financial, pii]" in two.splitlines()

    def test_none_removes_it_and_it_reads_back(self):
        labelled = apply_labels(SCHEMA, [{"object_type": "Account", "field": "balance", "labels": ["pii"]}])
        cleared = apply_labels(labelled, [{"object_type": "Account", "field": "balance", "labels": []}])

        assert current_descriptions(labelled)["Account"]["fields"]["balance"]["labels"] == ["pii"]
        assert current_descriptions(cleared)["Account"]["fields"]["balance"]["labels"] == []

    def test_a_repeated_label_is_one(self):
        edited = apply_labels(SCHEMA, [{"object_type": "Account", "field": "balance",
                                        "labels": ["pii", "pii"]}])

        assert yaml.safe_load(edited)["object_types"]["Account"]["fields"]["balance"]["classification"] == "pii"

    @pytest.mark.parametrize("label", ["PII", "pii x", "1pii", "pi-i", ""])
    def test_a_label_has_one_spelling(self, label):
        with pytest.raises(ConfigEditError, match="not a label"):
            apply_labels(SCHEMA, [{"object_type": "Account", "field": "balance", "labels": [label]}])

    def test_only_a_fields_classification_is_reachable(self):
        with pytest.raises(ConfigEditError, match="no field"):
            apply_labels(SCHEMA, [{"object_type": "Customer", "field": "security", "labels": ["pii"]}])
