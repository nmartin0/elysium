"""Columns that look like links nobody declared (R54).

    python -m scripts.suggest_links
    python -m scripts.suggest_links --limit 10000

Reads bronze, and for each column not already a declared link, asks
whether its values are (nearly) all ids of some object type -- an
inclusion dependency, the first step of foreign-key discovery. See
core/mirror/link_discovery.py for the method and its limits.

IT CHANGES NOTHING. A candidate is something to look at: two columns of
small integers are included in each other by accident, so the report
says whether the column is NAMED like its target and how many values
did not match, and the decision -- an ontology change -- stays yours.
"""

import argparse
import sys
from pathlib import Path

from core.deployment_loader import load_deployment, resolve_runtime_paths
from core.mirror.catalog import open_mirror_catalog
from core.mirror.link_discovery import MIN_COVERAGE, bronze_rows, discover


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=50_000, metavar="ROWS",
                        help="how many rows per table to read (default 50000)")
    args = parser.parse_args()

    paths = resolve_runtime_paths()
    mirror = Path(paths.data_dir) / "mirror"
    if not mirror.exists():
        print("No mirror yet. Run a sync first.", file=sys.stderr)
        return 1
    config = load_deployment(paths.config_dir)
    found = discover(config.schema,
                     bronze_rows(open_mirror_catalog(mirror, dict(config.mirror_storage)),
                                 args.limit))
    if not found:
        print(f"No undeclared column has {MIN_COVERAGE:.0%} of its values among some type's "
              f"ids. That is not a guarantee: a link through a renamed or reformatted key "
              f"would not show.")
        return 0
    for candidate in found:
        named = "named like it" if candidate.named_like_target else "NOT named like it"
        field = f" (field {candidate.field})" if candidate.field else " (an undeclared column)"
        print(f"{candidate.object_type}.{candidate.column}{field} -> {candidate.target_type}: "
              f"{candidate.coverage:.1%} of {candidate.distinct} distinct values are "
              f"{candidate.target_type} ids, {candidate.unmatched} are not; {named}")
    print("\nNOTHING HAS BEEN CHANGED. To declare one, give the field `type: link` and "
          "`target: <Type>` in ontology_schema.yaml. A candidate not named like its target is "
          "most often two number columns that happen to overlap.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
