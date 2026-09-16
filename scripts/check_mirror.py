"""Checks that the mirror is self-consistent, and says what is not.

WHAT THIS ANSWERS is narrow deliberately: given a warehouse and a
catalog, is what they contain self-consistent? Not "is the data
correct" -- correctness is a property of the SOURCE, and the mirror
cannot know it.

WHY IT EXISTS NOW. Until the changelog, everything in the mirror was
derivable: if it was wrong, delete it and re-sync. The changelog is
not -- a source holds "now" and cannot say what a value used to be --
so the mirror holds something only it holds, and "is it intact" became
a question with consequences.

RUN IT AGAINST A LAKE NOBODY HAS CONFIGURED YET. The ontology argument
is optional, because the most valuable case is a warehouse preserved
through a teardown and inspected before a new Elysium is stood up on
it. The structural checks still run; the ontology-aware ones are
skipped rather than guessed at.

    python -m scripts.check_mirror
    python -m scripts.check_mirror --mirror /path/to/mirror --no-ontology

EXIT CODE 1 ON ANY PROBLEM, so a cron job or a deploy step can use it
without parsing the output.
"""

import argparse
import sys
from pathlib import Path

from pyiceberg.catalog.sql import SqlCatalog

from core.deployment_loader import load_deployment, resolve_runtime_paths
from core.mirror.integrity import check_mirror


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror", type=Path, default=None,
                        help="the mirror directory (default: the deployment's own)")
    parser.add_argument("--no-ontology", action="store_true",
                        help="skip the checks that need a schema, for a lake "
                             "whose Elysium is not configured yet")
    args = parser.parse_args()

    paths = resolve_runtime_paths()
    mirror_dir = args.mirror if args.mirror is not None else paths.data_dir / "mirror"

    if not (mirror_dir / "catalog.db").exists():
        # THE CATALOG IS THE THING THAT MAKES A WAREHOUSE READABLE, so
        # its absence is the most serious finding available and is
        # reported as such rather than as an empty result.
        print(f"No catalog at {mirror_dir / 'catalog.db'}.", file=sys.stderr)
        print(
            "Without it the warehouse is a directory of Parquet nobody can "
            "interpret -- the catalog must be part of any backup.",
            file=sys.stderr,
        )
        return 1

    catalog = SqlCatalog(
        "elysium_mirror",
        uri=f"sqlite:///{mirror_dir / 'catalog.db'}",
        warehouse=f"file://{mirror_dir / 'warehouse'}",
    )

    schema = None
    if not args.no_ontology:
        try:
            schema = load_deployment(paths.config_dir).schema
        except (OSError, ValueError) as e:
            print(f"Could not load the ontology ({e}); running structural "
                  f"checks only.", file=sys.stderr)

    report = check_mirror(catalog, schema, mirror_dir / "warehouse")

    print(f"Checked {report.tables_checked} table(s) in {mirror_dir}.")
    if report.ok:
        print("No problems found.")
        return 0

    print(f"\n{len(report.problems)} problem(s):", file=sys.stderr)
    for problem in report.problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
