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

from dataclasses import dataclass, field

from core.mirror.duplicates import DuplicatePolicy, policy_for_storage
from core.mirror.expectations import expectations_for
from core.mirror.standardise import rules_for


@dataclass(frozen=True)
class SyncTarget:
    """One real, physical table to copy, and exactly which columns."""

    silo_name: str
    table_name: str
    id_column: str
    columns: list[str]
    # column name -> its declared data_type (see core/ontology/
    # field_types.py). Resolved by the SAME ontology walk that resolves
    # `columns` itself, deliberately -- deriving them separately would
    # be two passes that could disagree about which columns exist.
    column_types: dict[str, str]
    # column -> the ontology field it backs, so a verdict about a
    # vanished COLUMN can name the FIELD an operator actually edits.
    # Without it, an error says "source column cust_region is gone" and
    # leaves them grepping ontology_schema.yaml to find out which
    # declaration cares.
    fields_by_column: dict[str, str]
    # The object type(s) backing this table, for asking the write log
    # about pending edits -- it is keyed by OBJECT TYPE, and the sync
    # works in TABLES (PA001-A1). A frozenset because two types can
    # share one table.
    object_types: frozenset = field(default_factory=frozenset)
    # For a many-to-many JOIN TABLE: the two columns whose PAIR
    # identifies a row (PA001-A2). Empty for every ordinary table.
    #
    # A JOIN TABLE HAS NO ID. Keying it by either column alone makes
    # every second row a duplicate -- and the default duplicate policy
    # is QUARANTINE, so a customer with two tags lost one of them and
    # the mirror served a SUBSET of the truth. Measured while fixing
    # this: live said ['c1', 'c2'], the mirror said ['c2'].
    link_pair: tuple = ()
    # column -> the rules silver canonicalises its values with, absent
    # for a column whose field opted out (GOLD-1). Read from the same
    # field declaration as the type above, in the same walk.
    standardisation: dict[str, dict] = field(default_factory=dict)
    # column -> what silver checks on every row and what a failure does
    # (GOLD-1). Absent for a column that declares no constraints.
    expectations: dict[str, dict] = field(default_factory=dict)
    # What to do when two rows claim the same id (GOLD-1). Declared on
    # the storage block, because it is a property of the TABLE.
    duplicate_policy: DuplicatePolicy = field(default_factory=DuplicatePolicy)


# The column a join table is keyed by, synthesised from its pair.
LINK_ID_COLUMN = "_link_id"


