"""
Deciding that two rows from different sources are ONE object
(GOLD-6, the deterministic half).

HOW THIS DIFFERS FROM GOLD-5: a type spanning storages that agree on
the object's id is a JOIN, and fusion.py does it. This is the other
case -- the customer is `c1` in billing and `9f2a` in the CRM, and the
only thing saying they are the same person is a rule somebody wrote.

THE DECLARED RULE IS THE PRIMARY PATH: "deterministic, auditable, no
inference, no confidence score", and "THE GOLD LAYER MUST WORK WITH
ZERO INFERENCE" (FUSION_AND_IDENTITY.md). Probabilistic matching only
ever ADDS PROPOSALS to this.
"""

import pytest

from core.mirror.identity import IdentityRule, resolve, rule_for

TYPE = {
    "id_field": "customer_id",
    "security": {"field": "region"},
    "storage": {"silo": "billing", "table": "customers", "id_column": "cust_pk"},
    "additional_storage": {"crm": {"silo": "crm", "table": "contacts",
                                    "id_column": "contact_id"}},
    "identity": {"match_on": ["email"]},
    "fields": {
        "customer_id": {"type": "data", "column": "cust_pk"},
        "region": {"type": "data"},
        "email": {"type": "data"},
        "name": {"type": "data"},
    },
}


def _rows(billing, crm):
    return {None: billing, "crm": crm}


class TestTheRule:
    def test_a_type_declaring_none_resolves_nothing(self):
        without = {key: value for key, value in TYPE.items() if key != "identity"}

        assert rule_for(without) is None
        assert resolve(without, _rows([], [])).entities == {}

    def test_a_match_on_naming_an_unknown_field_is_refused(self):
        """It would otherwise match every row against every other on a
        missing value."""
        broken = {**TYPE, "identity": {"match_on": ["nickname"]}}

        with pytest.raises(ValueError, match="does not have"):
            rule_for(broken)

    @pytest.mark.parametrize("declared", [
        {"match_on": []},
        {"match_on": "email"},
        {"match_on": ["email"], "fuzzy": True},
        "email",
    ])
    def test_anything_malformed_is_refused(self, declared):
        with pytest.raises(ValueError):
            rule_for({**TYPE, "identity": declared})


class TestMatching:
    def test_two_sources_agreeing_on_the_key_become_one_entity(self):
        resolution = resolve(TYPE, _rows(
            [{"cust_pk": "c1", "email": "ada@x.com", "region": "us-west"}],
            [{"contact_id": "9f2a", "email": "ada@x.com", "region": "us-west"}],
        ))

        assert resolution.merged_count == 1
        assert sorted(str(key) for key in resolution.entities["c1"]) == ["None", "crm"]

    def test_rows_that_match_nothing_stay_themselves(self):
        """What makes this safe to turn on: a rule matching nothing
        leaves a deployment exactly as it was."""
        resolution = resolve(TYPE, _rows(
            [{"cust_pk": "c1", "email": "ada@x.com", "region": "us-west"}],
            [{"contact_id": "7c1b", "email": "zoe@x.com", "region": "eu"}],
        ))

        assert sorted(resolution.entities) == ["c1", "crm:7c1b"]
        assert resolution.merged_count == 0

    def test_a_MISSING_key_matches_nothing(self):
        """Treating absence as equality is how identity resolution
        merges a whole population into one object."""
        resolution = resolve(TYPE, _rows(
            [{"cust_pk": "c1", "email": None, "region": "us-west"},
             {"cust_pk": "c2", "email": "", "region": "us-west"}],
            [{"contact_id": "9f2a", "email": None, "region": "us-west"}],
        ))

        assert sorted(resolution.entities) == ["c1", "c2", "crm:9f2a"]

    def test_a_multi_field_key_needs_every_part(self):
        type_def = {**TYPE, "identity": {"match_on": ["email", "name"]}}

        resolution = resolve(type_def, _rows(
            [{"cust_pk": "c1", "email": "ada@x.com", "name": "Ada", "region": "us-west"}],
            [{"contact_id": "9f2a", "email": "ada@x.com", "name": None, "region": "us-west"}],
        ))

        assert sorted(resolution.entities) == ["c1", "crm:9f2a"]

    def test_matching_is_EXACT_on_the_standardised_value(self):
        """Silver already trimmed and normalised these; anything looser
        here would be inference, and inference goes through proposals."""
        resolution = resolve(TYPE, _rows(
            [{"cust_pk": "c1", "email": "ada@x.com", "region": "us-west"}],
            [{"contact_id": "9f2a", "email": "Ada@X.com", "region": "us-west"}],
        ))

        assert resolution.merged_count == 0


class TestTheEntityId:
    def test_it_keeps_the_PRIMARY_sources_id(self):
        rule = IdentityRule(match_on=("email",), primary=None)

        resolution = resolve(TYPE, _rows(
            [{"cust_pk": "c1", "email": "ada@x.com", "region": "us-west"}],
            [{"contact_id": "9f2a", "email": "ada@x.com", "region": "us-west"}],
        ), rule)

        assert "c1" in resolution.entities and "crm:9f2a" not in resolution.entities

    def test_a_row_only_the_other_source_has_is_namespaced(self):
        resolution = resolve(TYPE, _rows([], [
            {"contact_id": "7c1b", "email": "zoe@x.com", "region": "eu"}]))

        assert sorted(resolution.entities) == ["crm:7c1b"]

    def test_the_id_is_DERIVED_so_it_survives_a_rebuild(self):
        """A random id would make the changelog report the whole
        population as deleted and recreated every night (GOLD-4)."""
        rows = _rows(
            [{"cust_pk": "c1", "email": "ada@x.com", "region": "us-west"}],
            [{"contact_id": "9f2a", "email": "ada@x.com", "region": "us-west"}],
        )

        first = sorted(resolve(TYPE, rows).entities)
        second = sorted(resolve(TYPE, rows).entities)

        assert first == second == ["c1"]


class TestDecisionD2:
    """A security disagreement REFUSES the merge and reports it."""

    def _disagreeing(self):
        return resolve(TYPE, _rows(
            [{"cust_pk": "c1", "email": "ada@x.com", "region": "us-west"}],
            [{"contact_id": "9f2a", "email": "ada@x.com", "region": "eu"}],
        ))

    def test_the_rows_are_left_unmerged(self):
        """Merging would silently decide who can see the result."""
        resolution = self._disagreeing()

        assert sorted(resolution.entities) == ["c1", "crm:9f2a"]
        assert resolution.merged_count == 0

    def test_and_the_disagreement_is_reported_with_both_values(self):
        resolution = self._disagreeing()

        entity_id, values = resolution.refused[0]
        assert entity_id == "c1"
        assert sorted(str(value) for value in values.values()) == ["eu", "us-west"]

    def test_agreeing_sources_merge_normally(self):
        resolution = resolve(TYPE, _rows(
            [{"cust_pk": "c1", "email": "ada@x.com", "region": "us-west"}],
            [{"contact_id": "9f2a", "email": "ada@x.com", "region": "us-west"}],
        ))

        assert resolution.refused == [] and resolution.merged_count == 1

    def test_a_source_that_does_not_hold_the_security_field_is_not_a_conflict(self):
        """Absent is not disagreement -- and refusing on absence would
        make a CRM without regions unmergeable forever."""
        resolution = resolve(TYPE, _rows(
            [{"cust_pk": "c1", "email": "ada@x.com", "region": "us-west"}],
            [{"contact_id": "9f2a", "email": "ada@x.com"}],
        ))

        assert resolution.refused == [] and resolution.merged_count == 1
