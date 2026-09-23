"""Choosing between two sources' versions of one property (GOLD-6).

THIS IS THE QUESTION GOLD-5 COULD NOT ASK. There, each property had
exactly one home, so a type spanning storages was a join. Once
identity resolution decides that billing's `c1` and the CRM's `9f2a`
are one customer, BOTH may hold a name, and something has to choose.

SURVIVORSHIP IS PER ATTRIBUTE, not per record -- the MDM practice this
project's research recorded: "trusted source, most recent, most
frequent, most complete -- usually mixed by attribute". A record-level
"the CRM wins" is the wrong shape: the CRM may have the better address
and the worse phone number.

AND THE LOSING VALUE IS KEPT. The same research is blunt about it:
"deleting losing values destroys trust". A person asking why the
golden record says Leeds needs to see that the CRM said Hull and was
outranked -- otherwise the answer is an assertion. Losers go to the
conflicts table, not to the bin.

WHAT A DEPLOYMENT DECLARES, and nothing more clever:

    survivorship:
      prefer: [billing, crm]      # per type: the order sources win in

    fields:
      phone:
        survivorship: {prefer: [crm]}   # per field, overriding it

THE DEFAULT IS THE DECLARATION ORDER -- primary storage first, then
additional storages as written -- and within that, THE FIRST NON-NULL
VALUE WINS. "Most complete" as a default, because a source that has
nothing to say about a property should not silently blank it.

NOT IMPLEMENTED, DELIBERATELY: most-recent survivorship. It needs a
per-property timestamp that silver does not carry, and inventing one
from a row's sync time would answer "when did we READ it" rather than
"when did it CHANGE". Recorded here rather than guessed at.
"""

from dataclasses import dataclass, field
from typing import Any

from core.mirror.identity import Resolution

# What a conflict row records. One per property where sources
# disagreed, plus one per merge refused by D2.
PROPERTY_CONFLICT = "property"
SECURITY_CONFLICT = "security"


@dataclass
class Conflict:
    """One disagreement, kept rather than discarded."""

    entity_id: str
    kind: str
    field_name: str | None
    chosen: Any
    chosen_source: str
    losing: Any
    losing_source: str


@dataclass
class FusedEntities:
    rows: list[dict] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)


def _order_for(type_def: dict, field_name: str | None) -> list:
    """The storages in the order they win, for a type or one field."""
    declared_order = list((type_def.get("survivorship") or {}).get("prefer") or [])
    if field_name is not None:
        field_config = (type_def.get("fields") or {}).get(field_name) or {}
        override = (field_config.get("survivorship") or {}).get("prefer")
        if override:
            declared_order = list(override)
    natural = [None, *(type_def.get("additional_storage") or {})]
    # A declared order names storages; anything it omits keeps its
    # natural place after them, so a partial preference is legal and
    # means "these first".
    ordered = [key for key in declared_order if key in natural]
    ordered += [key for key in natural if key not in ordered]
    return ordered


def _source_name(storage_key: Any) -> str:
    return "primary" if storage_key is None else str(storage_key)


def _column_for(type_def: dict, field_name: str, storage_key: Any) -> str | None:
    """What that storage calls this field, or None if it does not hold
    it."""
    field_config = (type_def.get("fields") or {}).get(field_name) or {}
    declared_storage = field_config.get("storage")
    if declared_storage is not None and declared_storage != storage_key:
        return None
    return field_config.get("column", field_name)


def fuse_entities(type_def: dict, resolution: Resolution) -> FusedEntities:
    """One row per entity, with each property chosen and the losers
    recorded."""
    fused = FusedEntities()
    id_field = type_def["id_field"]
    property_names = [
        name for name in (type_def.get("fields") or {})
        if (type_def["fields"][name].get("type") != "link"
            or type_def["fields"][name].get("cardinality") == "one")
    ]

    for entity_id in sorted(resolution.entities):
        members = resolution.entities[entity_id]
        row: dict = {id_field: entity_id}
        contributing = sorted(_source_name(key) for key in members)
        for field_name in property_names:
            if field_name == id_field:
                continue
            chosen_value, chosen_source = None, None
            for storage_key in _order_for(type_def, field_name):
                source_row = members.get(storage_key)
                if source_row is None:
                    continue
                column = _column_for(type_def, field_name, storage_key)
                if column is None:
                    continue
                value = source_row.get(column)
                if value is None:
                    continue
                if chosen_value is None:
                    chosen_value, chosen_source = value, _source_name(storage_key)
                elif str(value) != str(chosen_value):
                    # KEPT, NOT DISCARDED: a person asking why the
                    # golden record says one thing must be able to see
                    # what the other source said.
                    fused.conflicts.append(Conflict(
                        entity_id=entity_id, kind=PROPERTY_CONFLICT, field_name=field_name,
                        chosen=chosen_value, chosen_source=chosen_source or "",
                        losing=value, losing_source=_source_name(storage_key),
                    ))
            row[field_name] = chosen_value
        row["_fused_from"] = ",".join(contributing)
        # Lineage from whichever member carried it, in winning order.
        for storage_key in _order_for(type_def, None):
            source_row = members.get(storage_key)
            if source_row is None:
                continue
            for column, value in source_row.items():
                if column.startswith("_") and column not in row:
                    row[column] = value
        fused.rows.append(row)

    for entity_id, values in resolution.refused:
        # D2's refusals travel with the property conflicts, because an
        # operator looking for "what did identity resolution decline to
        # do" should find one place, not two.
        sources = sorted(values, key=lambda key: _source_name(key))
        fused.conflicts.append(Conflict(
            entity_id=entity_id, kind=SECURITY_CONFLICT, field_name=None,
            chosen=values[sources[0]], chosen_source=_source_name(sources[0]),
            losing=values[sources[-1]], losing_source=_source_name(sources[-1]),
        ))
    return fused
