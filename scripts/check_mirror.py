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
        # TWO VERY DIFFERENT SITUATIONS LOOK IDENTICAL HERE, and a
        # first version reported both as the alarming one.
        #
        # A catalog missing with NO warehouse beside it means nobody
        # has ever synced -- an ordinary state on a fresh checkout, and
        # telling that person their backup strategy has failed is both
        # wrong and frightening.
        #
        # A catalog missing while the warehouse HOLDS DATA is the
        # serious case: the Parquet is there and nothing can interpret
        # it. Found by running the script on a machine that had never
        # synced, which is exactly the person the wrong message would
        # have reached.
        warehouse = mirror_dir / "warehouse"
        has_data = warehouse.is_dir() and any(warehouse.rglob("*.parquet"))

        if not has_data:
            print(f"No mirror at {mirror_dir}.")
            print("Nothing has been synced yet. Run: python -m scripts.run_sync")
            return 0

        print(f"DATA WITHOUT A CATALOG at {mirror_dir}.", file=sys.stderr)
        print(
            f"{warehouse} holds Parquet files, but {mirror_dir / 'catalog.db'} "
            f"is missing -- so nothing can interpret them. The catalog must be "
            f"part of any backup that includes the warehouse.",
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
