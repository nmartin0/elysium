"""Each object type as an ODCS data contract (R16).

WHAT IT IS FOR. Gold is this deployment's published interface: one
table per object type, read by the mediator today and by anything
pointed at the lake tomorrow (R17). What a consumer may RELY on --
which columns, what types, which key, how fresh, what the values are
-- is already declared, in the ontology and in the freshness targets.
It is declared for this project's own reader. The Open Data Contract
Standard (Bitol, Linux Foundation, v3) is the declaration other tools
read: datacontract-cli tests a table against one, and the catalogs
that read OpenLineage (R15) import them.

GENERATED, NEVER EDITED. A contract here is a VIEW of the ontology,
the same rule gold_view.py states: derived every time, never stored,
so it cannot drift from what the deployment enforces. A contract that
somebody edited by hand would promise things nothing checks.

WHAT MAPS TO WHAT:

    object type            one schema object, physicalName gold.<Type>
    id_field               the first property, primaryKey
    a data field           a property, logicalType from data_type
    a link stored here     a property holding the target's id
    a reverse link         NOT a property: gold computes it from the
                           other table, so this table has no such column
    required: true         required: true
    constraints            quality rules, one per constraint, as text
    classification         classification (and tags, one per label)
    freshness target       slaProperties latency: warn, valueExt fail
    status                 status (experimental -> draft)

WHAT IS LEFT OUT, deliberately. Who may read what (policy.yaml) --
a contract describes data, and its readers are not its audience's
business. Where the data came from (source_bindings.yaml) -- that is
an ingestion detail gold exists to hide, and naming source tables
would describe the customer's systems to whoever holds the contract.
Gold's own system columns (`_silo`, `_security` and the rest) -- they
are present, and a consumer must not rely on them.

VERSION IS A DIGEST, in semver's build-metadata slot: 1.0.0+<12 hex>
of the type's declaration. Two contracts with the same version promise
the same thing; any change to the declaration changes it. A hand-kept
semver would need a person to decide what is breaking, every time, and
nobody would.
"""

import hashlib
import json

from core.ontology.classifications import field_classifications
from core.ontology.derived_fields import derivation_of
from core.ontology.field_types import DECIMAL_PRECISION, DECIMAL_SCALE
from core.ontology.gold_view import GOLD_NAMESPACE
from core.ontology.link_types import is_reverse_link

API_VERSION = "v3.0.2"

#: ODCS v3's logical types are string, date, number, integer, object,
#: array and boolean. The physical type is what gold's Iceberg column is.
_LOGICAL = {
    "string": ("string", "string"),
    "integer": ("integer", "long"),
    "number": ("number", "double"),
    "decimal": ("number", "decimal"),
    "boolean": ("boolean", "boolean"),
    "date": ("date", "date"),
    "timestamp": ("date", "timestamp"),
    "timestamptz": ("date", "timestamptz"),
}

_STATUS = {"active": "active", "experimental": "draft", "deprecated": "deprecated"}


def _plain(value):
    """Frozen mappings and tuples from the live schema, as YAML can
    write them."""
    if hasattr(value, "items"):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple | frozenset | set):
        return [_plain(item) for item in value]
    return value


def contract_version(type_def) -> str:
    canonical = json.dumps(_plain(type_def), sort_keys=True, default=str)
    return f"1.0.0+{hashlib.sha256(canonical.encode()).hexdigest()[:12]}"


def _types(field_info) -> tuple[str, str]:
    declared = str(field_info.get("data_type") or "string").split("@", 1)[0]
    logical, physical = _LOGICAL.get(declared, ("string", "string"))
    if declared == "decimal":
        # ALWAYS THE ONE SCALE IN GOLD, whatever decimal_places says: that is
        # a rounding rule applied to the VALUE (standardise.py), not the
        # column's scale. The first draft wrote decimal(38, 2) and the
        # contract-matches-gold test refused it.
        physical = f"decimal({DECIMAL_PRECISION}, {DECIMAL_SCALE})"
    return logical, physical


