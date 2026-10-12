"""Field classifications, carried to every table that holds the values (R12).

THE RULE IS FOUNDRY'S: "If a dataset has a file marking, every dataset
that depends on it inherits that marking." A field declared
`classification: pii` in the ontology is one property, and its values
live in up to seven tables here. Each gets the label, on the column
that holds them, as the Iceberg table property CLASSIFICATIONS_PROPERTY:

    bronze_<silo>.<table>       the source column, verbatim     per column
    <silo>.<table>   (silver)   the same column, standardised   per column
    changelog_<silo>.<table>    every past value of it          per column
    quarantine_<silo>.<table>   a refused value, of ANY column  `value`: union
    gold.<Type>                 the property, conformed         per field
    gold_history.<Type>         every past row, as JSON         `values`: union
    gold_conflicts.<Type>       the winning and losing values   `chosen`, `losing`: union

WHERE ONE COLUMN HOLDS VALUES OF MANY FIELDS it carries the union of
their labels. That is conservative by construction -- a quarantine row
refusing a non-PII column is labelled as though it might hold PII --
and it is the same direction Foundry errs in: a derived dataset
inherits every marking of everything it depends on, and removing one is
"a sensitive action", never an inference.

THE LINEAGE IS DECLARED, NOT DISCOVERED. Which source column backs
which field is the ontology's `column:`/`storage:` mapping, resolved by
the same `_targets_for_type` the sync itself copies by -- so the
column labelled is the column copied, by construction rather than by a
second walk that could disagree with the first.

A TABLE PROPERTY, NOT A COLUMN `doc`. Iceberg has no column tags. A
`doc` would be a schema change -- a new metadata version, a column
evolution -- every time a label changed; a property is one metadata
commit, readable by anything that reads the catalog, and does not touch
a snapshot.

LABELS ONLY. Nothing here decides who may read anything; see
core/ontology/classifications.py and BLOCKING 6.
"""

import json
import logging

from core.mirror.sync_targets import _targets_for_type
from core.ontology.classifications import field_classifications
from core.ontology.gold_view import GOLD_NAMESPACE
from core.ontology.link_types import is_reverse_link

logger = logging.getLogger(__name__)

CLASSIFICATIONS_PROPERTY = "elysium.classifications"

# Namespaces of the derived tables, as their writers name them.
_CHANGELOG = "changelog_{silo}"
_QUARANTINE = "quarantine_{silo}"
_GOLD_HISTORY = "gold_history"
_GOLD_CONFLICTS = "gold_conflicts"


def _merge(into: dict[str, set], column: str, labels) -> None:
    if labels:
        into.setdefault(column, set()).update(labels)


def classifications_by_table(object_types: dict) -> dict[str, dict[str, list[str]]]:
    """Every table that holds a classified value, and which columns.

    Tables holding NO classified value are absent rather than mapped to
    {} -- the caller clears a stale property on those.
    """
    by_table: dict[str, dict[str, set]] = {}

    for object_type, type_def in object_types.items():
        fields = type_def.get("fields") or {}
        labels_by_field = {name: field_classifications(info) for name, info in fields.items()}
        everything: set[str] = set().union(*labels_by_field.values())
        if not everything:
            continue

        for (silo, table, _id_column, _columns, _types, fields_by_column,
             _standardisation, _expectations, _duplicates) in _targets_for_type(type_def):
            source_labels: dict[str, set] = {}
            for column, field_name in fields_by_column.items():
                _merge(source_labels, column, labels_by_field.get(field_name))
            if not source_labels:
                continue
            for identifier in (f"bronze_{silo}.{table}", f"{silo}.{table}",
                               f"{_CHANGELOG.format(silo=silo)}.{table}"):
                for column, labels in source_labels.items():
                    _merge(by_table.setdefault(identifier, {}), column, labels)
            _merge(by_table.setdefault(f"{_QUARANTINE.format(silo=silo)}.{table}", {}),
                   "value", set().union(*source_labels.values()))

        gold = by_table.setdefault(f"{GOLD_NAMESPACE}.{object_type}", {})
        for field_name, field_labels in labels_by_field.items():
            info = fields[field_name]
            # NOT A GOLD COLUMN: a reverse link is computed on read, so
            # there is nothing in gold to label. Same rule gold._arrow
            # uses to choose the columns it writes.
            if info.get("type") == "link" and is_reverse_link(info):
                continue
            _merge(gold, field_name, field_labels)
        _merge(by_table.setdefault(f"{_GOLD_HISTORY}.{object_type}", {}), "values", everything)
        conflicts = by_table.setdefault(f"{_GOLD_CONFLICTS}.{object_type}", {})
        _merge(conflicts, "chosen", everything)
        _merge(conflicts, "losing", everything)

    return {
        identifier: {column: sorted(labels) for column, labels in sorted(columns.items())}
        for identifier, columns in by_table.items() if columns
    }


def recorded_classifications(table) -> dict[str, list[str]]:
    """What a table says it holds. Empty when it says nothing."""
    raw = table.properties.get(CLASSIFICATIONS_PROPERTY)
    if not raw:
        return {}
    try:
        recorded = json.loads(raw)
    except ValueError:
        return {}
    return recorded if isinstance(recorded, dict) else {}


def record_classifications(catalog, object_types: dict) -> list[str]:
    """Writes each table's labels where they differ. Returns the tables
    changed, so the sync can say what it did.

    EVERY TABLE IN THE CATALOG IS VISITED, not only those with labels,
    because a label REMOVED from the ontology must come off too: a
    property left behind would say a column holds PII after the
    ontology stopped saying so -- or, worse, the reverse would never be
    noticed when it was added back.

    PER TABLE, NEVER FATAL. One table that cannot take a property must
    not cost the others theirs, and a sync that published gold must not
    be reported as failed over metadata.
    """
    wanted = classifications_by_table(object_types)
    changed = []
    for namespace in catalog.list_namespaces():
        for identifier_parts in catalog.list_tables(namespace):
            identifier = ".".join(identifier_parts)
            target = wanted.get(identifier, {})
            try:
                table = catalog.load_table(identifier)
                if recorded_classifications(table) == target:
                    continue
                with table.transaction() as tx:
                    if target:
                        tx.set_properties({CLASSIFICATIONS_PROPERTY:
                                           json.dumps(target, sort_keys=True)})
                    else:
                        tx.remove_properties(CLASSIFICATIONS_PROPERTY)
                changed.append(identifier)
            except Exception as e:  # noqa: BLE001 - see the docstring
                logger.warning(f"could not record classifications on {identifier}: {e}")
    return changed
