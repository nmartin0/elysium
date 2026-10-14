"""Finding values that announce themselves as absences or impossible
dates, in bronze (ZOO-08, -09, -10, -23; PR001-R25; R31).

Moved here from scripts/suggest_declarations.py so the Admin screen can
run the same scan the command does: one detector, two ways in.

SUGGEST, NEVER INFER. This reads and reports. What a person decides
about a finding is core/rule_suggestions.py's to remember; what the
data says is the schema's to declare.
"""

import re
from collections import Counter

from core.rule_suggestions import ABSENCE, RANGE, suggestion_id

# Values that usually mean "we did not have one" written as though
# they were data. Matched case-insensitively against the WHOLE value,
# because "n/a" is a disguised absence and "N/A-1 connector" is a part
# number.
DISGUISED_ABSENCES = {
    "n/a", "na", "none", "null", "nil", "unknown", "undefined",
    "not applicable", "not available", "no data", "missing", "tbd", "-",
    "?", "??", "???", ".", "--",
}

# Placeholders that are the right SHAPE for their column and cannot be
# a real value.
PLACEHOLDER_PATTERNS = (
    (re.compile(r"^9{3}-9{3}-9{4}$"), "a placeholder telephone number"),
    (re.compile(r"^\(?9{3}\)?[ -]?9{3}[ -]?9{4}$"), "a placeholder telephone number"),
    (re.compile(r"^0{3}-0{2}-0{4}$"), "a placeholder national insurance number"),
    (re.compile(r"^(test|example|dummy|sample)@"), "a placeholder email address"),
    (re.compile(r"^x{3,}$", re.I), "a placeholder"),
    # THREE OR MORE, because "0" is a real quantity and "00" is a
    # plausible code. A test caught this: the first version matched a
    # single zero and would have suggested treating every zero
    # measurement as missing.
    (re.compile(r"^0{3,}$"), "a placeholder"),
)

# Dates that are almost always a sentinel rather than an event.
SENTINEL_DATES = {
    "1900-01-01": "the classic spreadsheet epoch sentinel",
    "1899-12-30": "the Excel epoch",
    "1970-01-01": "the Unix epoch, often meaning 'no date'",
    "0000-00-00": "an impossible date some databases store",
    "9999-12-31": "a far-future sentinel meaning 'never'",
}

_DATE = re.compile(r"^(\d{4})-\d{2}-\d{2}")
IMPLAUSIBLE_BEFORE = 1900
IMPLAUSIBLE_AFTER = 2100


# THE TWO KINDS OF SUGGESTION, named rather than inferred from the
# wording of a message (core/rule_suggestions.ABSENCE and RANGE). An
# earlier version decided which YAML to print by looking for the word
# "date" in the explanation, so rephrasing a sentence would have
# silently changed the advice.


def _looks_absent(value: str) -> "tuple[str, str] | None":
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.lower() in DISGUISED_ABSENCES:
        return ABSENCE, "a word meaning 'no value', stored as a value"
    for pattern, why in PLACEHOLDER_PATTERNS:
        if pattern.match(stripped):
            return ABSENCE, why
    if stripped in SENTINEL_DATES:
        # A KNOWN SENTINEL IS AN ABSENCE, not a range problem: the
        # value is exact and meaningless, so null_if names it directly
        # rather than a range catching it by accident.
        return ABSENCE, SENTINEL_DATES[stripped]
    year = _DATE.match(stripped)
    if year:
        number = int(year.group(1))
        if number < IMPLAUSIBLE_BEFORE:
            return RANGE, f"a date in {number}, before anything this system records"
        if number > IMPLAUSIBLE_AFTER:
            return RANGE, f"a date in {number}, further ahead than any plan"
    return None


def suspicious_values(rows, columns) -> dict:
    """Column -> {value: (count, why)}, for values worth a look."""
    found: dict = {}
    for column in columns:
        counts: Counter = Counter()
        reasons: dict = {}
        for row in rows:
            value = row.get(column)
            if not isinstance(value, str):
                continue
            verdict = _looks_absent(value)
            if verdict is not None:
                counts[value] += 1
                reasons[value] = verdict
        if counts:
            found[column] = {
                value: (count, reasons[value][0], reasons[value][1])
                for value, count in counts.most_common()
            }
    return found




#: How many example dates a range suggestion keeps.
_EXAMPLES = 5


def scan(catalog, schema: dict, limit: int = 50_000) -> list[dict]:
    """Every finding, named by the TYPE and FIELD a person declares the
    rule on -- not the bronze column, which the old report printed and
    the schema does not use.

    An absence is one finding per value; a range is one per field, with
    the dates seen as examples, because its rule (min/max) is per field.
    """
    from core.mirror.sync_targets import _targets_for_type

    findings: list[dict] = []
    for object_type, type_def in sorted((schema or {}).items()):
        for target in _targets_for_type(type_def):
            silo, table, fields_by_column = target[0], target[1], target[5]
            try:
                bronze = catalog.load_table(f"bronze_{silo}.{table}")
            except Exception:  # noqa: BLE001 - not synced yet is not an error here
                continue
            columns = [column for column in fields_by_column
                       if column in {f.name for f in bronze.schema().fields}]
            if not columns:
                continue
            rows = bronze.scan(limit=limit).to_arrow().to_pylist()
            for column, values in suspicious_values(rows, columns).items():
                field = fields_by_column[column]
                dates = []
                for value, (count, kind, why) in values.items():
                    if kind == ABSENCE:
                        findings.append({"object_type": object_type, "field": field,
                                         "kind": ABSENCE, "value": value, "seen": count,
                                         "why": why, "examples": [value]})
                    else:
                        dates.append((value, count))
                if dates:
                    findings.append({
                        "object_type": object_type, "field": field, "kind": RANGE,
                        "value": "", "seen": sum(count for _, count in dates),
                        "why": "dates outside anything the business has",
                        "examples": sorted(value for value, _ in dates)[:_EXAMPLES]})
    return findings


def already_declared(schema: dict, findings: list[dict]) -> set[str]:
    """The findings the schema already handles: the value is in the
    field's null_if, or the field declares a min or max."""
    declared = set()
    for item in findings:
        field = (((schema or {}).get(item["object_type"]) or {}).get("fields") or {}).get(
            item["field"]) or {}
        if item["kind"] == ABSENCE:
            handled = item["value"] in ((field.get("standardise") or {}).get("null_if") or ())
        else:
            constraints = field.get("constraints") or {}
            handled = "min" in constraints or "max" in constraints
        if handled:
            declared.add(suggestion_id(item["object_type"], item["field"], item["kind"],
                                       item["value"]))
    return declared


def yaml_for(object_type: str, field: str, kind: str, values: list[str]) -> str:
    """The exact lines to add to ontology_schema.yaml."""
    lines = ["object_types:", f"  {object_type}:", "    fields:", f"      {field}:"]
    if kind == ABSENCE:
        rendered = ", ".join('"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
                             for value in sorted(values))
        lines += ["        standardise:", f"          null_if: [{rendered}]"]
    else:
        lines += ["        constraints:",
                  '          min: "1970-01-01"   # adjust to your business',
                  '          max: "2030-12-31"',
                  "        on_violation: quarantine"]
    return "\n".join(lines)


def refresh(catalog, schema: dict, store, limit: int = 50_000) -> dict:
    """Scan, and merge what was found into the review queue. What a
    person already dismissed stays dismissed; see RuleSuggestionStore."""
    found = scan(catalog, schema, limit)
    return store.record_scan(found, already_declared(schema, found))
