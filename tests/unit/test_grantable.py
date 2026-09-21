"""
Every grant a role could hold, derived from the ontology.

BESIDE THE VALIDATOR ON PURPOSE, and held to it here. An editor
offering a grant the validator refuses would let somebody build a role
that cannot be saved; one omitting a grant the validator accepts would
hide a power that exists.
"""

import pytest

from core.intermediate_layer.policy_validation import (
    grantable,
    validate_roles,
)


@pytest.fixture
def config():
    from core.deployment_loader import build_generation, resolve_runtime_paths

    paths = resolve_runtime_paths()
    return build_generation(paths.config_dir, paths.data_dir, paths.log_dir).config


def _everything(config):
    return grantable(config.schema, config.action_types, config.enabled_tools)


def test_every_listed_grant_validates(config):
    """A ROLE HOLDING EVERYTHING LISTED must be a valid role -- so the
    editor can never offer a grant the validator refuses."""
    everything = {"all": {"allowed_actions": frozenset(_everything(config))}}

    validate_roles(everything, config.schema, config.action_types, config.enabled_tools)


def test_every_grant_the_shipped_policy_uses_is_listed(config):
    """THE OTHER DIRECTION: nothing a real role holds is missing from
    what the editor offers."""
    listed = set(_everything(config))

    for name, role in config.roles.items():
        missing = set(role["allowed_actions"]) - listed
        assert not missing, f"{name} holds {missing}, which grantable() omits"


def test_it_offers_manage_roles(config):
    assert "manage:roles" in _everything(config)


def test_it_offers_field_grants(config):
    assert "read:Customer.email" in _everything(config)


def test_it_follows_the_ontology(config):
    """DERIVED, NOT LISTED: a new type appears the moment it exists."""
    schema = dict(config.schema)
    # A REAL TYPE HAS AN id_field -- validated at load. A first version
    # of this test left it out and failed on KeyError, which was the
    # fixture being unrealistic, not the code being wrong.
    schema["Invoice"] = {"id_field": "invoice_id", "fields": {"total": {}}}

    grants = grantable(schema, config.action_types, config.enabled_tools)

    assert "read:Invoice.total" in grants
    assert "read:Invoice.invoice_id" in grants
