"""Approved predictions, brought to the gold build (R48).

run_sync hands build_gold a copy of each type with every predicted
field's APPROVED proposals attached, and each row's security
compartment made resolvable; gold_arrow.with_predicted trains, measures
and fills. Kept here, in the mirror, so the proposal store stays a store
-- as core/mirror/enrichment.py does for recipes.

RETRAINED ONLY WHEN GOLD IS REBUILT (the owner, 17 October). The
attached approvals and compartments ride on the type, so they are part
of the digest that decides whether gold is rebuilt at all (run_sync's
_gold_inputs): an unchanged table is not retrained, and an approval, a
changed record or a moved compartment is.

EACH ROW'S COMPARTMENT BY THE READ PATH'S RULE (mediator.
_get_security_value): for a type with a security field of its own, the
carried `_security` column, or the declared field where that is empty;
for a type secured through a link
(`via_field`), the compartment of the record it links to -- read from
that type's gold, published earlier in the same run, since targets are
built before the types that link to them.
"""

import logging
from collections.abc import Callable
from typing import Any

from core.carried_columns import SECURITY_COLUMN
from core.ontology.gold_view import GOLD_NAMESPACE
from core.prediction_proposals import PredictionProposalStore

logger = logging.getLogger(__name__)

#: Where run_sync puts a predicted field's approvals, on the copy of the
#: type it hands build_gold: [{compartment, skill, proposal_id}].
#: Underscored, so no ontology can declare it (ALLOWED_BESIDE).
APPROVED_PREDICTIONS = "_approved_predictions"
#: On the type: how a row's compartment is found -- {"field": the
#: declared security field, or None for a type with no security} or
#: {"via": link field, "by_id": {linked id: compartment}}.
COMPARTMENTS = "_prediction_compartments"


def with_approved_predictions(catalog_of: Callable[[], Any], schema: dict, object_type: str,
                              type_def, store: PredictionProposalStore) -> dict:
    """A plain copy of the type with each predicted field's approvals
    attached, or the type itself when it has none -- so every other
    type's digest is unchanged. `catalog_of` is called only then: a
    deployment predicting nothing never reads gold for it."""
    from core.ontology.predicted_fields import declaration_hash, predicted_fields

    attached = {}
    for field_name, prediction in predicted_fields(type_def).items():
        approved = store.approved(object_type, field_name,
                                  declaration_hash(object_type, field_name, prediction))
        if approved:
            attached[field_name] = sorted(
                ({"compartment": proposal.compartment,
                  "skill": proposal.evaluation.get("skill"),
                  "proposal_id": proposal.proposal_id} for proposal in approved),
                key=lambda item: str(item["compartment"]))
    if not attached:
        return type_def
    fields = {name: dict(field) for name, field in (type_def.get("fields") or {}).items()}
    for field_name, approvals in attached.items():
        fields[field_name][APPROVED_PREDICTIONS] = approvals
    try:
        compartments = _how_compartments_resolve(catalog_of(), schema, object_type)
    except Exception as e:  # noqa: BLE001 - unresolvable compartments fill nothing
        logger.warning("%s: its records' compartments could not be resolved (%s: %s); its "
                       "predicted fields are left empty", object_type, type(e).__name__, e)
        return type_def
    return {**type_def, "fields": fields, COMPARTMENTS: compartments}


def _how_compartments_resolve(catalog, schema: dict, object_type: str) -> dict:
    security = (schema.get(object_type) or {}).get("security") or {}
    if "via_field" in security:
        link = security["via_field"]
        target = ((schema[object_type].get("fields") or {}).get(link) or {}).get("target")
        if not target:
            raise ValueError(f"via_field {link!r} is not a link")
        return {"via": link, "by_id": _compartment_by_id(catalog, schema, target, set())}
    return {"field": security.get("field")}


def compartment_of(row: dict, security_field: "str | None") -> Any:
    """The carried value first, then the declared field -- the order
    mediator._get_security_value reads them in. None for a type with no
    security, whose records all share the one compartment None."""
    if security_field is None:
        return None
    carried = row.get(SECURITY_COLUMN)
    return carried if carried is not None else row.get(security_field)


def _compartment_by_id(catalog, schema: dict, object_type: str, seen: set) -> dict[str, Any]:
    """{id: compartment} for every published record of a type, by the
    same rule, following a chain of links to its end."""
    if object_type in seen:
        raise ValueError(f"the security chain through {object_type!r} is a cycle")
    seen = seen | {object_type}
    type_def = schema[object_type]
    id_field = type_def["id_field"]
    security = type_def.get("security") or {}
    table = catalog.load_table(f"{GOLD_NAMESPACE}.{object_type}")
    if "via_field" in security:
        link = security["via_field"]
        target = (type_def["fields"].get(link) or {}).get("target")
        if not target:
            raise ValueError(f"{object_type}'s via_field {link!r} is not a link")
        upstream = _compartment_by_id(catalog, schema, target, seen)
        rows = table.scan(selected_fields=(id_field, link)).to_arrow().to_pylist()
        return {str(row[id_field]): (None if row[link] is None
                                     else upstream.get(str(row[link])))
                for row in rows}
    if "field" not in security:
        rows = table.scan(selected_fields=(id_field,)).to_arrow().to_pylist()
        return {str(row[id_field]): None for row in rows}
    rows = table.scan(selected_fields=(id_field, SECURITY_COLUMN, security["field"])
                      ).to_arrow().to_pylist()
    return {str(row[id_field]): compartment_of(row, security["field"]) for row in rows}
