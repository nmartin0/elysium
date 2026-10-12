"""Classification labels decide field access (formerly BLOCKING 6).

As the owner decided it on 2026-10-12: a label both GRANTS and
RESTRICTS, a label grant never opens a type, and the whole is opt-in.

    readable(field) = read:<Type>  AND  read:label:<L> for every label L

A field nobody labelled is untouched. A role that held a per-field
grant on a labelled field and lacks the label is demoted to discover --
it may know the field exists, not what it holds.

THE END-TO-END TESTS READ THROUGH THE REAL MEDIATOR of the shipped
deployment, where Customer.email is `pii` and Transaction.amount is
`financial`, and customer_service holds read:Customer.email by name.
"""

import pytest

from core.intermediate_layer.auth import resolve_user_record
from core.intermediate_layer.policy_validation import grantable, validate_roles
from core.ontology.classifications import compile_label_access, label_access_changes

SCHEMA = {
    "Customer": {"id_field": "id", "fields": {
        "name": {"type": "data"},
        "email": {"type": "data", "classification": "pii"},
        "salary": {"type": "data", "classification": ["pii", "financial"]},
    }},
    "Account": {"id_field": "id", "fields": {
        "iban": {"type": "data", "classification": "pii"},
    }},
}


def _grants(*allowed):
    compiled = compile_label_access({"r": {"allowed_actions": frozenset(allowed)}}, SCHEMA)
    return compiled["r"]["allowed_actions"]


class TestTheRule:
    def test_a_label_grant_reads_every_field_carrying_it(self):
        assert "read:Customer.email" in _grants("read:Customer", "read:label:pii")

    def test_a_labelled_field_needs_its_label_whatever_was_granted_by_name(self):
        """RESTRICT: the per-field grant alone no longer reads it."""
        grants = _grants("read:Customer", "read:Customer.email")

        assert "read:Customer.email" not in grants
        assert "discover:Customer.email" in grants

    def test_every_label_is_needed(self):
        """Conjunctive, as markings are: [pii, financial] needs both."""
        assert "read:Customer.salary" not in _grants("read:Customer", "read:label:pii")
        assert "read:Customer.salary" in _grants("read:Customer", "read:label:pii",
                                                 "read:label:financial")

    def test_a_label_never_opens_a_type(self):
        """read:label:pii reaches no field of Account without read:Account."""
        grants = _grants("read:Customer", "read:label:pii")

        assert not any(grant.startswith(("read:Account", "discover:Account")) for grant in grants)

    def test_an_unlabelled_field_is_untouched(self):
        """THE CONTROL: name carries no label, and its grant stands."""
        assert "read:Customer.name" in _grants("read:Customer", "read:Customer.name")
        assert "read:Customer.name" not in _grants("read:Customer", "read:label:pii")

    def test_the_diff_says_who_gains_and_loses_what(self):
        changes = label_access_changes(
            {"named": {"allowed_actions": frozenset({"read:Customer", "read:Customer.email"})},
             "labelled": {"allowed_actions": frozenset({"read:Customer", "read:label:pii"})}},
            SCHEMA)

        assert changes["named"] == ([], ["read:Customer.email"])
        assert changes["labelled"] == (["read:Customer.email"], [])


class TestTheGrantItself:
    def test_a_label_in_use_is_a_valid_grant_and_is_offered(self):
        validate_roles({"r": {"allowed_actions": ["read:label:pii"]}}, SCHEMA, {}, [])

        assert "read:label:pii" in grantable(SCHEMA, {}, [])

    def test_a_label_nothing_carries_is_refused(self):
        """'PII' against fields labelled 'pii' would permit nothing."""
        with pytest.raises(ValueError, match="no field carries"):
            validate_roles({"r": {"allowed_actions": ["read:label:PII"]}}, SCHEMA, {}, [])


def _mediator(paths, enforce: bool, extra_grant: "str | None" = None):
    from core.deployment_loader import build_generation

    if enforce:
        config = paths.config_dir / "config.yaml"
        config.write_text(config.read_text() + "\naccess:\n  label_enforcement: true\n")
    if extra_grant:
        policy = paths.config_dir / "policy.yaml"
        policy.write_text(policy.read_text().replace(
            "      - read:Customer.email\n", f"      - read:Customer.email\n      - {extra_grant}\n", 1))
    generation = build_generation(paths.config_dir, paths.data_dir, paths.log_dir)
    user = resolve_user_record(generation.config.users, "user_alice",
                               generation.config.security_attribute)
    return generation.mediator, user


class TestThroughTheRealMediator:
    def test_off_by_default_nothing_changes(self, synced_deployment):
        """Applying the code changes nobody's access."""
        mediator, user = _mediator(synced_deployment, enforce=False)

        assert mediator.get_object(user, "Customer", "cust_001", ["email"])["email"]

    def test_on_a_labelled_field_is_withheld_without_its_label(self, synced_deployment):
        mediator, user = _mediator(synced_deployment, enforce=True)

        assert mediator.get_object(user, "Customer", "cust_001", ["email"])["email"] is None
        # ...and the role still knows the field exists.
        assert "email" in mediator.visible_schema(user)["Customer"]["fields"]

    def test_on_the_label_grant_restores_it(self, synced_deployment):
        mediator, user = _mediator(synced_deployment, enforce=True, extra_grant="read:label:pii")

        assert mediator.get_object(user, "Customer", "cust_001", ["email"])["email"]

    def test_on_the_declared_roles_are_left_as_written(self, synced_deployment):
        """The role editor shows and saves config.roles; a compiled grant
        saved back would become a declared one nobody wrote."""
        from core.deployment_loader import build_generation

        _mediator(synced_deployment, enforce=True)
        generation = build_generation(synced_deployment.config_dir, synced_deployment.data_dir,
                                      synced_deployment.log_dir)

        assert "read:Customer.email" in generation.config.roles["customer_service"]["allowed_actions"]
