"""What your data holds that you may not have declared (ZOO-08,
ZOO-09, ZOO-10, ZOO-23; PR001-R25).

    python -m scripts.suggest_declarations

WHY THIS EXISTS RATHER THAN A CLEANING RULE. Four of the dirty-data
findings in this audit turned out to be ALREADY DECLARABLE:

    "N/A" kept as a real value          -> standardise: null_if
    "999-999-9999" kept                 -> standardise: null_if
    1900-01-01 parsed as a real date    -> constraints: min
    2099-01-01 accepted with no range   -> constraints: max

Nothing was missing from the mechanism. What was missing is that
NOBODY DECLARES `null_if: ["N/A"]` FOR A VALUE THEY DO NOT KNOW IS
THERE. A rule you have to already suspect is a rule for the person who
does not need it.

SUGGEST, NEVER INFER. This reads bronze -- the raw copy, before any
declared cleaning -- counts values that look like disguised absences
or implausible dates, and prints the exact YAML to declare. It writes
nothing and changes nothing. The 2024 VLDB evaluation of twelve
automatic repair algorithms found most introduce more errors than they
remove, which is the argument for stopping at a suggestion.

WHY BRONZE AND NOT SILVER: silver has already had the declared rules
applied, so a value a deployment ALREADY handles would be reported
again by a report reading silver, and the operator would chase
something they had fixed.

A SUGGESTION IS NOT A FINDING. "N/A" in a free-text notes column may
be exactly what somebody typed and meant. The report says how often
and in which column; the decision stays with the person who knows the
business.
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from core.deployment_loader import resolve_runtime_paths
from core.mirror.catalog import open_mirror_catalog

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
# wording of a message. An earlier version decided which YAML to print
# by looking for the word "date" in the explanation, so rephrasing a
# sentence would have silently changed the advice.
ABSENCE = "absence"      # a specific value meaning "there was none"
RANGE = "range"          # a date outside anything the business has


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


def _suggestion(column: str, values: dict) -> str:
    """The YAML to declare, for the values found in this column."""
    absences = sorted(v for v, (_, kind, _why) in values.items()
                      if kind == ABSENCE)
    dates = sorted(v for v, (_, kind, _why) in values.items() if kind == RANGE)
    lines = [f"  {column}:"]
    if absences:
        rendered = ", ".join(f'"{value}"' for value in absences)
        lines.append("    standardise:")
        lines.append(f"      null_if: [{rendered}]")
    if dates:
        lines.append("    constraints:")
        lines.append('      min: "1970-01-01"   # adjust to your business')
        lines.append('      max: "2030-12-31"')
        lines.append("    on_violation: quarantine")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50_000, metavar="ROWS",
                        help="how many rows per table to read (default 50000)")
    args = parser.parse_args()

    paths = resolve_runtime_paths()
    mirror = Path(paths.data_dir) / "mirror"
    if not mirror.exists():
        print("No mirror yet. Run a sync first.", file=sys.stderr)
        return 1
    catalog = open_mirror_catalog(mirror)

    reported = 0
    for namespace in sorted(catalog.list_namespaces()):
        if not namespace[0].startswith("bronze_"):
            continue
        for identifier in sorted(catalog.list_tables(namespace)):
            name = ".".join(identifier)
            table = catalog.load_table(name)
            rows = table.scan(limit=args.limit).to_arrow().to_pylist()
            columns = [f.name for f in table.schema().fields
                       if not f.name.startswith("_")]
            found = suspicious_values(rows, columns)
            if not found:
                continue
            reported += 1
            print(f"\n{name} ({len(rows)} rows read)")
            for column, values in found.items():
                for value, (count, _kind, why) in values.items():
                    print(f"  {column}: {value!r} x{count} -- {why}")
            print("\n  To treat these as absent, add to "
                  "ontology_schema.yaml under this type's `fields`:")
            for column, values in found.items():
                print(_suggestion(column, values))

    if reported == 0:
        print("Nothing suspicious found. That is not a guarantee: this "
              "looks for values that ANNOUNCE themselves, not for wrong "
              "ones.")
    else:
        print("\nNOTHING HAS BEEN CHANGED. These are suggestions. A value "
              "listed here may be exactly what somebody meant to type -- "
              "'N/A' in a free-text note is a sentence, not a gap.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
