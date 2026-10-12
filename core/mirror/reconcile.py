"""Reconcile gold against the SOURCE, read fresh, not against the pipeline (R8).

"AN INDEPENDENT RECONCILIATION SOURCE TO GOLD." Everything else that
checks the mirror checks it against ITSELF: the gold audit compares a
build with the previous publication, check_mirror asks whether the
catalog and the warehouse agree, the parity tests run inside the test
suite. None of them can see a value that went wrong on the way IN and
was then faithfully kept. This reads the source system directly,
through the same read-only adapters the sync uses -- never the
mediator's, which read the mirror -- and compares row by row with what
readers are actually served: gold's PUBLISHED snapshot.

THE PRECEDENT IS DATA-DIFF's shape (Datafold's open-source data-diff,
and every finance reconciliation before it): key-level first -- which
keys exist on only one side -- then value-level per column for the keys
both hold, then CONTROL TOTALS, the per-column sums an auditor checks
because a total can be compared without trusting either side's row
list.

A DIFFERENCE IS NOT ALWAYS A FAULT, and the report keeps them apart:

    DECLARED STANDARDISATION  the source says " Ada  Okafor", gold says
                              "Ada Okafor" because the field declares
                              collapse_whitespace. Counted, never a
                              problem: it is the ontology's own rule.
    SINCE THE LAST SYNC       a source row changed after gold was
                              published. Unavoidable between syncs, so
                              the report states the publication time
                              and the read time rather than guessing.
    EVERYTHING ELSE           a fault, and the exit code says so.

THE EXPECTED VALUE IS COMPUTED WITH THE SYNC'S OWN coerce() AND
standardise(), and that is a stated limit rather than a hidden one: a
bug in either would be shared by both sides and not seen here. What
this DOES see is everything else between the source and the reader --
a dropped row, a held-back deletion, a value overwritten by fusion, a
publication that never moved, a type change applied to the wrong
column.

NOT YET RECONCILED: types spanning several storages or resolving
identity across sources (GOLD-5, GOLD-6). Their gold row is built from
several source rows, so there is no one source row to compare with;
they are reported as skipped, by name, never silently passed.
"""

import decimal
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.mirror.gold import _latest_published_snapshot
from core.mirror.standardise import rules_for, standardise
from core.mirror.sync_targets import _targets_for_type
from core.ontology.field_types import DEFAULT_FIELD_DATA_TYPE, coerce, split_declared_type
from core.ontology.gold_view import GOLD_NAMESPACE
from core.ontology.link_types import is_reverse_link

#: How many example ids a report names per kind of difference. Enough
#: to go and look; not a dump of the table.
SAMPLE = 5

_NUMERIC = frozenset({"integer", "number", "decimal"})


@dataclass
class TypeReconciliation:
    object_type: str
    source_rows: int = 0
    gold_rows: int = 0
    only_in_source: list = field(default_factory=list)
    only_in_gold: list = field(default_factory=list)
    #: field -> ids whose gold value is not the source value.
    differing: dict[str, list] = field(default_factory=dict)
    #: field -> how many values differ ONLY by declared standardisation.
    standardised: dict[str, int] = field(default_factory=dict)
    #: field -> (source total, gold total), for numeric fields.
    totals: dict[str, tuple] = field(default_factory=dict)
    skipped: "str | None" = None
    published_at: "str | None" = None

    @property
    def clean(self) -> bool:
        return (self.skipped is None and not self.only_in_source and not self.only_in_gold
                and not self.differing
                and all(source == gold for source, gold in self.totals.values()))


def _comparable(value: Any, data_type: str) -> Any:
    """A value as the reconciliation compares it: a key as text, a
    number exactly, everything else as it is."""
    if value is None:
        return None
    if data_type in _NUMERIC:
        try:
            return decimal.Decimal(str(value))
        except decimal.InvalidOperation:
            return str(value)
    return value


def _expected(raw: Any, field_config: dict) -> tuple[Any, Any]:
    """What gold should hold for one source value: (as read, after the
    field's declared standardisation). Both COERCED, as silver does."""
    declared = field_config.get("data_type") or DEFAULT_FIELD_DATA_TYPE
    data_type, zone = split_declared_type(declared)
    if field_config.get("timezone"):
        zone = field_config["timezone"]

    def typed(value):
        try:
            return _comparable(coerce(value, data_type, zone), data_type)
        except (ValueError, TypeError, decimal.DecimalException):
            # UNCOERCIBLE: silver quarantines or refuses it. Compared as
            # the raw text, so it shows as the difference it is.
            return value

    return typed(raw), typed(standardise(raw, rules_for(field_config)))


