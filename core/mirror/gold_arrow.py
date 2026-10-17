"""Conforming and auditing gold WITHOUT building Python dicts
(GOLD-7).

WHY THIS EXISTS, MEASURED RATHER THAN ASSUMED. A silver table read as
Arrow holds 200,000 six-column rows in 25.7 MB of buffers. The same
rows as a list of dicts peak at 154.3 MB -- 772 bytes per row, a SIX-
FOLD amplification, because every value becomes a Python object and
every row a hash table. Extrapolated, ten million rows would need
7.7 GB as dicts against roughly 1.3 GB as Arrow.

AND THE WORK DID NOT NEED DICTS. conform() is a column RENAME and a
projection; audit() counts nulls, counts distinct ids and compares
totals. Both are what Arrow is for, and doing them in Python was
paying six times the memory to use a slower representation.

WHAT STILL NEEDS DICTS, and is honestly out of scope here: identity
resolution and survivorship (GOLD-6) compare values row by row across
sources, and the changelog diffs two snapshots by key. Those are
row-shaped problems, and the dict path remains for them -- which is
why this is a SECOND path rather than a replacement. A type declaring
identity keeps the old one.

THE LIMIT THIS DOES NOT REMOVE. Arrow still materialises the whole
table. What it removes is the six-fold multiplier, which is the
difference between a table that fits and one that does not on the same
machine. Streaming gold in batches is a further step, and it is
blocked on the audit: "are these ids unique" cannot be answered by a
batch that has not seen the others.
"""

import pyarrow as pa
import pyarrow.compute as pc

from core.mirror.lineage import CARRIED_COLUMNS
from core.ontology.field_types import arrow_type_for
from core.ontology.link_types import is_reverse_link


def conform_arrow(type_def: dict, silver: pa.Table) -> pa.Table:
    """Silver's columns, renamed to the ontology's property names.

    A COLUMN OPERATION, not a row one: the buffers are reused, so this
    costs almost nothing however many rows there are.
    """
    id_column = type_def["storage"]["id_column"]
    mapping = {id_column: type_def["id_field"]}
    for field_name, field_config in (type_def.get("fields") or {}).items():
        if field_config.get("type") == "link" and is_reverse_link(field_config):
            continue
        mapping[field_config.get("column", field_name)] = field_name

    fields = type_def.get("fields") or {}
    columns, names = [], []
    for column, field_name in mapping.items():
        # TYPED AS THE ONTOLOGY DECLARES, exactly as the dict path is
        # (patch 370): silver's inferred type is not the contract, the
        # declaration is. A column of all nulls arrives typed `null`,
        # which Iceberg refuses outright -- and a decimal read as text
        # would make a money filter match nothing, which is the bug the
        # parity test found in the first place.
        field_config = fields.get(field_name) or {}
        if field_config.get("type") == "link" or field_name == type_def["id_field"]:
            wanted = pa.string()
        else:
            wanted = arrow_type_for(field_config.get("data_type", "string"))
        if column in silver.column_names:
            values = silver.column(column)
            columns.append(values if values.type == wanted else values.cast(wanted))
        else:
            # A DECLARED PROPERTY SILVER DOES NOT HOLD is null here,
            # exactly as the dict path produced -- and the audit is
            # where a required one becomes a refusal.
            columns.append(pa.nulls(silver.num_rows, type=wanted))
        names.append(field_name)
    for column in CARRIED_COLUMNS:
        # EVERY LINEAGE COLUMN, NULL WHERE SILVER LACKS IT -- which is
        # what the dict path produces, and the parity test caught the
        # difference: a gold table whose columns depend on which
        # lineage silver happened to carry would reshape itself between
        # builds, and GOLD-6's reshape check would then rebuild it.
        if column in silver.column_names:
            # CAST, NOT PASSED THROUGH. A batch reader types these as
            # large_string while a materialised scan types them as
            # string, so gold's schema would depend on HOW silver was
            # read -- and the next build, reading it the other way,
            # would see a changed column set and rebuild the table.
            #
            # FOUND BY COMPARING the streamed and materialised builds
            # of one table: identical rows, different schemas.
            values = silver.column(column)
            columns.append(values if values.type == pa.string()
                            else values.cast(pa.string()))
        else:
            columns.append(pa.nulls(silver.num_rows, type=pa.string()))
        names.append(column)
    return with_derived(pa.Table.from_arrays(columns, names=names), type_def)


def with_derived(table: pa.Table, type_def: dict) -> pa.Table:
    """Gold's derived columns (R37), computed from the row's other
    properties. ONE PLACE FOR ALL THREE GOLD PATHS -- the dict path's
    _arrow, the Arrow path and the streamed batches all end here -- so
    a derived value cannot depend on which path published it.

    Per row in Python over the INPUT columns only, and only for a type
    that declares one: the formulas are not Arrow kernels, and a type
    without derived fields pays nothing."""
    from core.ontology.derived_fields import compute, derived_fields, finished

    fields = type_def.get("fields") or {}
    for field_name, derivation in derived_fields(type_def).items():
        if field_name not in table.column_names:
            continue
        inputs = {name: table.column(name).to_pylist()
                  for name in derivation.inputs if name in table.column_names}
        data_type = fields[field_name].get("data_type") or "string"
        values = [finished(compute(derivation, {name: column[index]
                                                for name, column in inputs.items()}), data_type)
                  for index in range(table.num_rows)]
        position = table.column_names.index(field_name)
        table = table.set_column(position, field_name,
                                 pa.array(values, type=table.schema.field(field_name).type))
    # ENRICHED FIELDS (R41) FROM HERE TOO, for the same reason: this is
    # where all three gold paths end.
    return with_enriched(table, type_def)


