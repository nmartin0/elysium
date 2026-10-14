"""Which ontology fields a new source table's columns probably are (R55).

WHAT IT HELPS WITH: binding a table the ontology does not read yet --
a CRM's contacts table that also describes Customers -- means writing an
additional_storage block and a `storage:`/`column:` pair per field, by
hand, by guessing from column names. This puts two kinds of evidence in
front of whoever is writing it.

TWO SIGNALS, kept apart rather than blended, because a schema-matching
result is something a person judges and they judge them differently:

  NAME     how alike the column and field names are, after case and
           punctuation are ignored (difflib's ratio; the field's own
           `column` and display name count too). Cheap, and misleading
           whenever two systems name things differently.
  VALUES   what share of the column's distinct values already appear
           in that field in gold. Slower, and the stronger evidence:
           "cust_ref" means nothing, but its values being Customer ids
           means a lot.

This is the instance-based-plus-name-based pairing the schema-matching
literature describes; what it does NOT do is decide. It prints, and the
binding stays a change somebody makes on purpose.
"""

import difflib
import re
from dataclasses import dataclass

#: A candidate is listed when either signal reaches its bar.
NAME_BAR = 0.6
VALUE_BAR = 0.3
TOP = 3


@dataclass(frozen=True)
class FieldMatch:
    column: str
    object_type: str
    field: str
    name_score: float
    value_share: "float | None"   # None when the field held nothing to compare


@dataclass(frozen=True)
class IdMatch:
    column: str
    object_type: str
    share: float


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _name_score(column: str, field: str, field_config: dict) -> float:
    names = [field, field_config.get("column"), field_config.get("display_name")]
    return max(difflib.SequenceMatcher(None, _norm(column), _norm(name)).ratio()
               for name in names if name)


def _distinct(rows: list[dict], column: str) -> set[str]:
    return {str(row[column]) for row in rows if row.get(column) not in (None, "")}


def suggest(schema: dict, source_rows: list[dict], gold_rows_for,
            only_type: "str | None" = None) -> tuple[dict[str, list[FieldMatch]], list[IdMatch]]:
    """Per source column, the likeliest fields; and which columns look
    like the id of a type.

    `gold_rows_for(object_type)` returns that type's gold rows (a sample
    is fine), or None.
    """
    columns = sorted({key for row in source_rows for key in row})
    source_values = {column: _distinct(source_rows, column) for column in columns}
    by_column: dict[str, list[FieldMatch]] = {column: [] for column in columns}
    ids: list[IdMatch] = []
    for object_type, type_def in sorted((schema or {}).items()):
        if only_type is not None and object_type != only_type:
            continue
        gold = gold_rows_for(object_type) or []
        id_field = type_def.get("id_field")
        id_values = _distinct(gold, id_field) if id_field else set()
        for column in columns:
            values = source_values[column]
            if values and id_values:
                share = len(values & id_values) / len(values)
                if share >= VALUE_BAR:
                    ids.append(IdMatch(column, object_type, share))
            for field, config in ((type_def.get("fields") or {}).items()):
                config = config or {}
                if config.get("type", "data") != "data":
                    continue
                gold_values = _distinct(gold, field)
                value_share = (len(values & gold_values) / len(values)
                               if values and gold_values else None)
                score = _name_score(column, field, config)
                if score >= NAME_BAR or (value_share or 0) >= VALUE_BAR:
                    by_column[column].append(
                        FieldMatch(column, object_type, field, score, value_share))
    for column, found in by_column.items():
        found.sort(key=lambda m: (-(m.value_share or 0), -m.name_score, m.object_type, m.field))
        by_column[column] = found[:TOP]
    ids.sort(key=lambda m: (-m.share, m.object_type, m.column))
    return by_column, ids


def yaml_skeleton(object_type: str, storage_key: str, silo: str, table: str,
                  id_column: "str | None", fields: dict[str, str]) -> str:
    """The additional_storage block and the field bindings, to edit."""
    lines = ["object_types:", f"  {object_type}:", "    additional_storage:",
             f"      {storage_key}:", f"        silo: {silo}", f"        table: {table}",
             f"        id_column: {id_column or '<the column holding the id>'}", "    fields:"]
    for field, column in sorted(fields.items()):
        lines += [f"      {field}:", f"        storage: {storage_key}", f"        column: {column}"]
    return "\n".join(lines)
