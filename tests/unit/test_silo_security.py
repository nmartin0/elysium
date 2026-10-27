"""A silo's row rule and `security: inherit` (27 October, owner-agreed).

core/ontology/silo_security.py has the reasoning. Built on the shared
Author/Book fixture: Author's rule is moved out of the type and into its
silo, then inherited.
"""

import copy

import pytest

from core.intermediate_layer.auth import resolve_user_record
from core.ontology.object_type_validation import validate_object_types
from core.ontology.silo_security import INHERITED_FROM, resolve_inherited_security, silo_rules
from tests.conftest import TEST_SCHEMA, author_book_mediator

USERS = {
    "alice": {"org_id": "org-a", "role": "reader"},
    "bob": {"org_id": "org-b", "role": "reader"},
}
ROLES = {"reader": {"allowed_actions": [
    "read:Author", "read:Author.author_id", "read:Author.name", "read:Author.org_id",
    "read:Book", "read:Book.book_id", "read:Book.title", "read:Book.year",
    "read:Book.author_id",
]}}


def _silos(security="__none__"):
    silo = {"adapter": "sqlite", "connection": {"path": "x"}}
    if security != "__none__":
        silo["security"] = security
    return {"data_silos": {"test_silo": silo}}


def _schema(silo_security=None):
    silo_security = {"field": "org_id"} if silo_security is None else silo_security
    schema = copy.deepcopy(TEST_SCHEMA)
    schema["Author"]["security"] = "inherit"
    raw = {"object_types": schema}
    resolve_inherited_security(raw, _silos(silo_security))
    return raw["object_types"]


class TestTheSiloRule:
    def test_a_field_rule_or_the_word_unrestricted(self):
        assert silo_rules(_silos("unrestricted")) == {"test_silo": {"unrestricted": True}}
        assert silo_rules(_silos({"field": "org_id"})) == {"test_silo": {"field": "org_id"}}

    def test_a_silo_with_no_rule_has_none(self):
        assert silo_rules(_silos()) == {}

    @pytest.mark.parametrize("bad", ["public", {"via_field": "x"}, {"field": ""},
                                     {"field": "a", "unrestricted": True}, 3])
    def test_anything_else_is_refused(self, bad):
        with pytest.raises(ValueError, match="silo 'test_silo'"):
            silo_rules(_silos(bad))


class TestInheriting:
    def test_the_type_takes_the_silos_rule_and_says_from_where(self):
        schema = _schema()
        assert schema["Author"]["security"] == {"field": "org_id"}
        assert schema["Author"][INHERITED_FROM] == "test_silo"
        validate_object_types(schema)

    def test_an_unrestricted_silo_gives_an_unrestricted_type(self):
        schema = _schema("unrestricted")
        assert schema["Author"]["security"] == {"unrestricted": True}

    def test_a_silo_with_no_rule_refuses_inherit(self):
        with pytest.raises(ValueError, match="'Author'.*declares no security"):
            _schema(silo_security="__none__")

    def test_a_type_with_no_source_cannot_inherit(self):
        schema = copy.deepcopy(TEST_SCHEMA)
        schema["Author"]["security"] = "inherit"
        del schema["Author"]["storage"]
        with pytest.raises(ValueError, match="'Author'.*needs a source"):
            resolve_inherited_security({"object_types": schema}, _silos({"field": "org_id"}))

    def test_a_type_that_writes_its_own_rule_is_untouched(self):
        raw = {"object_types": copy.deepcopy(TEST_SCHEMA)}
        resolve_inherited_security(raw, _silos("unrestricted"))
        assert raw["object_types"]["Author"]["security"] == {"field": "org_id"}
        assert INHERITED_FROM not in raw["object_types"]["Author"]

    def test_an_inherited_field_must_exist_on_the_type(self):
        schema = _schema({"field": "no_such_field"})
        with pytest.raises(ValueError, match="unknown field 'no_such_field'"):
            validate_object_types(schema)

    def test_the_resolved_unrestricted_type_obeys_the_chain_rule(self):
        # Book reaches Author through via_field: an inherited unrestricted
        # Author must be refused exactly as a written one is.
        with pytest.raises(ValueError, match="chain ends at 'Author'"):
            validate_object_types(_schema("unrestricted"))


class TestReading:
    def test_an_inherited_field_rule_filters_rows_like_a_written_one(self, test_db_path):
        mediator = author_book_mediator(test_db_path, _schema(), ROLES)
        a = mediator.search_object(resolve_user_record(USERS, "alice", "org_id"), "Author")
        b = mediator.search_object(resolve_user_record(USERS, "bob", "org_id"), "Author")
        written = author_book_mediator(test_db_path, copy.deepcopy(TEST_SCHEMA), ROLES)
        for name, got in (("alice", a), ("bob", b)):
            user = resolve_user_record(USERS, name, "org_id")
            assert got and sorted(got) == sorted(written.search_object(user, "Author")), name
        assert set(a).isdisjoint(b)


class TestTheLoaderDoesIt:
    """The whole path: files on disk -> load_deployment."""

    FIXTURES = "tests/integration/fixtures"

    def _deployment(self, tmp_path, silo_rule):
        import shutil

        import yaml

        from core.deployment_loader import load_deployment
        shutil.copytree(self.FIXTURES, tmp_path / "d", dirs_exist_ok=True)
        d = tmp_path / "d"
        silos = yaml.safe_load((d / "data_silos.yaml").read_text())
        if silo_rule is not None:
            silos["data_silos"]["primary_sql"]["security"] = silo_rule
        (d / "data_silos.yaml").write_text(yaml.safe_dump(silos))
        text = (d / "ontology_schema.yaml").read_text()
        schema = yaml.safe_load(text)
        schema["object_types"]["Customer"]["security"] = "inherit"
        (d / "ontology_schema.yaml").write_text(yaml.safe_dump(schema))
        return load_deployment, d

    def test_a_deployment_loads_with_the_inherited_rule(self, tmp_path):
        original = None
        import yaml
        base = yaml.safe_load(open(f"{self.FIXTURES}/ontology_schema.yaml"))
        original = base["object_types"]["Customer"]["security"]
        load, d = self._deployment(tmp_path, original)
        assert load(d).schema["Customer"]["security"] == original

    def test_a_deployment_whose_silo_says_nothing_does_not_load(self, tmp_path):
        load, d = self._deployment(tmp_path, None)
        with pytest.raises(ValueError, match="'Customer'.*declares no security"):
            load(d)
