"""
Point 16: link types as first-class ontology entities.

FOUNDRY'S MODEL, adopted directly: a link type is "the schema
definition of a relationship between two object types" -- an entity in
its own right, not an attribute of a field. It names both object
types, their cardinality, and how the relationship is backed:
a FOREIGN KEY for one-to-one and one-to-many ("a property of one
object type refers to the primary key property of the other"), or a
JOIN TABLE for many-to-many ("a table containing pairs of primary
keys").

WHAT THIS REPLACED. Links were previously declared as field
attributes, once per DIRECTION, so Customer.transactions and
Transaction.customer_id were unrelated declarations of ONE
relationship. Four limitations followed, and all four are closed here:
no many-to-many at all, directions that could drift apart, no link
metadata, and nowhere for a relationship's own identity.
"""

import pytest

from core.ontology.link_types import expand_link_types, validate_link_types

OBJECT_TYPES = {
    "Customer": {
        "storage": {"silo": "primary", "table": "customers", "id_column": "customer_id"},
        "id_field": "customer_id",
        "fields": {"name": {"type": "data"}},
    },
    "Order": {
        "storage": {"silo": "primary", "table": "orders", "id_column": "order_id"},
        "id_field": "order_id",
        "fields": {"total": {"type": "data"}},
    },
    "Tag": {
        "storage": {"silo": "primary", "table": "tags", "id_column": "tag_id"},
        "id_field": "tag_id",
        "fields": {"label": {"type": "data"}},
    },
}

ONE_TO_MANY = {
    "CustomerOrders": {
        "display_name": "Orders",
        "source": {"object_type": "Customer", "api_name": "orders"},
        "target": {"object_type": "Order", "api_name": "customer_id"},
        "cardinality": "one_to_many",
        "foreign_key_column": "customer_id",
    }
}

MANY_TO_MANY = {
    "CustomerTags": {
        "source": {"object_type": "Customer", "api_name": "tags"},
        "target": {"object_type": "Tag", "api_name": "customers"},
        "cardinality": "many_to_many",
        "join_table": {
            "table": "customer_tags",
            "source_column": "customer_id",
            "target_column": "tag_id",
        },
    }
}


def test_one_declaration_generates_both_directions(expected=None):
    # THE limitation this design closes. Two independent field
    # declarations could drift apart; one link type cannot.
    expanded = expand_link_types(ONE_TO_MANY, OBJECT_TYPES)

    forward = expanded["Customer"]["fields"]["orders"]
    backward = expanded["Order"]["fields"]["customer_id"]

    assert forward["target"] == "Order"
    assert forward["cardinality"] == "many"
    assert backward["target"] == "Customer"
    assert backward["cardinality"] == "one"
    assert forward["link_type"] == backward["link_type"] == "CustomerOrders"


def test_a_foreign_key_link_traverses_the_targets_own_table(expected=None):
    expanded = expand_link_types(ONE_TO_MANY, OBJECT_TYPES)

    forward = expanded["Customer"]["fields"]["orders"]

    assert forward["via_table"] == "orders"
    assert forward["via_column"] == "customer_id"
    # A foreign-key link declares no via_target_column: the target's
    # own id column is what comes back.
    assert "via_target_column" not in forward


def test_a_many_to_many_link_traverses_a_join_table_in_both_directions():
    # The capability the old form could not express AT ALL: neither
    # object can hold the other's key without duplicating rows.
    expanded = expand_link_types(MANY_TO_MANY, OBJECT_TYPES)

    forward = expanded["Customer"]["fields"]["tags"]
    backward = expanded["Tag"]["fields"]["customers"]

    assert forward["via_table"] == backward["via_table"] == "customer_tags"
    # Both traverse the SAME table, differing only in which column is
    # matched and which is returned.
    assert forward["via_column"] == "customer_id"
    assert forward["via_target_column"] == "tag_id"
    assert backward["via_column"] == "tag_id"
    assert backward["via_target_column"] == "customer_id"
    assert forward["cardinality"] == backward["cardinality"] == "many"