def resolve_sync_targets(schema: dict) -> list[SyncTarget]:
    """Every physical table the ontology actually references, with the
    real columns each one needs.

    Deduplicated by (silo, table): two object types genuinely can share
    one physical table, and a table must be synced once with the UNION
    of the columns both types need -- never twice, and never with only
    the second type's columns silently winning.
    """
    by_table: dict[tuple[str, str], dict] = {}

    for object_type, type_def in schema.get("object_types", {}).items():
        for (silo_name, table_name, id_column, columns,
             column_types, fields_by_column,
             standardisation, expectations,
             duplicate_policy) in _targets_for_type(type_def):
            key = (silo_name, table_name)
            if key not in by_table:
                by_table[key] = {"id_column": id_column, "columns": [], "column_types": {},
                             "fields_by_column": {}, "object_types": set(),
                             "standardisation": {},
                             "expectations": {},
                             "duplicate_policy": duplicate_policy}
            existing = by_table[key]["columns"]
            for column in columns:
                if column not in existing:
                    existing.append(column)
            by_table[key]["column_types"].update(column_types)
            by_table[key]["standardisation"].update(standardisation)
            by_table[key]["expectations"].update(expectations)
            by_table[key]["duplicate_policy"] = duplicate_policy
            # FIRST DECLARATION WINS on a shared table. Two object
            # types can back onto one table, and if both map the same
            # column the field names are interchangeable for the
            # purpose this serves -- naming either one tells the
            # operator where to look.
            for column, backing_field in fields_by_column.items():
                by_table[key]["fields_by_column"].setdefault(column, backing_field)
            # WHICH OBJECT TYPES BACK ONTO THIS TABLE (PA001-A1). The
            # write log is keyed by OBJECT TYPE and the sync works in
            # TABLES; the drift policy asked the log using the table
            # name, got zero every time, and absorbed removals that
            # should have been refused.
            #
            # A SET, NOT ONE NAME, because two types CAN share a table
            # -- the loop above already handles that for columns -- and
            # a pending write on either of them is a reason to refuse.
            by_table[key]["object_types"].add(object_type)

    for (silo_name, table_name), entry in by_table.items():
        # INVARIANT: the id column is always synced, and every typed
        # column is one that is actually being copied. Both dicts are
        # merged across separate object types in the loop above, so
        # they can drift apart without either being obviously wrong on
        # its own. A missing id column silently produces a mirror table
        # nothing can be looked up in; a type naming an absent column
        # surfaces later as a KeyError inside the sync, far from the
        # schema that caused it.
        assert entry["id_column"] in entry["columns"], (
            f"{silo_name}.{table_name}: id column {entry['id_column']!r} is not "
            f"among the columns being synced"
        )
        unknown = set(entry["column_types"]) - set(entry["columns"])
        assert not unknown, (
            f"{silo_name}.{table_name}: declared types for columns that are not "
            f"being synced: {sorted(unknown)}"
        )

    return [
        SyncTarget(
            silo_name=silo_name,
            table_name=table_name,
            id_column=entry["id_column"],
            columns=entry["columns"],
            column_types=entry["column_types"],
            fields_by_column=entry["fields_by_column"],
            object_types=frozenset(entry["object_types"]),
            standardisation=entry["standardisation"],
            expectations=entry["expectations"],
            duplicate_policy=entry["duplicate_policy"],
        )
        for (silo_name, table_name), entry in by_table.items()
    ] + _join_table_targets(schema, set(by_table))


