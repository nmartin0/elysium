"""Which source tends to be right when two disagree, with the counts (R60).

    python -m scripts.source_track_record            # every type
    python -m scripts.source_track_record Customer

For each field and pair of sources: how many disagreements have ended,
and whose value both sources ended up holding. The Provenance panel
shows only a rounded share, from 10 ended disagreements; this shows the
counts, because it runs on the server, for the operator.

EVIDENCE ONLY. It changes nothing. If a source you prefer usually turns
out to be the one that moved, that is a reason to look at `prefer` --
yours to change, in ontology_schema.yaml. core/mirror/source_record.py
has the method and what it cannot tell you.
"""

import argparse
import sys
from pathlib import Path

from core.deployment_loader import load_deployment, resolve_runtime_paths
from core.mirror.source_record import SHOWN_FROM, SourceRecordStore


def report(store: SourceRecordStore, object_types: list[str]) -> str:
    lines = []
    for object_type in object_types:
        records = store.track_records(object_type)
        if not records:
            continue
        lines.append(f"{object_type}:")
        for (field_name, _), record in sorted(records.items(), key=lambda item: item[0][0]):
            first, second = record.sources
            held = ", ".join(f"{name}'s value held {record.held.get(name, 0)}"
                             for name in (first, second))
            leader, share = record.leader()
            shown = record.shown()
            seen = (f"panel shows {shown['source']} about {shown['about_percent']}%"
                    if shown else f"not on the panel until {SHOWN_FROM} have ended")
            lines.append(f"  {field_name}, {first} vs {second}: {record.total} ended; {held}. "
                         f"{leader} {share:.0%}; {seen}.")
    return "\n".join(lines) if lines else "No disagreement between sources has ended yet."


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("object_type", nargs="?")
    args = parser.parse_args(argv)
    paths = resolve_runtime_paths()
    config = load_deployment(paths.config_dir)
    types = sorted(config.schema or {})
    if args.object_type is not None:
        if args.object_type not in types:
            print(f"No object type {args.object_type!r}.", file=sys.stderr)
            return 1
        types = [args.object_type]
    path = Path(paths.data_dir) / "source_record.db"
    if not path.exists():
        print("No disagreement between sources has ended yet.")
    else:
        print(report(SourceRecordStore(path), types))
    print("\nNOTHING HAS BEEN CHANGED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