def test_link_metadata_reaches_both_generated_fields():
    # Point 10 gave object types and fields display names; links got
    # none, so a UI rendered "owner_customer_id".
    expanded = expand_link_types(ONE_TO_MANY, OBJECT_TYPES)

    assert expanded["Customer"]["fields"]["orders"]["display_name"] == "Orders"
    assert expanded["Order"]["fields"]["customer_id"]["display_name"] == "Orders"


def test_an_undeclared_display_name_is_omitted_not_nulled():
    # A null would override humanize()'s fallback with nothing, leaving
    # a UI with a blank label.
    expanded = expand_link_types(MANY_TO_MANY, OBJECT_TYPES)

    assert "display_name" not in expanded["Customer"]["fields"]["tags"]


def test_expansion_leaves_the_original_object_types_untouched():
    # Mutating the caller's dict would make load order matter.
    before = dict(OBJECT_TYPES["Customer"]["fields"])

    expand_link_types(ONE_TO_MANY, OBJECT_TYPES)

    assert OBJECT_TYPES["Customer"]["fields"] == before


# --- Validation ---------------------------------------------------------


def test_a_valid_link_type_validates():
    validate_link_types(ONE_TO_MANY, OBJECT_TYPES)
    validate_link_types(MANY_TO_MANY, OBJECT_TYPES)


def test_an_unknown_object_type_is_rejected():
    bad = {"L": {**ONE_TO_MANY["CustomerOrders"],
                 "target": {"object_type": "NoSuchType", "api_name": "x"}}}

    with pytest.raises(ValueError, match="not a declared object type"):
        validate_link_types(bad, OBJECT_TYPES)


def test_an_unknown_cardinality_is_rejected():
    bad = {"L": {**ONE_TO_MANY["CustomerOrders"], "cardinality": "some_to_some"}}

    with pytest.raises(ValueError, match="cardinality must be one of"):
        validate_link_types(bad, OBJECT_TYPES)


def test_many_to_many_without_a_join_table_is_rejected():
    bad = {"L": {**MANY_TO_MANY["CustomerTags"]}}
    del bad["L"]["join_table"]

    with pytest.raises(ValueError, match="requires a join_table"):
        validate_link_types(bad, OBJECT_TYPES)


def test_a_foreign_key_link_without_a_column_is_rejected():
    bad = {"L": {**ONE_TO_MANY["CustomerOrders"]}}
    del bad["L"]["foreign_key_column"]

    with pytest.raises(ValueError, match="requires a foreign_key_column"):
        validate_link_types(bad, OBJECT_TYPES)


def test_declaring_both_backings_is_rejected():
    # A link is backed one way or the other; declaring both means the
    # author is unsure, and guessing which they meant would be worse
    # than saying so.
    bad = {"L": {**ONE_TO_MANY["CustomerOrders"],
                 "join_table": {"table": "x", "source_column": "a", "target_column": "b"}}}

    with pytest.raises(ValueError, match="must not declare a join_table"):
        validate_link_types(bad, OBJECT_TYPES)


def test_an_api_name_colliding_with_a_real_field_is_rejected():
    # The generated link field would silently shadow the data field.
    bad = {"L": {**ONE_TO_MANY["CustomerOrders"],
                 "target": {"object_type": "Order", "api_name": "total"}}}

    with pytest.raises(ValueError, match="collides with a field"):
        validate_link_types(bad, OBJECT_TYPES)


def test_a_missing_side_is_rejected():
    bad = {"L": {"cardinality": "one_to_many", "foreign_key_column": "x",
                 "source": {"object_type": "Customer", "api_name": "orders"}}}

    with pytest.raises(ValueError, match="missing 'target'"):
        validate_link_types(bad, OBJECT_TYPES)


# --- The deployment linter -----------------------------------------------


