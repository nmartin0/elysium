"""How well the matcher finds a type's duplicates, measured (R59).

    python -m scripts.evaluate_matching Customer --synthetic 40
    python -m scripts.evaluate_matching Customer --labels pairs.csv
    python -m scripts.evaluate_matching Customer --decisions

Reads the type's silver tables -- the rows the sync hands the matcher --
scores every pair the matcher compares, and prints precision and recall
at each score it produces, with 95% intervals.

  --synthetic N   copy N real rows with seeded typos, blanks and
                  initials; the only source that measures RECALL.
  --labels FILE   a CSV of pairs: left,right,is_match (or Splink's
                  unique_id_l,unique_id_r,clerical_match_score). Ids as
                  the matcher names them: primary:<id> or <storage>:<id>.
  --decisions     what reviewers approved and rejected. Precision only:
                  nobody decided the pairs the matcher never proposed.

IT CHANGES NOTHING: no proposal is stored and no setting is touched.
core/mirror/match_evaluation.py has the method and its precedent.
"""

import argparse
import csv
import sys
from pathlib import Path

from core.deployment_loader import load_deployment, resolve_runtime_paths
from core.mirror.match_evaluation import (
    Evaluation,
    evaluate,
    labels_from_pairs,
    synthetic_duplicates,
)
from core.mirror.matching import SplinkMatcher, settings_for


def _silver_rows(config, data_dir: Path, type_def: dict) -> dict:
    from core.mirror.catalog import open_mirror_catalog

    catalog = open_mirror_catalog(data_dir / "mirror", dict(config.mirror_storage))

    def read(block: dict) -> list[dict]:
        identifier = f"{block.get('silo')}.{block.get('table')}"
        return catalog.load_table(identifier).scan().to_arrow().to_pylist()

    rows = {None: read(type_def["storage"])}
    for name, block in (type_def.get("additional_storage") or {}).items():
        rows[name] = read(block)
    return rows


def _labels_file(path: Path):
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        if {"left", "right", "is_match"} <= fields:
            names = ("left", "right", "is_match")
        elif {"unique_id_l", "unique_id_r", "clerical_match_score"} <= fields:
            names = ("unique_id_l", "unique_id_r", "clerical_match_score")
        else:
            raise ValueError(
                f"{path} needs columns left,right,is_match or "
                f"unique_id_l,unique_id_r,clerical_match_score; it has {sorted(fields)}.")
        rows = []
        for line in reader:
            value = line[names[2]].strip().lower()
            is_match = value in ("1", "true", "yes", "y") or (
                _number(value) is not None and _number(value) >= 0.5)  # Splink's default
            rows.append((line[names[0]].strip(), line[names[1]].strip(), is_match))
    return labels_from_pairs(rows, source=f"{len(rows)} labelled pairs from {path.name}")


def _number(text: str):
    try:
        return float(text)
    except ValueError:
        return None


def _decision_labels(data_dir: Path, object_type: str):
    from core.identity_decisions import APPROVED, REJECTED, MergeDecisionStore

    store = MergeDecisionStore(data_dir / "identity_decisions.db")
    decided = [p for p in store.proposals(object_type) if p.decision in (APPROVED, REJECTED)]
    return labels_from_pairs(
        ((p.left_id, p.right_id, p.decision == APPROVED) for p in decided),
        source=f"{len(decided)} reviewer decisions")


def _percent(value) -> str:
    return "  n/a" if value is None else f"{value:5.0%}"


def _interval(bounds) -> str:
    return "" if bounds is None else f"({bounds[0]:.0%}-{bounds[1]:.0%})"


def report(evaluation: Evaluation) -> str:
    lines = [f"Labels: {evaluation.source}."]
    if evaluation.exhaustive:
        lines.append(
            f"True matches: {evaluation.labelled_matches}; blocking compared "
            f"{evaluation.compared_matches} of them"
            + ("" if evaluation.pairs_completeness is None
               else f" ({evaluation.pairs_completeness:.0%})")
            + ". One never compared cannot be found at any threshold.")
    else:
        lines.append("RECALL IS NOT MEASURABLE from these labels: they cover only pairs "
                     "someone chose to label, so a match the matcher missed has no label.")
    lines.append("")
    lines.append(f"{'score >=':>9}  {'found':>5}  {'wrong':>5}  {'missed':>6}  "
                 f"{'unlabelled':>10}  {'precision':>20}  {'recall':>20}")
    for row in evaluation.rows:
        missed = "" if row.false_negatives is None else str(row.false_negatives)
        lines.append(
            f"{row.threshold:9.4f}  {row.true_positives:5d}  {row.false_positives:5d}  "
            f"{missed:>6}  {row.unlabelled:10d}  "
            f"{_percent(row.precision):>6} {_interval(row.precision_interval):>13}  "
            f"{_percent(row.recall):>6} {_interval(row.recall_interval):>13}"
            + (f"   <- {row.declared_as}" if row.declared_as else ""))
    if not evaluation.rows:
        lines.append("  (the matcher compared no pairs)")
    if evaluation.errors_at is not None:
        lines.append("")
        lines.append(f"Errors at {evaluation.errors_at:g}:" if evaluation.errors
                     else f"No errors at {evaluation.errors_at:g}.")
        for error in evaluation.errors:
            score = "never compared" if error.score is None else f"score {error.score:.4f}"
            agreed = ", ".join(
                f"{name} {'agrees' if v else 'differs' if v is False else 'uncompared'}"
                for name, v in sorted(error.agreement.items()))
            lines.append(f"  {error.kind}: {error.left_id} ~ {error.right_id}, {score}"
                         + (f"; {agreed}" if agreed else ""))
            if error.note:
                lines.append(f"      {error.note}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("object_type")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--synthetic", type=int, metavar="N")
    source.add_argument("--labels", type=Path, metavar="FILE")
    source.add_argument("--decisions", action="store_true")
    parser.add_argument("--rate", type=float, default=0.3,
                        help="with --synthetic: chance each compared field is damaged (0.3)")
    parser.add_argument("--seed", type=int, default=0, help="with --synthetic (0)")
    args = parser.parse_args(argv)

    paths = resolve_runtime_paths()
    config = load_deployment(paths.config_dir)
    type_def = (config.schema or {}).get(args.object_type)
    if type_def is None:
        print(f"No object type {args.object_type!r}.", file=sys.stderr)
        return 1
    settings = settings_for(type_def)
    if settings is None:
        print(f"{args.object_type} declares no identity.probabilistic block, so there is "
              f"no matcher to evaluate.", file=sys.stderr)
        return 1
    data_dir = Path(paths.data_dir)
    rows = _silver_rows(config, data_dir, type_def)
    if args.synthetic is not None:
        rows, labels = synthetic_duplicates(type_def, rows, settings.compare, args.synthetic,
                                            rate=args.rate, seed=args.seed)
    elif args.labels is not None:
        labels = _labels_file(args.labels)
    else:
        labels = _decision_labels(data_dir, args.object_type)

    candidates = SplinkMatcher().candidates(type_def, rows, at_least=0.0)
    evaluation = evaluate(
        candidates, labels,
        declared={"review_above": settings.review_above,
                  "auto_propose_above": settings.auto_propose_above},
        errors_at=settings.review_above)
    print(f"{args.object_type}: comparing {', '.join(settings.compare)}; "
          f"blocking on {', '.join(settings.block_on or settings.compare[:1])}.")
    print(report(evaluation))
    print("\nNOTHING HAS BEEN CHANGED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