#: Where run_sync puts a field's APPROVED rules on the copy of the type
#: it hands to build_gold. Underscored, so no ontology can declare it:
#: an enriched field's ALLOWED_BESIDE refuses any other key at load.
APPROVED_RULES = "_approved_rules"
#: Beside them, for an EXTRACTED field: the locale its source writes
#: numbers and dates in (DEP-1), which types the text a rule took.
APPROVED_LOCALE = "_approved_locale"


def with_enriched(table: pa.Table, type_def: dict) -> pa.Table:
    """Gold's enriched columns (R41): each row's value from the rules a
    person APPROVED, or empty.

    NO MODEL HERE, and none can be: the rules were compiled and approved
    before the sync, and applying them is word matching. A field with no
    approved recipe -- none proposed yet, one rejected, or one approved
    for a declaration that has since changed -- is left as the empty
    column conform gave it, which is the honest value (R52)."""
    from core.ontology.enriched_fields import apply_recipe, enriched_fields
    from core.ontology.extraction_rules import typed

    fields = type_def.get("fields") or {}
    for field_name, enrichment in enriched_fields(type_def).items():
        rules = (fields.get(field_name) or {}).get(APPROVED_RULES)
        if not rules or field_name not in table.column_names:
            continue
        inputs = {name: table.column(name).to_pylist()
                  for name in enrichment.inputs if name in table.column_names}
        # ONE RULE SET OR A WEIGHTED VOTE of several (17 October).
        values = [apply_recipe(rules, {name: column[index] for name, column in inputs.items()})
                  for index in range(table.num_rows)]
        if enrichment.extract is not None:
            # TEXT TAKEN FROM THE ROW, TYPED AS THE SYNC TYPES: the same
            # converter, the same locale, the same refusals -- and a
            # value that does not convert is empty, never repaired.
            locale = (fields.get(field_name) or {}).get(APPROVED_LOCALE)
            values = [typed(value, enrichment.extract, locale) for value in values]
        position = table.column_names.index(field_name)
        table = table.set_column(position, field_name,
                                 pa.array(values, type=table.schema.field(field_name).type))
    return table


def audit_arrow(type_def: dict, table: pa.Table, previous_count: int | None,
                known_ids: "dict[str, set] | None" = None) -> list[str]:
    """The same findings as audit(), counted in Arrow.

    Kept deliberately parallel to the dict version, because two checks
    that are supposed to agree and drift apart are worse than one
    slower check.
    """
    from core.mirror.gold import MAX_DELETED_FRACTION

    problems: list[str] = []
    id_field = type_def["id_field"]
    if id_field not in table.column_names:
        return [f"no {id_field} column"]

    ids = table.column(id_field)
    missing = ids.null_count
    if missing:
        problems.append(f"{missing} row(s) have no {id_field}")

    present = ids.drop_null()
    # AN ALL-NULL ID COLUMN arrives typed `null`, and count_distinct
    # has no kernel for that -- so uniqueness is SKIPPED, not the rest
    # of the audit. It used to `return` here, which silently dropped
    # the required-property, dangling-link and row-count checks for
    # exactly the table most likely to fail them.
    #
    # FOUND BY WRITING A THIRD IMPLEMENTATION (the streaming one) and
    # comparing all three: the dict and streaming audits both reported
    # "1 rows, down from 10" on a table this one called clean.
    duplicated = len(present) and not pa.types.is_null(present.type) and (
        pc.count_distinct(present).as_py() != len(present))
    if duplicated:
        # NAMED, NOT JUST COUNTED: an operator cannot act on "there are
        # duplicates" without knowing which -- the dict path shows
        # examples too, and losing that would make this check useless
        # in exactly the case it fires.
        repeated = sorted(
            (entry["values"] for entry in present.value_counts().to_pylist()
             if entry["counts"] > 1),
            key=repr,
        )
        shown = ", ".join(repr(value) for value in repeated[:5])
        problems.append(f"{len(repeated)} duplicate {id_field}(s): {shown}")

    for field_name, field_config in (type_def.get("fields") or {}).items():
        if not field_config.get("required"):
            continue
        if field_name not in table.column_names:
            problems.append(f"{table.num_rows} row(s) are missing required {field_name}")
            continue
        absent = table.column(field_name).null_count
        if absent:
            problems.append(f"{absent} row(s) are missing required {field_name}")

    for field_name, field_config in (type_def.get("fields") or {}).items():
        if field_config.get("type") != "link" or is_reverse_link(field_config):
            continue
        target = field_config.get("target")
        if not known_ids or target not in known_ids or field_name not in table.column_names:
            continue
        values = table.column(field_name).drop_null()
        if not len(values):
            continue
        absent_mask = pc.invert(pc.is_in(
            values, value_set=pa.array(sorted(str(value) for value in known_ids[target]))))
        dangling = sorted(set(values.filter(absent_mask).to_pylist()), key=repr)
        if dangling:
            shown = ", ".join(repr(value) for value in dangling[:5])
            problems.append(
                f"{len(dangling)} {field_name} value(s) point at no {target}: {shown}"
            )

    if previous_count and table.num_rows < previous_count * (1 - MAX_DELETED_FRACTION):
        problems.append(
            f"{table.num_rows} rows, down from {previous_count}: more than "
            f"{MAX_DELETED_FRACTION:.0%} of the last publication is gone"
        )
    return problems