def _quality(field_info) -> list[dict]:
    rules = []
    for key, value in sorted((field_info.get("constraints") or {}).items()):
        if key == "one_of":
            text = f"one of {sorted(map(str, value))}"
        elif key in ("no_invisible_characters", "no_misleading_text"):
            if not value:
                continue
            text = key.replace("_", " ")
        else:
            text = f"{key.replace('_', ' ')} {value}"
        rules.append({"type": "text", "description": text})
    return rules


def _property(name: str, field_info, schema) -> dict:
    prop: dict = {"name": name}
    if field_info.get("type") == "link":
        target = field_info.get("target")
        target_def = schema.get(target) or {}
        id_info = (target_def.get("fields") or {}).get(target_def.get("id_field"), {})
        prop["logicalType"], prop["physicalType"] = _types(id_info)
        prop["description"] = f"The {target} this links to, by its {target_def.get('id_field')}."
    else:
        prop["logicalType"], prop["physicalType"] = _types(field_info)
        if field_info.get("description"):
            prop["description"] = str(field_info["description"])
        derivation = derivation_of(field_info)
        if derivation is not None:
            # ODCS has no derivation field; `transformLogic` is its
            # place for how a property is produced (R37).
            prop["transformLogic"] = derivation.describe()
    if field_info.get("required"):
        prop["required"] = True
    labels = sorted(field_classifications(field_info))
    if labels:
        prop["classification"] = ", ".join(labels)
        prop["tags"] = [f"classification:{label}" for label in labels]
    quality = _quality(field_info)
    if quality:
        prop["quality"] = quality
    return prop


def data_contract(object_type: str, schema, freshness=None,
                  namespace: str = "elysium") -> dict:
    """The ODCS v3 contract for one object type's gold table.

    `freshness` is that type's FreshnessTarget, or None when the
    deployment has none for it.
    """
    type_def = schema[object_type]
    fields = type_def.get("fields") or {}
    id_field = type_def.get("id_field")

    # THE KEY AS GOLD WROTE IT. A storage's `id_type: integer` is how
    # the SOURCE is queried, not what gold holds -- gold keeps the id
    # as its field declares it, a string unless it says otherwise. The
    # first draft promised `long` and the real table said `string`.
    key = _property(id_field, fields.get(id_field) or {}, schema)
    key.update({"primaryKey": True, "primaryKeyPosition": 1, "required": True, "unique": True})

    properties = [key]
    for name, info in fields.items():
        if name == id_field:
            continue
        if info.get("type") == "link" and is_reverse_link(info):
            continue
        properties.append(_property(name, info, schema))

    schema_object: dict = {
        "name": object_type,
        "physicalName": f"{GOLD_NAMESPACE}.{object_type}",
        "physicalType": "table",
        "logicalType": "object",
        "properties": properties,
    }
    if type_def.get("description"):
        schema_object["description"] = str(type_def["description"])

    contract: dict = {
        "apiVersion": API_VERSION,
        "kind": "DataContract",
        "id": f"urn:{namespace}:contract:{object_type}",
        "name": str(type_def.get("display_name") or object_type),
        "version": contract_version(type_def),
        "status": _STATUS.get(str(type_def.get("status") or "active"), "active"),
        "description": {
            "purpose": str(type_def.get("description") or f"The {object_type} object type."),
            "usage": ("Generated from the ontology; never edit by hand. The table also "
                      "carries system columns prefixed with an underscore, which are not "
                      "part of this contract."),
        },
        "schema": [schema_object],
    }
    if freshness is not None and not freshness.exempt:
        contract["slaProperties"] = [{
            "property": "latency",
            "value": _hours(freshness.warn_after),
            "valueExt": _hours(freshness.fail_after),
            "unit": "h",
            "element": f"{GOLD_NAMESPACE}.{object_type}",
            "driver": "operational",
        }]
    return contract


def _hours(span) -> float | int:
    hours = round(span.total_seconds() / 3600, 2)
    return int(hours) if hours == int(hours) else hours


def contract_yaml(contract: dict) -> str:
    import yaml

    return yaml.safe_dump(contract, sort_keys=False, allow_unicode=True)