def _lint(tmp_path, mutate=None):
    """Copies the real fixture deployment, optionally breaks it, and
    lints it -- exercising the actual CLI path an operator uses."""
    import shutil

    from scripts.lint_deployment import lint_deployment

    config_dir = tmp_path / "config"
    shutil.copytree("tests/integration/fixtures", config_dir)
    if mutate:
        schema_path = config_dir / "ontology_schema.yaml"
        schema_path.write_text(mutate(schema_path.read_text()))

    import io
    from contextlib import redirect_stdout

    captured = io.StringIO()
    with redirect_stdout(captured):
        valid = lint_deployment(config_dir)
    return valid, captured.getvalue()


def test_the_linter_accepts_the_real_fixture_deployment(tmp_path):
    valid, _output = _lint(tmp_path)

    assert valid


def test_the_linter_rejects_a_link_to_an_unknown_object_type(tmp_path):
    valid, output = _lint(
        tmp_path,
        lambda text: text.replace(
            "target: {object_type: Tag, api_name: customers}",
            "target: {object_type: NoSuchType, api_name: customers}",
        ),
    )

    assert not valid
    assert "NoSuchType" in output


def test_the_linter_rejects_many_to_many_without_a_join_table(tmp_path):
    import re

    valid, output = _lint(
        tmp_path,
        lambda text: re.sub(
            r"    join_table:\n      table: customer_tags\n"
            r"      source_column: customer_id\n      target_column: tag_id\n",
            "",
            text,
        ),
    )

    assert not valid
    assert "requires a join_table" in output


def test_a_broken_link_type_is_reported_in_the_right_file(tmp_path):
    # THE bug this closes. Link fields are GENERATED from link_types,
    # so checking roles against the UNEXPANDED types reported spurious
    # "unknown field 'accounts'" errors against policy.yaml when the
    # real fault was a broken link type in ontology_schema.yaml --
    # pointing an author at the wrong file entirely.
    valid, output = _lint(
        tmp_path,
        lambda text: text.replace(
            "target: {object_type: Tag, api_name: customers}",
            "target: {object_type: NoSuchType, api_name: customers}",
        ),
    )

    assert not valid
    assert "ontology_schema.yaml" in output
    assert "Link type" in output
    assert "policy.yaml" not in output, (
        "the linter blamed policy.yaml for a fault in ontology_schema.yaml"
    )


def test_grants_on_GENERATED_link_fields_are_not_reported_as_unknown(tmp_path):
    # read:Customer.accounts is valid even though "accounts" appears
    # nowhere in the raw YAML -- it is generated from a link type.
    #
    # Reaching the code that matters needs care, and a first version of
    # this test did NOT: the linter only falls back to per-item error
    # collection when load_deployment() has already failed, so a valid
    # deployment never exercises it. This breaks an ACTION TYPE, so the
    # load fails for an unrelated reason and the fallback runs with
    # link grants present -- exactly the situation where an unexpanded
    # check would report spurious "unknown field" errors.
    valid, output = _lint(
        tmp_path,
        lambda text: text.replace("operation: update", "operation: nonsense", 1),
    )

    assert not valid
    # The REAL fault is reported...
    assert "nonsense" in output
    # ...and the generated link fields are not blamed alongside it.
    assert "unknown field 'accounts'" not in output
    assert "unknown field 'tags'" not in output


# --- Object-type errors get positions too --------------------------------


def test_an_object_type_error_reports_its_file_and_line(tmp_path):
    # These were surfaced only through load_deployment()'s generic
    # ValueError, so a field-level fault named the object type and
    # field in its message but pointed at NO line in NO file -- while a
    # link-type fault a few lines away reported "(ontology_schema.yaml,
    # line 188)". The position machinery already walked arbitrary key
    # paths; object types simply never reached it.
    valid, output = _lint(
        tmp_path,
        lambda text: text.replace("        data_type: number", "        data_type: nonsense", 1),
    )

    assert not valid
    assert "nonsense" in output
    assert "ontology_schema.yaml, line" in output


