"""Why something is deprecated, and what replaces it (core/ontology/deprecation.py).

The block is checked by the real loader, over a copy of the fixture
configuration, so these cover the wiring as well as the rules: a type, a
field and a link type each accept a well-formed block and each refuse the
same mistakes with a message naming the thing. A link takes the most
restrictive status of itself and its two types.
"""

import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from core.deployment_loader import load_deployment
from core.ontology.deprecation import link_status, most_restrictive, validate_deprecation

FIXTURES = Path(__file__).resolve().parents[1] / "integration" / "fixtures"
WHY = {"reason": "Replaced by a single name field."}


def _load(tmp_path: Path, change):
    copy = tmp_path / "copy"
    if copy.exists():
        shutil.rmtree(copy)
    shutil.copytree(FIXTURES, copy)
    raw = yaml.safe_load((copy / "ontology_schema.yaml").read_text())
    change(raw)
    (copy / "ontology_schema.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))
    return load_deployment(copy)


def _field(raw, type_name, field):
    return raw["object_types"][type_name]["fields"][field]


class TestTheBlockOnAField:
    def test_a_well_formed_block_loads_and_is_carried_on_the_field(self, tmp_path):
        def change(raw):
            _field(raw, "Customer", "email").update(status="deprecated", deprecation={
                **WHY, "replaced_by": "name", "remove_after": "2027-03-31"})

        config = _load(tmp_path, change)

        carried = config.schema["Customer"]["fields"]["email"]
        assert carried["status"] == "deprecated"
        assert carried["deprecation"]["replaced_by"] == "name"

    def test_deprecated_with_no_block_still_loads(self, tmp_path):
        _load(tmp_path, lambda raw: _field(raw, "Customer", "email").update(status="deprecated"))

    @pytest.mark.parametrize("status", [None, "active", "experimental"])
    def test_a_block_on_anything_not_deprecated_is_refused(self, tmp_path, status):
        def change(raw):
            _field(raw, "Customer", "email").update(deprecation=dict(WHY))
            if status:
                _field(raw, "Customer", "email")["status"] = status

        with pytest.raises(ValueError, match=r"Customer\.email: `deprecation` describes why"):
            _load(tmp_path, change)

    @pytest.mark.parametrize("block,message", [
        ({}, "needs a `reason`"),
        ({"reason": "  "}, "needs a `reason`"),
        ({"reason": "x" * 301}, "at most 300"),
        ({**WHY, "colour": "red"}, "unknown key"),
        ({**WHY, "replaced_by": "nonesuch"}, "which is not a field that exists"),
        ({**WHY, "replaced_by": "email"}, "replaced by itself"),
        ({**WHY, "remove_after": "soon"}, "must be a date like 2027-03-31"),
        ({**WHY, "remove_after": 20270331}, "must be a date like 2027-03-31"),
    ])
    def test_each_mistake_is_refused_and_names_the_field(self, tmp_path, block, message):
        with pytest.raises(ValueError, match=rf"Customer\.email: .*{message}"):
            _load(tmp_path, lambda raw: _field(raw, "Customer", "email").update(
                status="deprecated", deprecation=block))

    def test_a_replacement_that_is_itself_deprecated_is_refused(self, tmp_path):
        def change(raw):
            _field(raw, "Customer", "email").update(status="deprecated",
                                                     deprecation={**WHY, "replaced_by": "risk_score"})
            _field(raw, "Customer", "risk_score")["status"] = "deprecated"

        with pytest.raises(ValueError, match="itself deprecated"):
            _load(tmp_path, change)

    def test_a_date_written_without_quotes_is_a_date_already(self, tmp_path):
        block = {**WHY, "remove_after": date(2027, 3, 31)}

        validate_deprecation("x", "x", {"status": "deprecated", "deprecation": block}, {}, "field")


class TestTheBlockOnATypeAndALink:
    def test_a_type_may_be_deprecated_with_a_replacement(self, tmp_path):
        def change(raw):
            raw["object_types"]["Tag"].update(status="deprecated", deprecation={**WHY, "replaced_by": "Account"})

        assert _load(tmp_path, change).schema["Tag"]["deprecation"]["replaced_by"] == "Account"

    def test_a_type_names_only_a_type_that_exists(self, tmp_path):
        def change(raw):
            raw["object_types"]["Tag"].update(status="deprecated", deprecation={**WHY, "replaced_by": "Nobody"})

        with pytest.raises(ValueError, match=r"Object type 'Tag': .*not an object type that exists"):
            _load(tmp_path, change)

    def test_a_link_type_may_be_deprecated_and_both_ends_carry_it(self, tmp_path):
        def change(raw):
            raw["link_types"]["CustomerTags"].update(status="deprecated", deprecation=dict(WHY))

        schema = _load(tmp_path, change).schema

        for owner, end in (("Customer", "tags"), ("Tag", "customers")):
            carried = schema[owner]["fields"][end]
            assert carried["status"] == "deprecated" and carried["deprecation"]["reason"] == WHY["reason"]
            assert "status_inherited_from" not in carried

    def test_a_link_names_only_a_link_that_exists(self, tmp_path):
        def change(raw):
            raw["link_types"]["CustomerTags"].update(status="deprecated",
                                                      deprecation={**WHY, "replaced_by": "NoSuchLink"})

        with pytest.raises(ValueError, match=r"Link type 'CustomerTags': .*not a link type that exists"):
            _load(tmp_path, change)

    def test_a_link_with_a_status_that_is_not_one_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="Link type 'CustomerTags': status must be one of"):
            _load(tmp_path, lambda raw: raw["link_types"]["CustomerTags"].update(status="retired"))


class TestALinkTakesTheMostRestrictiveStatus:
    def test_a_deprecated_type_deprecates_its_links_and_says_which_type(self, tmp_path):
        schema = _load(tmp_path, lambda raw: raw["object_types"]["Tag"].update(status="deprecated")).schema

        for owner, end in (("Customer", "tags"), ("Tag", "customers")):
            carried = schema[owner]["fields"][end]
            assert (carried["status"], carried["status_inherited_from"]) == ("deprecated", "Tag")

    def test_an_experimental_type_makes_an_active_link_experimental(self, tmp_path):
        schema = _load(tmp_path, lambda raw: raw["object_types"]["Tag"].update(status="experimental")).schema

        assert schema["Customer"]["fields"]["tags"]["status"] == "experimental"

    def test_an_ordinary_link_carries_no_status_at_all(self, tmp_path):
        carried = _load(tmp_path, lambda raw: None).schema["Customer"]["fields"]["tags"]

        assert "status" not in carried and "status_inherited_from" not in carried

    def test_a_types_fields_do_not_follow_it(self, tmp_path):
        schema = _load(tmp_path, lambda raw: raw["object_types"]["Tag"].update(status="deprecated")).schema

        assert "status" not in schema["Tag"]["fields"]["label"]

    def test_the_links_own_status_stands_when_it_is_the_strictest(self):
        link = {"status": "deprecated", "source": {"object_type": "A"}, "target": {"object_type": "B"}}

        assert link_status(link, {}, {"status": "experimental"}) == ("deprecated", None)

    def test_the_strictest_of_three_wins_and_the_first_such_type_is_named(self):
        link = {"source": {"object_type": "A"}, "target": {"object_type": "B"}}

        assert link_status(link, {"status": "experimental"}, {"status": "deprecated"}) == ("deprecated", "B")
        assert most_restrictive(None, "experimental", "active") == "experimental"
