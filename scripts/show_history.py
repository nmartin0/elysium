"""What changed in a gold table, and when.

    python -m scripts.show_history Customer
    python -m scripts.show_history Customer --id cust_001
    python -m scripts.show_history Customer --since 2026-09-01 --limit 50

THE TABLE EXISTED FOR MONTHS WITH NO READER. Every gold publication
compares the previous rows to the new ones and writes one row per
change into `gold_history.<ObjectType>`; nothing has ever opened it.
This is the smallest thing that makes it visible: no UI, no API, no
front end.

WHY AN OPERATOR COMMAND AND NOT ONLY A ROUTE. The question this
answers -- "what changed in Customer last week, and what did it change
from" -- is asked while something looks wrong, which is exactly when
somebody is at a terminal rather than in a browser. The API route
exists too, for the detail page.

IT APPLIES NO ACCESS CONTROL, like every other script in here. It
reads the lake directly, so running it means you can already read the
lake. The API route is the path that filters per caller.
"""

import argparse
import json
import sys

from core.deployment_loader import load_deployment, resolve_runtime_paths
from core.mirror.catalog import open_mirror_catalog
from core.mirror.gold_history import read_history


def _id_field(schema: dict, object_type: str) -> "str | None":
    """The id field of a type, as the gold view keys it."""
    type_def = (schema or {}).get(object_type) or {}
    return type_def.get("id_field")


def _format(entry: dict, show_values: bool) -> str:
    head = (f"{entry['changed_at']}  {entry['change']:<6} "
            f"{entry['object_id']}")
    if not show_values:
        return head
    values = json.dumps(entry["values"], indent=2, sort_keys=True,
                        default=str)
    indented = "\n".join("      " + line for line in values.splitlines())
    return f"{head}\n{indented}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("object_type", help="e.g. Customer")
    parser.add_argument("--id", dest="object_id", default=None,
                        help="only this object's changes")
    parser.add_argument("--since", default=None,
                        help="ISO date or timestamp; changes at or after it")
    parser.add_argument("--limit", type=int, default=50,
                        help="how many changes to show, newest first")
    parser.add_argument("--values", action="store_true",
                        help="print the row as it stood at each change")
    args = parser.parse_args()

    paths = resolve_runtime_paths()
    catalog = open_mirror_catalog(paths.data_dir / "mirror")

    # THE ID FIELD COMES FROM THE DECLARATION, not from guessing at the
    # history table's columns: the history is keyed by whatever the
    # type declares, and reading it back needs the same answer.
    config = load_deployment(paths.config_dir)
    id_field = _id_field(config.schema, args.object_type)
    if id_field is None:
        declared = ", ".join(sorted(config.schema or {})) or "none"
        print(f"no object type {args.object_type!r} is declared. "
              f"Declared types: {declared}", file=sys.stderr)
        return 1

    entries = read_history(catalog, args.object_type, id_field,
                           object_id=args.object_id, since=args.since,
                           limit=args.limit)
    if not entries:
        # NOT AN ERROR, and the distinction matters: a type published
        # once has no history yet, which is different from a type whose
        # history was lost.
        scope = f" for {args.object_id!r}" if args.object_id else ""
        print(f"no recorded changes for {args.object_type}{scope}. "
              f"A type published only once has no history yet.")
        return 0

    for entry in entries:
        print(_format(entry, args.values))
    print(f"\n{len(entries)} change(s), newest first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