def reconcile_rows(object_type: str, type_def: dict, source_rows: list[dict],
                   fields_by_column: dict[str, str], id_column: str,
                   gold_rows: list[dict]) -> TypeReconciliation:
    """Compares one type's source rows with its published gold rows.

    PURE, so the comparison is testable without a database: the caller
    reads both sides.
    """
    result = TypeReconciliation(object_type, len(source_rows), len(gold_rows))
    id_field = type_def["id_field"]
    fields = type_def.get("fields") or {}
    compared = {column: name for column, name in fields_by_column.items()
                if name in fields and name != id_field
                and not (fields[name].get("type") == "link" and is_reverse_link(fields[name]))}

    source_by_id = {str(row.get(id_column)): row for row in source_rows}
    gold_by_id = {str(row.get(id_field)): row for row in gold_rows}
    result.only_in_source = sorted(set(source_by_id) - set(gold_by_id))
    result.only_in_gold = sorted(set(gold_by_id) - set(source_by_id))

    for object_id in sorted(set(source_by_id) & set(gold_by_id)):
        source_row, gold_row = source_by_id[object_id], gold_by_id[object_id]
        for column, field_name in compared.items():
            config = fields[field_name]
            data_type = split_declared_type(config.get("data_type") or DEFAULT_FIELD_DATA_TYPE)[0]
            gold_value = gold_row.get(field_name)
            if config.get("type") == "link":
                # A KEY, and keys are text everywhere in this system.
                raw = source_row.get(column)
                if (None if raw is None else str(raw)) != gold_value:
                    result.differing.setdefault(field_name, []).append(object_id)
                continue
            as_read, as_standardised = _expected(source_row.get(column), config)
            gold_comparable = _comparable(gold_value, data_type)
            if as_read == gold_comparable:
                continue
            if as_standardised == gold_comparable:
                result.standardised[field_name] = result.standardised.get(field_name, 0) + 1
                continue
            result.differing.setdefault(field_name, []).append(object_id)

    # CONTROL TOTALS over EVERY row on each side, not only the shared
    # ones: a total is the check that does not depend on either side's
    # list of keys being right.
    for column, field_name in compared.items():
        config = fields[field_name]
        data_type = split_declared_type(config.get("data_type") or DEFAULT_FIELD_DATA_TYPE)[0]
        if data_type not in _NUMERIC or config.get("type") == "link":
            continue
        source_total = sum((value for value in (_expected(row.get(column), config)[1]
                                                for row in source_rows)
                            if isinstance(value, decimal.Decimal)), decimal.Decimal(0))
        gold_total = sum((value for value in (_comparable(row.get(field_name), data_type)
                                              for row in gold_rows)
                          if isinstance(value, decimal.Decimal)), decimal.Decimal(0))
        result.totals[field_name] = (source_total, gold_total)
    return result


def reconcile(catalog, adapters: dict, object_types: dict,
              published_at: "dict[str, str] | None" = None) -> list[TypeReconciliation]:
    """Every type, source read now against gold as published."""
    results = []
    for object_type, type_def in object_types.items():
        if type_def.get("additional_storage") or type_def.get("identity"):
            results.append(TypeReconciliation(
                object_type,
                skipped="built from several source rows (several storages or identity "
                        "resolution), so there is no one source row to compare with"))
            continue
        targets = list(_targets_for_type(type_def))
        if not targets:
            results.append(TypeReconciliation(object_type, skipped="no storage declared"))
            continue
        silo, table_name, id_column, columns, _types, fields_by_column, *_ = targets[0]
        adapter = adapters.get(silo)
        if adapter is None:
            results.append(TypeReconciliation(object_type, skipped=f"no adapter for silo {silo!r}"))
            continue
        try:
            gold_table = catalog.load_table(f"{GOLD_NAMESPACE}.{object_type}")
        except Exception:  # noqa: BLE001 - no gold is a result, reported as one
            results.append(TypeReconciliation(object_type, skipped="has no gold table"))
            continue
        snapshot = _latest_published_snapshot(gold_table)
        if snapshot is None:
            results.append(TypeReconciliation(object_type, skipped="has never been published"))
            continue
        gold_rows = gold_table.scan(snapshot_id=snapshot).to_arrow().to_pylist()
        source_rows = adapter.read_all_rows(
            table_name, columns, {"storage": {"table": table_name, "id_column": id_column}})
        result = reconcile_rows(object_type, type_def, source_rows, fields_by_column,
                                id_column, gold_rows)
        result.published_at = (published_at or {}).get(object_type)
        results.append(result)
    return results


def describe(results: list[TypeReconciliation], read_at: "datetime | None" = None) -> list[str]:
    """The report, as lines a person reads."""
    read_at = read_at or datetime.now(UTC)
    lines = [f"source read {read_at.isoformat(timespec='seconds')}"]
    for result in results:
        if result.skipped:
            lines.append(f"SKIPPED {result.object_type}: {result.skipped}")
            continue
        verdict = "ok     " if result.clean else "DIFFERS"
        published = f", gold published {result.published_at}" if result.published_at else ""
        lines.append(f"{verdict} {result.object_type}: source {result.source_rows} rows, "
                     f"gold {result.gold_rows}{published}")
        if result.only_in_source:
            lines.append(f"    {len(result.only_in_source)} only in the source: "
                         f"{', '.join(result.only_in_source[:SAMPLE])}")
        if result.only_in_gold:
            lines.append(f"    {len(result.only_in_gold)} only in gold: "
                         f"{', '.join(result.only_in_gold[:SAMPLE])}")
        for field_name, ids in sorted(result.differing.items()):
            lines.append(f"    {field_name}: {len(ids)} value(s) differ -- "
                         f"{', '.join(ids[:SAMPLE])}")
        for field_name, (source_total, gold_total) in sorted(result.totals.items()):
            if source_total != gold_total:
                lines.append(f"    {field_name} total: source {source_total}, gold {gold_total}")
        for field_name, count in sorted(result.standardised.items()):
            lines.append(f"    {field_name}: {count} value(s) differ only by declared "
                         f"standardisation (expected)")
    return lines
