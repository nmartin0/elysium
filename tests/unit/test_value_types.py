"""
What a value IS, declared once (R28): the check, the tidying, the key.

`value_type: email` stands for the email constraint and the email
standardisation (DEP-4), and gives identity matching a canonical key --
so two records whose addresses differ only in case, or whose phone
numbers are written two ways, are one key while each keeps its spelling.
"""

import pytest

from core.mirror.identity import _match_key as match_key
from core.mirror.identity import rule_for as identity_rule_for
from core.ontology.value_types import canonical_key, validate_and_expand_value_types


def _schema(**field):
    return {"Person": {"id_field": "id", "fields": {"id": {"type": "data"},
                                                    "contact": {"type": "data", **field}}}}


class TestItExpandsIntoTheRulesItStandsFor:
    def test_email(self):
        schema = _schema(value_type="email")
        validate_and_expand_value_types(schema)
        field = schema["Person"]["fields"]["contact"]

        assert field["constraints"] == {"email": True}
        assert field["standardise"] == {"email": True}

    def test_phone_with_its_region(self):
        schema = _schema(value_type={"phone": "GB"})
        validate_and_expand_value_types(schema)
        field = schema["Person"]["fields"]["contact"]

        assert field["constraints"]["phone"] == "GB" and field["standardise"]["phone"] == "GB"

    def test_a_rule_written_by_hand_is_kept(self):
        schema = _schema(value_type={"phone": "GB"}, constraints={"phone": True},
                         standardise=False)
        validate_and_expand_value_types(schema)
        field = schema["Person"]["fields"]["contact"]

        assert field["constraints"]["phone"] is True and field["standardise"] is False

    @pytest.mark.parametrize("field, says", [
        ({"value_type": "postcode"}, "must be one of"),
        ({"value_type": {"phone": "XX"}}, "region code"),
        ({"value_type": "email", "data_type": "integer"}, "is text"),
    ])
    def test_a_value_type_that_cannot_apply_is_refused(self, field, says):
        with pytest.raises(ValueError, match=says):
            validate_and_expand_value_types(_schema(**field))


class TestTheCanonicalKey:
    def test_an_address_keys_without_case(self):
        field = {"value_type": "email"}
        assert canonical_key("Ada.Okafor@EXAMPLE.com", field) == \
            canonical_key("ada.okafor@example.com", field)

    def test_a_number_keys_as_e164(self):
        field = {"value_type": {"phone": "US"}}
        assert canonical_key("(201) 555-0123", field) == canonical_key("+1 201-555-0123", field) \
            == "+12015550123"

    def test_an_undeclared_field_keys_as_its_text(self):
        assert canonical_key("Ada@Example.com", {}) == "Ada@Example.com"


def test_identity_matches_two_spellings_of_one_address():
    type_def = {
        "id_field": "id", "storage": {"silo": "a", "table": "people", "id_column": "id"},
        "identity": {"match_on": ["email"]},
        "fields": {"id": {"type": "data"}, "email": {"type": "data", "value_type": "email"}},
    }
    rule = identity_rule_for(type_def)

    assert match_key({"email": "Ada@Example.COM"}, rule, type_def, None) == \
        match_key({"email": "ada@example.com"}, rule, type_def, None)


def test_the_loader_expands_it(tmp_path):
    import shutil

    from core.deployment_loader import load_deployment
    from tests.unit.conftest import CONFIG_DIR

    config_dir = tmp_path / "etc"
    shutil.copytree(CONFIG_DIR, config_dir)
    ontology = config_dir / "ontology_schema.yaml"
    text = ontology.read_text()
    assert "      email:\n        type: data\n" in text
    ontology.write_text(text.replace("      email:\n        type: data\n",
                                     "      email:\n        type: data\n        value_type: email\n", 1))

    config = load_deployment(config_dir)

    field = config.schema["Customer"]["fields"]["email"]
    assert field["constraints"]["email"] is True and field["standardise"]["email"] is True
