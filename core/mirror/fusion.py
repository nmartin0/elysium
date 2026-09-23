"""One object from several storages (GOLD-5).

WHAT A MULTI-SOURCE TYPE ACTUALLY IS HERE, audited before designing
rather than assumed. Elysium's schema gives each storage its OWN
id_column, and each field names EXACTLY ONE storage. So a Customer
spanning `primary_sql.customers` and `risk_db.risk_scores` is a JOIN:
every property has one authoritative home, and no two storages offer a
competing value for the same property.

THAT MAKES THIS THE DETERMINISTIC HALF, and it is the half
FUSION_AND_IDENTITY.md insists comes first: "hand-written joins are
the PRIMARY path, not a fallback ... the gold layer must work with
ZERO INFERENCE."

WHAT IS THEREFORE *NOT* HERE, and is not missing:

  SURVIVORSHIP PER PROPERTY -- choosing between two sources' versions
  of one value -- cannot arise while each property has one home. It
  arises when two sources describe the same entity INDEPENDENTLY,
  which is identity resolution (GOLD-6), and it is designed there.

  A MAC CONFLICT (the owner's decision D2, refuse and review) is the
  same case: the security field lives in one storage, so the storages
  cannot disagree about it. D2 governs GOLD-6's fused entities.

  Writing either one now would be guessing at a shape the next step
  will settle.

THE JOIN IS OUTER, and deliberately. An object present in one storage
and absent from another is a real thing -- a customer with no risk
score yet -- and dropping it would silently lose an object that
exists. Its properties from the absent storage are null, and if one of
those is declared `required`, GOLD'S AUDIT REFUSES THE PUBLICATION.
The check already exists; this just lets it see the case.
"""

from typing import Any

# Which storages contributed to a fused row. Lineage per PROPERTY is
# what GOLD-6's review will need; this is the honest thing available
# now -- per ROW, naming every storage that had something to say.
FUSED_FROM_COLUMN = "_fused_from"


def _storages_of(type_def: dict) -> dict[Any, dict]:
    """{storage key: its block}, with None for the primary one --
    matching how a field's `storage` pointer names them."""
    storages: dict[Any, dict] = {None: type_def["storage"]}
    storages.update(type_def.get("additional_storage") or {})
    return storages


def fields_by_storage(type_def: dict) -> dict[Any, list[str]]:
    """{storage key: the fields it holds}. A field with no pointer is
    the primary storage's, which is what the rest of the system means
    by an absent `storage` key."""
    grouped: dict[Any, list[str]] = {key: [] for key in _storages_of(type_def)}
    for field_name, field_config in (type_def.get("fields") or {}).items():
        key = field_config.get("storage")
        if key in grouped:
            grouped[key].append(field_name)
    return grouped


def fuse(type_def: dict, rows_by_storage: dict[Any, list[dict]]) -> list[dict]:
    """One row per object, joined across storages by the object's id.

    Each storage's rows are keyed by ITS OWN id_column, because the
    same object is `customer_id` in one database and `cust_ref` in
    another -- which the schema already lets a deployment say.

    THE ORDER OF THE RESULT follows the primary storage, then anything
    seen only elsewhere, so a fused build is reproducible rather than
    dependent on dictionary iteration order.
    """
    storages = _storages_of(type_def)
    grouped_fields = fields_by_storage(type_def)
    id_field = type_def["id_field"]

    indexed: dict[Any, dict[Any, dict]] = {}
    order: list[str] = []
    for key, storage in storages.items():
        id_column = storage["id_column"]
        by_id = {}
        for row in rows_by_storage.get(key) or []:
            object_id = row.get(id_column)
            if object_id is None:
                # An id-less row cannot be joined to anything. Silver's
                # own expectations are where a missing key is reported;
                # here it simply has nowhere to go.
                continue
            by_id[str(object_id)] = row
            if key is None and str(object_id) not in order:
                order.append(str(object_id))
        indexed[key] = by_id

    for key in storages:
        if key is None:
            continue
        for object_id in indexed[key]:
            if object_id not in order:
                order.append(object_id)

    fused = []
    for object_id in order:
        fused_row: dict = {}
        contributed = []
        for key in storages:
            source_row = indexed[key].get(object_id)
            if source_row is None:
                # OUTER: the properties this storage holds are null for
                # this object, and a `required` one makes the audit
                # refuse the publication.
                for field_name in grouped_fields[key]:
                    fused_row.setdefault(field_name, None)
                continue
            contributed.append("primary" if key is None else str(key))
            for field_name in grouped_fields[key]:
                field_config = (type_def.get("fields") or {})[field_name]
                column = field_config.get("column", field_name)
                fused_row[field_name] = source_row.get(column)
            if key is None:
                # Lineage travels from the primary storage's row, where
                # silver put it.
                for column, value in source_row.items():
                    if column.startswith("_"):
                        fused_row[column] = value
        fused_row[id_field] = object_id
        fused_row[FUSED_FROM_COLUMN] = ",".join(sorted(contributed))
        fused.append(fused_row)
    return fused
