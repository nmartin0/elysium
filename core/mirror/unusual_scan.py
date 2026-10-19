"""Unusual records, found when a type's gold is rebuilt (R51).

run_sync calls this for a type that declares `unusual` and whose gold was
just published; a type whose gold did not change keeps its flags, since
nothing they rest on moved. Kept in the mirror, as the other gold-side
steps are, so the flag store stays a store.

EACH RECORD'S COMPARTMENT BY THE READ PATH'S RULE -- prediction_fill's,
shared: the carried `_security`, else the declared field; through a
link, the linked record's. Each compartment is judged on its own.
"""

import logging

from core.carried_columns import SECURITY_COLUMN
from core.ontology.gold_view import GOLD_NAMESPACE

logger = logging.getLogger(__name__)


def scan(catalog, schema: dict, object_type: str, store) -> "int | None":
    """Finds and stores the type's unusual records. Returns how many
    were found, or None when the type declares no check or its records
    could not be read (its earlier flags are then left as they were)."""
    from core.mirror.prediction_fill import compartment_of, how_compartments_resolve
    from core.ontology.unusual_checks import unusual_of
    from core.unusual import find_unusual

    type_def = schema.get(object_type) or {}
    declared = unusual_of(type_def)
    if declared is None:
        return None
    numbers, within = declared
    id_field = type_def["id_field"]
    try:
        how = how_compartments_resolve(catalog, schema, object_type)
        table = catalog.load_table(f"{GOLD_NAMESPACE}.{object_type}")
        names = {id_field, *numbers, *within, how.get("via"), how.get("field")} - {None}
        present = set(table.schema().column_names)
        wanted = [name for name in sorted(names | {SECURITY_COLUMN}) if name in present]
        rows = table.scan(selected_fields=tuple(wanted)).to_arrow().to_pylist()
    except Exception as e:  # noqa: BLE001 - one type's failure costs only its flags
        logger.warning("%s: could not look for unusual records (%s: %s)", object_type,
                       type(e).__name__, e)
        return None
    by_compartment: dict = {}
    for row in rows:
        if "via" in how:
            link = row.get(how["via"])
            compartment = None if link is None else how["by_id"].get(str(link))
        else:
            compartment = compartment_of(row, how.get("field"))
        by_compartment.setdefault(compartment, []).append(row)
    found = {compartment: find_unusual(members, id_field, numbers, within)
             for compartment, members in by_compartment.items()}
    store.replace(object_type, found)
    return sum(total for _, total in found.values())