def _join_table_targets(schema: dict, already: set) -> list["SyncTarget"]:
    """A target for every many-to-many JOIN TABLE (PA001-A2).

    WHY THEY WERE MISSING. _targets_for_type skips any field carrying
    `via_table`, with a comment saying a reverse link "lives in the
    OTHER type's table, which is already its own sync target". That is
    true for a ONE-to-many link, where via_table IS the target type's
    table. For MANY-to-many it is the join table -- customer_tags,
    enrollments -- which backs no object type at all, so nothing else
    ever emits it.

    WHAT IT COST: on the default read path every many-to-many link,
    its link_counts and its search_around came back EMPTY. Not an
    error, not a warning: an empty list, which reads exactly like a
    customer with no tags. And gold's own link-table publishing reads
    `{silo}.{table}` from silver, so it failed on every run for a
    table that was never going to be there.

    TWO COLUMNS, because that is all a join table has that anyone
    needs: the two sides of the link. The silo is the link SOURCE's,
    which is where link_types.py already resolves the table against.
    """
    seen: dict[tuple, set] = {}
    for type_def in (schema.get("object_types") or {}).values():
        silo = (type_def.get("storage") or {}).get("silo")
        for field_config in (type_def.get("fields") or {}).values():
            via_table = field_config.get("via_table")
            via_column = field_config.get("via_column")
            target_column = field_config.get("via_target_column")
            # BOTH COLUMNS OR IT IS NOT A JOIN TABLE. A one-to-many
            # reverse link carries via_table and via_column but no
            # via_target_column, and its table really is the target
            # type's own -- already a target, and skipping it here is
            # what keeps this from emitting duplicates.
            if not (via_table and via_column and target_column):
                continue
            if (silo, via_table) in already:
                continue
            seen.setdefault((silo, via_table), set()).update({via_column, target_column})
    return [
        SyncTarget(
            silo_name=silo,
            table_name=table_name,
            # NO SINGLE ID COLUMN EXISTS on a join table -- a row is
            # identified by the PAIR. The source column is used so the
            # sync has something to key by; duplicate "ids" are normal
            # here and the duplicate policy must not quarantine them,
            # which is why nothing declares one.
            id_column=LINK_ID_COLUMN,
            columns=sorted(columns),
            column_types={},
            fields_by_column={},
            object_types=frozenset(),
            link_pair=tuple(sorted(columns)),
        )
        for (silo, table_name), columns in sorted(seen.items())
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
    # Only columns with a NON-default declared type are recorded --
    # a column absent from this map takes the default (string), so
    # an untyped schema produces an empty map and the previous
    # behavior exactly.
    types_by_storage: dict[str | None, dict[str, str]] = {name: {} for name in storages}
    # column -> the field it backs, so a drift verdict about a vanished
    # COLUMN can name the FIELD an operator edits. The id column and
    # the MAC security column are deliberately absent: neither is a
    # declared field, and claiming one is would send an operator
    # looking for a declaration that does not exist.
    fields_by_storage: dict[str | None, dict[str, str]] = {name: {} for name in storages}
    standardisation_by_storage: dict[str | None, dict[str, dict]] = {name: {} for name in storages}
    expectations_by_storage: dict[str | None, dict[str, dict]] = {name: {} for name in storages}

    # The id column of each storage is always needed -- it is what rows
    # are matched on, both during the sync itself and by every read
    # afterward. Its type comes from the SAME storage block (`id_type`),
    # read in this same pass -- an object's identity is a property of
    # its storage, and each additional_storage has its own id_column
    # that could genuinely have its own type (Customer is keyed by
    # customer_id in primary but cust_ref in risk_db). See
    # core/ontology/object_type_validation.py's own _validate_id_types()
    # for the fuller reasoning.
    duplicate_by_storage: dict[str | None, DuplicatePolicy] = {}
    for storage_key, storage in storages.items():
        try:
            duplicate_by_storage[storage_key] = policy_for_storage(storage)
        except ValueError as e:
            raise ValueError(f"{storage.get('table', storage_key)!r}: {e}") from None
        columns_by_storage[storage_key].append(storage["id_column"])
        id_type = storage.get("id_type")
        if id_type is not None:
            types_by_storage[storage_key][storage["id_column"]] = id_type

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
        fields_by_storage[storage_key].setdefault(column, field_name)
        declared = field_config.get("data_type")
        if declared is not None:
            types_by_storage[storage_key][column] = declared
        # THE STANDARDISATION RULES travel with the types: both are
        # per column, and both are read from the field that declares
        # the column (GOLD-1).
        try:
            rules = rules_for(field_config)
        except ValueError as e:
            raise ValueError(f"Field {field_name!r}: {e}") from None
        if rules is not None:
            standardisation_by_storage[storage_key][column] = rules
        try:
            expected = expectations_for(field_config)
        except ValueError as e:
            raise ValueError(f"Field {field_name!r}: {e}") from None
        if expected is not None:
            expectations_by_storage[storage_key][column] = {**expected, "field_name": field_name}
            # THE SOURCE ZONE TRAVELS WITH THE TYPE, because it is part
            # of what the type means: a `timestamptz` whose source is
            # naive cannot be read without it. Carried on the same
            # `data_type` string rather than a second dict, so nothing
            # downstream can have one without the other -- validation
            # has already established it appears only on timestamptz.
            timezone_name = field_config.get("timezone")
            if timezone_name is not None:
                types_by_storage[storage_key][column] = f"{declared}@{timezone_name}"

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
            types_by_storage[storage_key],
            fields_by_storage[storage_key],
            standardisation_by_storage[storage_key],
            expectations_by_storage[storage_key],
            duplicate_by_storage[storage_key],
        )
