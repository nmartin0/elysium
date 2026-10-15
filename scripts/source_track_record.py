"""Which source tends to be right when two disagree, with the counts (R60).

    python -m scripts.source_track_record            # every type
    python -m scripts.source_track_record Customer

For each field and pair of sources: how many disagreements have ended,
and whose value both sources ended up holding. And where three or more
sources hold a field: how often each sided with the majority, and which
pairs look like copies (core/mirror/source_vote.py). The Provenance panel
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
        lines.extend(_vote_lines(store, object_type))
        if not records:
            continue
        lines.append(f"{object_type}, disagreements that ended:")
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


def _vote_lines(store: SourceRecordStore, object_type: str) -> list[str]:
    """Where three or more sources hold a field: how often each sided
    with the majority, and which pairs look like copies -- with counts."""
    agreement = store.vote_agreement(object_type)
    copies = store.copying(object_type)
    if not agreement and not copies:
        return []
    lines = [f"{object_type}, voting where three or more sources hold a field:"]
    for (field_name, source), (agreed, total) in sorted(agreement.items()):
        lines.append(f"  {field_name}: {source} sided with the majority on {agreed} of "
                     f"{total} ({agreed / total:.0%}).")
    for pair in copies:
        lines.append(
            f"  {pair['source_a']} and {pair['source_b']} look like copies "
            f"({pair['probability']:.0%}): they share {pair['shared_false']} value(s) the "
            f"majority rejects, {pair['shared_true']} it accepts, and differ on "
            f"{pair['different']}. Counted as one voice.")
    return lines


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
