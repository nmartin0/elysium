"""Which ontology fields a source table's columns probably are (R55).

    python -m scripts.suggest_bindings crm_sql contacts
    python -m scripts.suggest_bindings crm_sql contacts --type Customer

For a table the ontology does not read yet: per column, the likeliest
fields by NAME and by VALUES already in gold, kept as two numbers; which
column looks like a type's id; and, with --type, the additional_storage
block to start from. core/mirror/binding_suggestions.py has the method.

IT CHANGES NOTHING. The silo must be configured (config.yaml) so it can
be read; the binding is yours to write.
"""

import argparse
import sys
from pathlib import Path

from core.deployment_loader import build_live_read_adapters, load_deployment, resolve_runtime_paths
from core.mirror.binding_suggestions import suggest, yaml_skeleton


def _gold_rows(config, data_dir: Path, limit: int):
    from core.mirror.catalog import open_mirror_catalog
    from core.ontology.gold_view import GOLD_NAMESPACE

    mirror = data_dir / "mirror"
    catalog = open_mirror_catalog(mirror, dict(config.mirror_storage)) if mirror.exists() else None

    def rows_for(object_type: str):
        if catalog is None:
            return None
        try:
            return catalog.load_table(f"{GOLD_NAMESPACE}.{object_type}").scan(
                limit=limit).to_arrow().to_pylist()
        except Exception:  # noqa: BLE001 - not published yet
            return None
    return rows_for


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("silo", help="a silo named in config.yaml")
    parser.add_argument("table", help="the table to look at")
    parser.add_argument("--type", dest="only_type", help="compare against this object type only")
    parser.add_argument("--limit", type=int, default=10_000, metavar="ROWS",
                        help="how many rows to read from each side (default 10000)")
    args = parser.parse_args()

    paths = resolve_runtime_paths()
    config = load_deployment(paths.config_dir)
    adapters = build_live_read_adapters(paths, config)
    if args.silo not in adapters:
        print(f"No silo {args.silo!r}. Configured: {', '.join(sorted(adapters)) or 'none'}.",
              file=sys.stderr)
        return 1
    adapter = adapters[args.silo]
    columns = sorted(adapter.columns_present(args.table))
    if not columns:
        print(f"{args.silo}.{args.table} has no columns this adapter can read.", file=sys.stderr)
        return 1
    rows: list[dict] = []
    for batch in adapter.iter_all_rows(args.table, columns, {}, batch_size=args.limit):
        rows.extend(batch)
        if len(rows) >= args.limit:
            break
    rows = rows[:args.limit]

    by_column, ids = suggest(config.schema, rows, _gold_rows(config, Path(paths.data_dir),
                                                              args.limit), args.only_type)
    print(f"{args.silo}.{args.table}: {len(rows)} rows read, {len(columns)} columns\n")
    for column, matches in by_column.items():
        if not matches:
            print(f"  {column}: nothing likely")
            continue
        described = "; ".join(
            f"{m.object_type}.{m.field} (name {m.name_score:.0%}, values "
            f"{'n/a' if m.value_share is None else format(m.value_share, '.0%')})"
            for m in matches)
        print(f"  {column}: {described}")
    if ids:
        print("\nLooks like an id:")
        for match in ids:
            print(f"  {match.column} -- {match.share:.0%} of its values are {match.object_type} ids")

    if args.only_type:
        chosen = {matches[0].field: column for column, matches in by_column.items()
                  if matches and matches[0].object_type == args.only_type}
        id_column = next((m.column for m in ids if m.object_type == args.only_type), None)
        print("\nA starting point, to edit -- binding a field here MOVES it to this table, so "
              "keep only the fields this table should be the source of:\n")
        print(yaml_skeleton(args.only_type, f"{args.silo}_{args.table}", args.silo, args.table,
                            id_column, chosen))
    print("\nNOTHING HAS BEEN CHANGED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
