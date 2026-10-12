"""Declared per-field rules work on the schema a deployment actually loads.

FOUND BY THE ONTOLOGY PREVIEW (R20), the first thing to push a declared
`standardise` rule through the real loader: the live schema is
DEEP-FROZEN, its mappings are MappingProxyType, and two readers
checked `isinstance(declared, dict)` -- so a deployment declaring
`standardise: {null_if: [...]}` or `duplicate_keys: {keep_last_by: c}`
had every sync refused with "must be a mapping ... got mappingproxy".
Every existing test built its schema from plain dicts, which is why
none saw it. This one freezes it first.
"""

from core.immutable import deep_freeze
from core.mirror.sync_targets import resolve_sync_targets

SCHEMA = {"object_types": {"T": {
    "id_field": "id",
    "security": {"field": "region"},
    "storage": {"silo": "s", "table": "t", "id_column": "id",
                "duplicate_keys": {"keep_last_by": "updated_at"}},
    "fields": {
        "region": {"type": "data"},
        "code": {"type": "data", "standardise": {"null_if": ["N/A"]}},
    },
}}}


def test_a_declared_standardisation_resolves_on_a_frozen_schema():
    (target,) = resolve_sync_targets(deep_freeze(SCHEMA))

    assert tuple(target.standardisation["code"]["null_if"]) == ("N/A",)


def test_a_declared_duplicate_policy_resolves_on_a_frozen_schema():
    (target,) = resolve_sync_targets(deep_freeze(SCHEMA))

    assert target.duplicate_policy.column == "updated_at"
