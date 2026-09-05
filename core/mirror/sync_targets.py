"""
sync_targets.py  (works out WHAT to sync, from the ontology alone)

Derives the real list of (silo, table, id_column, columns) tuples a
sync should copy, from `ontology_schema.yaml` itself -- never from a
second, separately-maintained list in config. Deliberate: a separate
list is one more thing to keep in step with the ontology, and drifting
out of step would mean either syncing tables nothing queries, or
(worse, and silently) failing to sync a table the ontology genuinely
references.

WHY THIS IS NOT SIMPLY "ONE TABLE PER OBJECT TYPE": an object type's
fields can span more than one physical table, in two genuinely
different ways this resolver handles explicitly:

  - `additional_storage` (MDO) -- a real, second table, potentially in
    a DIFFERENT silo, backing some of this type's own fields (e.g.
    Customer.risk_score living in risk_sql.customer_risk while every
    other Customer field lives in primary_sql.customers). Each such
    storage becomes its own separate sync target, since it is a real,
    separate physical table.

  - per-field `column` overrides -- a field whose ontology name
    differs from its real column name (e.g. risk_score stored as
    `score_val`). The COLUMN name is what gets synced; the field name
    is an ontology-level concept the mirror never needs to know.

REVERSE LINK FIELDS ARE DELIBERATELY SKIPPED, and this is the subtlest
real decision in this file. A field like Customer.transactions
(`via_table: transactions, via_column: customer_id`) does not live in
Customer's own table at all -- it is resolved by querying the OTHER
type's table. That table (transactions) is already its own sync
target, via the Transaction object type's own storage block, so
syncing it again here would be redundant. Confirmed directly against
the real schema rather than assumed: every `via_table` in the fixture
ontology is another declared object type's own primary table.

FORWARD LINK FIELDS ARE INCLUDED, by contrast, because they are
ordinary columns on this type's own table holding another object's id
(e.g. Transaction.customer_id). Distinguished from reverse links by
the absence of `via_table`, not by cardinality -- cardinality happens
to correlate today but is not what actually determines where the data
physically lives.

THE SECURITY FIELD IS ALWAYS INCLUDED when it names a real field on
this type (`security: {field: region}`). Non-negotiable: MAC filtering
reads it on every single access check, so a mirror missing it would
make every object unreadable. A `via_field` security chain needs no
special handling here -- it names a link field already included as an
ordinary column.

Used by: scripts/run_sync.py
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SyncTarget:
    """One real, physical table to copy, and exactly which columns."""

    silo_name: str
    table_name: str
    id_column: str
    columns: list[str]


def resolve_sync_targets(schema: dict) -> list[SyncTarget]:
    """Every physical table the ontology actually references, with the
    real columns each one needs.

    Deduplicated by (silo, table): two object types genuinely can share
    one physical table, and a table must be synced once with the UNION
    of the columns both types need -- never twice, and never with only
    the second type's columns silently winning.
    """
    by_table: dict[tuple[str, str], dict] = {}

    for type_def in schema.get("object_types", {}).values():
        for silo_name, table_name, id_column, columns in _targets_for_type(type_def):
            key = (silo_name, table_name)
            if key not in by_table:
                by_table[key] = {"id_column": id_column, "columns": []}
            existing = by_table[key]["columns"]
            for column in columns:
                if column not in existing:
                    existing.append(column)

    return [
        SyncTarget(
            silo_name=silo_name,
            table_name=table_name,
            id_column=entry["id_column"],
            columns=entry["columns"],
        )
        for (silo_name, table_name), entry in by_table.items()
    ]


def _targets_for_type(type_def: dict):
    primary = type_def["storage"]
    additional = type_def.get("additional_storage") or {}

    # Every storage this type touches, keyed by the name its own fields
    # use to refer to it. The primary storage is keyed by None, matching
    # how a field with no explicit `storage` key resolves.
    storages = {None: primary}
    storages.update(additional)

    columns_by_storage: dict[str | None, list[str]] = {name: [] for name in storages}

    # The id column of each storage is always needed -- it is what rows
    # are matched on, both during the sync itself and by every read
    # afterward.
    for storage_key, storage in storages.items():
        columns_by_storage[storage_key].append(storage["id_column"])

    for field_name, field_config in type_def.get("fields", {}).items():
        if field_config.get("via_table"):
            # A reverse link -- lives in the OTHER type's table, which is
            # already its own sync target. See this module's docstring.
            continue

        storage_key = field_config.get("storage")
        if storage_key not in columns_by_storage:
            raise ValueError(
                f"Field {field_name!r} references unknown storage {storage_key!r} "
                f"-- known: {sorted(str(k) for k in columns_by_storage)}"
            )
        column = field_config.get("column", field_name)
        if column not in columns_by_storage[storage_key]:
            columns_by_storage[storage_key].append(column)

    # The MAC security field, when it names a real field on this type
    # rather than a chain through a link. Always required -- see this
    # module's docstring.
    security = type_def.get("security") or {}
    security_field = security.get("field")
    if security_field:
        field_config = type_def.get("fields", {}).get(security_field, {})
        storage_key = field_config.get("storage")
        if storage_key in columns_by_storage:
            column = field_config.get("column", security_field)
            if column not in columns_by_storage[storage_key]:
                columns_by_storage[storage_key].append(column)

    for storage_key, storage in storages.items():
        yield (
            storage["silo"],
            storage["table"],
            storage["id_column"],
            columns_by_storage[storage_key],
        )
