"""Adding a link type (core/config_editing.apply_new_link) -- the lines it
writes, and what it refuses. The routes are in
tests/integration/test_new_link_from_the_ui.py.
"""

import pytest
import yaml

from core.config_editing import ConfigEditError, apply_new_link
from core.ontology.link_types import expand_link_types, validate_link_types

ONTOLOGY = """\
# The ontology.
object_types:
  Customer:
    id_field: customer_id
    storage: {silo: s, table: customers, id_column: customer_id}
    fields:
      name:
        type: data
  Transaction:
    id_field: transaction_id
    storage: {silo: s, table: transactions, id_column: transaction_id}
    fields:
      amount:
        type: data
      customer_ref:
        type: data
  Tag:
    id_field: tag_id
    storage: {silo: s, table: tags, id_column: tag_id}
    fields:
      label:
        type: data

link_types:
  # The first one, with a note after it.
  CustomerTransactions:
    source: {object_type: Customer, api_name: transactions}
    target: {object_type: Transaction, api_name: customer}
    cardinality: one_to_many
    foreign_key_column: customer_ref
  # A note that ends the file.
"""


def _link(**given):
    return {"name": "CustomerTags",
            "source": {"object_type": "Customer", "api_name": "tags"},
            "target": {"object_type": "Tag", "api_name": "customers"},
            "cardinality": "many_to_many",
            "join_table": {"table": "customer_tags", "source_column": "customer_id", "target_column": "tag_id"},
            **given}


def _fk(**given):
    return {"name": "CustomerNotes",
            "source": {"object_type": "Customer", "api_name": "notes"},
            "target": {"object_type": "Tag", "api_name": "customer"},
            "cardinality": "one_to_many", "foreign_key_column": "customer_ref", **given}


def _loads(ontology):
    """The result is a link set the loader would accept and expand."""
    parsed = yaml.safe_load(ontology)
    validate_link_types(parsed["link_types"], parsed["object_types"])
    return expand_link_types(parsed["link_types"], parsed["object_types"])


class TestTheLinesItWrites:
    def test_a_link_goes_after_the_last_one_and_its_trailing_note(self):
        ontology = apply_new_link(ONTOLOGY, _link())
        lines = ontology.splitlines()

        assert lines.index("  # A note that ends the file.") < lines.index("  CustomerTags:")
        assert yaml.safe_load(ontology)["link_types"]["CustomerTags"]["join_table"] == {
            "table": "customer_tags", "source_column": "customer_id", "target_column": "tag_id"}

    def test_everything_already_in_the_file_is_as_it_was(self):
        ontology = apply_new_link(ONTOLOGY, _link())

        assert ontology.startswith(ONTOLOGY)

    def test_both_directions_come_from_the_one_declaration(self):
        expanded = _loads(apply_new_link(ONTOLOGY, _link()))

        assert expanded["Customer"]["fields"]["tags"]["target"] == "Tag"
        assert expanded["Tag"]["fields"]["customers"]["target"] == "Customer"

    def test_a_foreign_key_link_names_its_column(self):
        ontology = apply_new_link(ONTOLOGY, _fk(display_name="Notes", description="yes"))

        declared = yaml.safe_load(ontology)["link_types"]["CustomerNotes"]
        assert declared["foreign_key_column"] == "customer_ref" and "join_table" not in declared
        assert declared["display_name"] == "Notes" and declared["description"] == "yes"
        assert _loads(ontology)["Customer"]["fields"]["notes"]["via_column"] == "customer_ref"

    def test_a_file_with_no_links_yet_gets_the_block(self):
        bare = ONTOLOGY[:ONTOLOGY.index("\nlink_types:")]
        ontology = apply_new_link(bare, _link())

        assert ontology.startswith(bare)
        assert list(yaml.safe_load(ontology)["link_types"]) == ["CustomerTags"]
        _loads(ontology)

    def test_a_file_with_no_final_newline_still_gets_one_block(self):
        bare = ONTOLOGY[:ONTOLOGY.index("\nlink_types:")].rstrip("\n")
        assert list(yaml.safe_load(apply_new_link(bare, _link()))["link_types"]) == ["CustomerTags"]


class TestWhatItRefuses:
    @pytest.mark.parametrize("given, match", [
        ({"name": "customer_tags"}, "not a link name"),
        ({"name": "CustomerTransactions"}, "already a link type"),
        ({"source": {"object_type": "Nobody", "api_name": "x"}}, "no object type 'Nobody'"),
        ({"target": {"object_type": "Tag", "api_name": "Bad Name"}}, "not a name for the link"),
        ({"source": {"object_type": "Customer", "api_name": "name"}}, "already has a field or link called 'name'"),
        ({"source": {"object_type": "Customer", "api_name": "transactions"}},
         "already has a field or link called 'transactions'"),
        ({"target": {"object_type": "Transaction", "api_name": "customer"}},
         "already has a field or link called 'customer'"),
        ({"source": {"object_type": "Customer"}}, "is {object_type, api_name}"),
        ({"cardinality": "many"}, "relationship is one of"),
        ({"join_table": None}, "needs a join table"),
        ({"join_table": {"table": "t"}}, "needs a join table"),
        ({"join_table": {"table": "t", "source_column": "", "target_column": "b"}}, "needs a table and both columns"),
        ({"foreign_key_column": "x"}, "not a column"),
        ({"surprise": 1}, "cannot be set"),
    ])
    def test_it_refuses_a_join_link(self, given, match):
        with pytest.raises(ConfigEditError, match=match):
            apply_new_link(ONTOLOGY, _link(**given))

    @pytest.mark.parametrize("given, match", [
        ({"foreign_key_column": None}, "needs the column"),
        ({"foreign_key_column": 7}, "foreign key column is a name"),
        ({"foreign_key_column": ""}, "needs the column"),
        ({"join_table": {"table": "t", "source_column": "a", "target_column": "b"}}, "not a join table"),
    ])
    def test_it_refuses_a_foreign_key_link(self, given, match):
        with pytest.raises(ConfigEditError, match=match):
            apply_new_link(ONTOLOGY, _fk(**given))

    def test_both_sides_may_not_take_the_same_name_on_one_type(self):
        both = {"name": "Friends", "cardinality": "many_to_many",
                "source": {"object_type": "Customer", "api_name": "friends"},
                "target": {"object_type": "Customer", "api_name": "friends"}}
        with pytest.raises(ConfigEditError, match="already has a field or link called 'friends'"):
            apply_new_link(ONTOLOGY, _link(**both))

    def test_a_link_from_a_type_to_itself_is_fine_under_two_names(self):
        loop = {"name": "Referrals", "cardinality": "one_to_many",
                "source": {"object_type": "Customer", "api_name": "referrals"},
                "target": {"object_type": "Customer", "api_name": "referrer"},
                "foreign_key_column": "referrer_id"}
        loop.pop("join_table", None)
        ontology = apply_new_link(ONTOLOGY, {k: v for k, v in _fk().items() if k != "name"} | loop)
        assert "Referrals" in yaml.safe_load(ontology)["link_types"]

    def test_a_file_with_no_object_types_is_refused(self):
        with pytest.raises(ConfigEditError, match="declares no object_types"):
            apply_new_link("link_types: {}\n", _link())
