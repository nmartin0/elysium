"""Columns that look like links nobody declared (R54).

THE METHOD IS INCLUSION DEPENDENCIES, the standard first step of
foreign-key discovery: "attributes A and B such that all values of A are
included in all values of B" (HPI's SPIDER project, Bauckmann, Leser and
Naumann). Here B is always a type's own id column, so a hit reads: every
value in Transaction.account_ref is the id of some Account.

AND IT IS ONLY THE FIRST STEP. SPIDER's own caveat is that an inclusion
dependency is the "syntactical and automatically testable part of a
foreign key constraint"; whether it IS one takes judgement. Small
integer ids are included in each other by accident all the time. So:

  PARTIAL, not exact -- real data is dirty, and one orphaned row would
  hide a link a person would want to know about. A column qualifies at
  MIN_COVERAGE, and the report says how many values did not match.

  A NAME HINT is reported beside the numbers -- the column is named like
  the target type or its id -- because it is the cheapest of SPIDER's
  filtering heuristics and the one a person checks first. It ranks; it
  does not decide.

  NOTHING IS APPLIED. This prints. Declaring a link is an ontology
  change somebody makes on purpose.

SKIPPED: a type's own id column, the security column, columns already
backing a declared link, and columns with fewer than MIN_DISTINCT
values -- a region or a status is "included" in anything that happens to
share its three values.
"""

import re
from dataclasses import dataclass

MIN_COVERAGE = 0.95
MIN_DISTINCT = 3


@dataclass(frozen=True)
class LinkCandidate:
    object_type: str
    column: str
    field: "str | None"          # the declared field the column backs, if any
    target_type: str
    distinct: int
    unmatched: int
    named_like_target: bool

    @property
    def coverage(self) -> float:
        return (self.distinct - self.unmatched) / self.distinct


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _named_like(column: str, target_type: str, target_id_column: str) -> bool:
    column, target = _norm(column), _norm(target_type)
    return target in column or column == _norm(target_id_column)


def _distinct(rows: list[dict], column: str) -> set[str]:
    return {str(row[column]) for row in rows if row.get(column) not in (None, "")}


def discover(schema: dict, rows_for) -> list[LinkCandidate]:
    """Every column that looks like an undeclared link.

    `rows_for(silo, table)` returns that bronze table's rows (a sample is
    fine), or None when it has not been synced.
    """
    from core.mirror.sync_targets import _targets_for_type

    ids: dict[str, tuple[str, set[str]]] = {}
    for object_type, type_def in (schema or {}).items():
        storage = type_def["storage"]
        rows = rows_for(storage["silo"], storage["table"])
        if rows:
            ids[object_type] = (storage["id_column"], _distinct(rows, storage["id_column"]))

    found: list[LinkCandidate] = []
    for object_type, type_def in sorted((schema or {}).items()):
        fields = type_def.get("fields") or {}
        security = (type_def.get("security") or {}).get("field")
        for target in _targets_for_type(type_def):
            silo, table, id_column, fields_by_column = target[0], target[1], target[2], target[5]
            rows = rows_for(silo, table)
            if not rows:
                continue
            skip = {id_column}
            for column, field_name in fields_by_column.items():
                if (fields.get(field_name) or {}).get("type") == "link" or field_name == security:
                    skip.add(column)
            columns = sorted({key for row in rows for key in row}
                             - skip - {key for key in rows[0] if key.startswith("_")})
            for column in columns:
                values = _distinct(rows, column)
                if len(values) < MIN_DISTINCT:
                    continue
                for target_type, (target_id, target_ids) in sorted(ids.items()):
                    unmatched = len(values - target_ids)
                    if (len(values) - unmatched) / len(values) >= MIN_COVERAGE:
                        found.append(LinkCandidate(
                            object_type, column, fields_by_column.get(column), target_type,
                            len(values), unmatched,
                            _named_like(column, target_type, target_id)))
    # NAMED LIKE THE TARGET FIRST, then by coverage: the order a person
    # would check them in.
    return sorted(found, key=lambda c: (not c.named_like_target, -c.coverage, c.object_type,
                                        c.column, c.target_type))


def bronze_rows(catalog, limit: int = 50_000):
    """A rows_for() over the mirror's bronze tables."""
    def rows_for(silo: str, table: str):
        try:
            return catalog.load_table(f"bronze_{silo}.{table}").scan(limit=limit).to_arrow().to_pylist()
        except Exception:  # noqa: BLE001 - not synced is not an error here
            return None
    return rows_for
