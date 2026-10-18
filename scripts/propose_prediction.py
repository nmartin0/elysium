#!/usr/bin/env python3
"""
propose_prediction.py  (train a predicted field, measure it, propose it)

    python -m scripts.propose_prediction Customer.churn_risk --group-by region
    python -m scripts.propose_prediction Customer.churn_risk --group-by plan --compartment EU

Reads the field's answer and inputs from published gold, holds a fifth
of the known records out, trains on the rest, and measures the model on
the ones it never saw -- against the naive guess, and per value of the
--group-by field, so an average cannot hide a group it fails. Then
PROPOSES it. Nothing is applied: approve or reject it in the Inbox's
Predictions tab, and the next sync trains it again and fills the field.

--group-by IS REQUIRED (the owner, 17 October): every approval sees the
score broken down by a field the approver chose.

ONE COMPARTMENT AT A TIME (the owner, 17 October). A model is shaped by
every record it learns from, so it learns from ONE security compartment
and fills only that compartment's records; only someone in it may see or
decide the proposal. Required when the type's records span more than
one -- propose once per compartment.

FAST: seconds, not minutes. No language model is involved.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.deployment_loader import load_deployment_bundle, resolve_runtime_paths  # noqa: E402
from core.mirror.catalog import open_mirror_catalog  # noqa: E402
from core.ontology.gold_view import GOLD_NAMESPACE  # noqa: E402
from core.ontology.predicted_fields import (  # noqa: E402
    check_group_by,
    declaration_hash,
    prediction_of,
)
from core.prediction_proposals import PredictionProposalStore  # noqa: E402
from core.predictions import SEED, NotLearnable, data_types_of, refusal, train  # noqa: E402


def _gold_rows(paths, config, object_type: str, columns: list[str]) -> list[dict]:
    catalog = open_mirror_catalog(Path(paths.data_dir) / "mirror", dict(config.mirror_storage))
    table = catalog.load_table(f"{GOLD_NAMESPACE}.{object_type}")
    return table.scan(selected_fields=tuple(columns)).to_arrow().to_pylist()


def _number(value) -> str:
    return "--" if value is None else f"{value:.3g}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("field", metavar="Type.field")
    parser.add_argument("--group-by", required=True, metavar="FIELD",
                        help="the field whose values the score is broken down by")
    parser.add_argument("--compartment", metavar="VALUE",
                        help="the security value to learn from (required when the type's records "
                             "have more than one); only someone with this value may approve")
    args = parser.parse_args()

    object_type, _, field_name = args.field.partition(".")
    paths = resolve_runtime_paths()
    config, mediator, _writers = load_deployment_bundle(paths.config_dir, paths.data_dir,
                                                        paths.log_dir)
    type_def = config.schema.get(object_type) or {}
    fields = type_def.get("fields") or {}
    prediction = prediction_of(fields.get(field_name) or {}, fields)
    if prediction is None:
        print(f"{args.field} is not a predicted field. Declare it with `predict: {{of, from}}` "
              f"in ontology_schema.yaml first.", file=sys.stderr)
        return 1
    try:
        check_group_by(object_type, type_def, field_name, prediction, args.group_by)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    id_field = type_def["id_field"]
    columns = list(dict.fromkeys([id_field, prediction.target, *prediction.inputs,
                                  args.group_by]))
    try:
        rows = _gold_rows(paths, config, object_type, columns)
    except Exception as e:  # noqa: BLE001 - said, not raised
        print(f"Could not read gold for {object_type} ({type(e).__name__}: {e}). "
              f"Run a sync first.", file=sys.stderr)
        return 1
    # EACH ROW'S COMPARTMENT AS THE READ PATH RESOLVES IT, as
    # compile_enrichment does: its own field, or through a via_field chain.
    compartments: dict = {}
    for row in rows:
        row["__compartment"] = mediator.security_value_of(object_type, row.get(id_field))
        compartments[row["__compartment"]] = compartments.get(row["__compartment"], 0) + 1
    compartment = args.compartment
    if compartment is None:
        if len(compartments) > 1:
            listed = ", ".join(f"{value} ({count} records)" for value, count in
                               sorted(compartments.items(), key=lambda item: str(item[0])))
            print(f"{object_type}'s records are in {len(compartments)} security compartments: "
                  f"{listed}. Choose one with --compartment; a model learns from one "
                  f"compartment and fills only its records.", file=sys.stderr)
            return 1
        compartment = next(iter(compartments), None)
    elif compartment not in compartments:
        print(f"No {object_type} records are in compartment {compartment!r}.", file=sys.stderr)
        return 1
    rows = [row for row in rows if row["__compartment"] == compartment]

    print(f"{args.field}: {prediction.describe()}, the answer being {prediction.target!r}"
          + (f" = {prediction.chance_of!r}" if prediction.chance_of is not None else ""))
    print(f"  {len(rows)} records in compartment {compartment!r}")
    try:
        trained = train(rows, prediction, data_types_of(fields), group_by=args.group_by)
    except NotLearnable as e:
        print(f"\nNOTHING PROPOSED: {e}.", file=sys.stderr)
        return 1

    evaluation = trained.evaluation
    print(f"\nJudged on {evaluation['judged_on']} known records it did not learn from "
          f"(learned from {evaluation['learned_from']}):")
    print(f"  {evaluation['measure']}: {_number(evaluation['score'])}, against "
          f"{_number(evaluation['naive_score'])} for the naive guess")
    print(f"  skill {evaluation['skill']:.0%} (0% = no better than guessing)")
    print(f"\nBy {args.group_by}:")
    for group in evaluation["groups"]:
        skill = "too few to judge" if group["skill"] is None else f"skill {group['skill']:.0%}"
        print(f"  {group['value']}: {group['records']} records, {skill}")
    print("\nWhat it leans on: " + ", ".join(f"{item['field']} {item['share']:.0%}"
                                             for item in evaluation["important"]))
    if "warning" in evaluation:
        print(f"\nWARNING: {evaluation['warning']}")

    refused = refusal(evaluation)
    if refused:
        print(f"\nNOTHING PROPOSED: {refused}", file=sys.stderr)
        return 1
    import sklearn

    proposal_id = PredictionProposalStore(Path(paths.data_dir) / "prediction_proposals.db").propose(
        object_type, field_name, declaration_hash(object_type, field_name, prediction),
        compartment, evaluation,
        {"library": f"scikit-learn {sklearn.__version__}", "seed": SEED, "records": len(rows)})
    print(f"\nPROPOSED as {proposal_id}. Nothing changes until someone in compartment "
          f"{compartment!r} approves it in the Inbox (Predictions); the next sync then trains "
          f"it again and fills {args.field} where {prediction.target!r} is unknown.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