def test_every_bad_object_type_is_reported_not_just_the_first(tmp_path):
    # validate_object_types() is eager-fail, so linting the whole dict
    # at once would surface one fault and hide the rest. An author
    # fixing them one round-trip at a time is the thing per-entry
    # collection exists to prevent.
    valid, output = _lint(
        tmp_path,
        lambda text: text.replace(
            "        data_type: number", "        data_type: nonsense", 1
        ).replace('    display_name: Tag', '    display_name: ""', 1),
    )

    assert not valid
    assert "nonsense" in output
    assert "non-empty string" in output


def test_narrowing_to_one_type_still_resolves_cross_references(tmp_path):
    # THE bug a first version of this had. Validating a single-entry
    # dict made every legitimate security.via_field reference look like
    # an unknown object type -- three false errors on a deployment
    # whose only real fault was one typo'd data_type. `only=` narrows
    # WHICH type is checked without narrowing what the checks can SEE.
    valid, output = _lint(
        tmp_path,
        lambda text: text.replace("        data_type: number", "        data_type: nonsense", 1),
    )

    assert not valid
    assert "targets unknown object type" not in output, (
        "narrowing broke cross-reference resolution"
    )


def test_a_valid_deployment_is_unaffected_by_the_narrowing(tmp_path):
    valid, output = _lint(tmp_path)

    assert valid, output


def test_a_join_carrying_its_own_properties_is_expressible():
    """The object-backed link case, built rather than asserted.

    Foundry's third link backing lets a join carry properties -- their
    example is a FlightManifest linking Aircraft and Flight while
    holding Pilot and First Mate. Elysium has foreign-key and
    join-table backings only, and the roadmap claimed this was already
    expressible as two ordinary links through a real object type.

    It was a claim with nothing behind it. This is the claim, executed:
    if it ever stops holding, the roadmap entry resting on it is wrong.
    """
    object_types = {
        "Aircraft": {
            "storage": {"silo": "p", "table": "aircraft", "id_column": "tail_number"},
            "id_field": "tail_number",
            "security": {"field": "region"},
            "fields": {"model": {"type": "data"}, "region": {"type": "data"}},
        },
        "Flight": {
            "storage": {"silo": "p", "table": "flights", "id_column": "flight_id"},
            "id_field": "flight_id",
            "security": {"field": "region"},
            "fields": {"departs": {"type": "data"}, "region": {"type": "data"}},
        },
        # The join, as a first-class object carrying its own properties.
        "FlightManifest": {
            "storage": {"silo": "p", "table": "manifests", "id_column": "manifest_id"},
            "id_field": "manifest_id",
            "security": {"field": "region"},
            "fields": {
                "pilot": {"type": "data"},
                "first_mate": {"type": "data"},
                "region": {"type": "data"},
                "tail_number": {"type": "data"},
                "flight_id": {"type": "data"},
            },
        },
    }
    link_types = {
        "AircraftManifests": {
            "source": {"object_type": "Aircraft", "api_name": "manifests"},
            "target": {"object_type": "FlightManifest", "api_name": "aircraft"},
            "cardinality": "one_to_many",
            "foreign_key_column": "tail_number",
        },
        "FlightManifests": {
            "source": {"object_type": "Flight", "api_name": "manifests"},
            "target": {"object_type": "FlightManifest", "api_name": "flight"},
            "cardinality": "one_to_many",
            "foreign_key_column": "flight_id",
        },
    }

    validate_link_types(link_types, object_types)
    expanded = expand_link_types(link_types, object_types)

    # Reachable from both sides...
    assert expanded["Aircraft"]["fields"]["manifests"]["target"] == "FlightManifest"
    assert expanded["Flight"]["fields"]["manifests"]["target"] == "FlightManifest"
    # ...and the link's own properties are ordinary fields on it.
    assert "pilot" in expanded["FlightManifest"]["fields"]
    assert "first_mate" in expanded["FlightManifest"]["fields"]
