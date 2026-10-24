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
or implausible dates, and prints the exact YAML to declare. It changes
no data and no configuration; since R31 it also records what it found
for review (System -> Server -> Cleaning), so a person's dismissal is remembered. The 2024 VLDB evaluation of twelve
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
import sys
from pathlib import Path

from core.deployment_loader import resolve_runtime_paths
from core.mirror.catalog import open_mirror_catalog
from core.mirror.rule_suggestion_scan import (  # noqa: F401 - re-exported for its tests
    DISGUISED_ABSENCES,
    PLACEHOLDER_PATTERNS,
    SENTINEL_DATES,
    _looks_absent,
    suspicious_values,
)
from core.rule_suggestions import ABSENCE, RANGE  # noqa: F401 - re-exported


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

    # AND REMEMBERED FOR REVIEW (R31): the findings on DECLARED fields go
    # to System -> Server -> Cleaning, where a person accepts or dismisses each one
    # and a dismissal is never raised again. The report above still
    # covers every bronze column, declared or not.
    from core.deployment_loader import load_deployment
    from core.mirror.rule_suggestion_scan import refresh
    from core.rule_suggestions import RuleSuggestionStore

    outcome = refresh(catalog, load_deployment(paths.config_dir).schema,
                      RuleSuggestionStore(Path(paths.data_dir) / "rule_suggestions.db"),
                      args.limit)
    print(f"\nFor review in System -> Server -> Cleaning: {outcome['new']} new, {outcome['updated']} "
          f"still open, {outcome['declared']} already declared, {outcome['kept_dismissed']} "
          f"dismissed earlier and not raised again.")

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
