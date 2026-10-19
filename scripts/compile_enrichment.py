#!/usr/bin/env python3
"""
compile_enrichment.py  (a model writes rules for one enriched field)

    python -m scripts.compile_enrichment SupportTicket.topic
    python -m scripts.compile_enrichment SupportTicket.topic --sample 30 --candidates 3

Reads the field's inputs from published gold, asks the deployment's model
to answer the field's question for a sample of rows, asks it for
candidate rule sets from half of those, keeps the best, scores it on the
half it never saw, and PROPOSES it. Nothing is applied: approve or reject
it in the Inbox's Enrichment tab, and the next sync fills the field.

SLOW, AND SAYS SO. A model call takes minutes on a CPU: a sample of 20 is
20 calls plus one per candidate. Labels are cached, so a second run --
with more candidates, say -- re-asks nothing it already has.

ONE COMPARTMENT AT A TIME. The rules a model writes are made of words
from the rows it was shown, and the person approving them must be cleared
for those rows -- R61's rule for merge review, applied here. MAC is one
value per person, so nobody can see every region: the sample is drawn
from ONE security compartment (--compartment, required when there is more
than one), recorded with the recipe, and only someone in that compartment
may see or decide it. The approved rules then run on every row; other
compartments see the values, never the words.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.agent.enrichment_compiler import PROMPT_VERSION, UNUSABLE, compile_recipe  # noqa: E402
from core.deployment_loader import (  # noqa: E402
    build_llm_adapter,
    load_deployment_bundle,
    resolve_runtime_paths,
)
from core.enrichment_recipes import EnrichmentLabelCache, EnrichmentRecipeStore  # noqa: E402
from core.mirror.catalog import open_mirror_catalog  # noqa: E402
from core.ontology.enriched_fields import (  # noqa: E402
    declaration_hash,
    describe_recipe,
    enrichment_of,
)
from core.ontology.gold_view import GOLD_NAMESPACE  # noqa: E402
from core.ontology.unrestricted import as_stored_compartment  # noqa: E402


def _gold_rows(paths, config, object_type: str, columns: list[str]) -> list[dict]:
    catalog = open_mirror_catalog(Path(paths.data_dir) / "mirror", dict(config.mirror_storage))
    table = catalog.load_table(f"{GOLD_NAMESPACE}.{object_type}")
    return table.scan(selected_fields=tuple(columns)).to_arrow().to_pylist()


def _percent(value) -> str:
    return "--" if value is None else f"{value:.0%}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("field", metavar="Type.field")
    parser.add_argument("--sample", type=int, default=20,
                        help="rows the model answers directly (default 20; half write the "
                             "rules, half judge them)")
    parser.add_argument("--candidates", type=int, default=3,
                        help="rule sets to ask for (default 3)")
    parser.add_argument("--seed", type=int, default=0, help="which rows are sampled")
    parser.add_argument("--compartment", metavar="VALUE",
                        help="the security value to sample from (required when the type's rows "
                             "have more than one); only someone with this value may approve")
    args = parser.parse_args()

    object_type, _, field_name = args.field.partition(".")
    paths = resolve_runtime_paths()
    config, mediator, _writers = load_deployment_bundle(paths.config_dir, paths.data_dir,
                                                        paths.log_dir)
    field = ((config.schema.get(object_type) or {}).get("fields") or {}).get(field_name)
    enrichment = enrichment_of(field or {})
    if enrichment is None:
        print(f"{args.field} is not an enriched field. Declare it with `enrich: {{from, "
              f"instruction}}` and either `choices` or `extract: true` in ontology_schema.yaml "
              f"first.", file=sys.stderr)
        return 1

    id_field = config.schema[object_type]["id_field"]
    try:
        rows = _gold_rows(paths, config, object_type, [id_field, *enrichment.inputs])
    except Exception as e:  # noqa: BLE001 - said, not raised
        print(f"Could not read gold for {object_type} ({type(e).__name__}: {e}). "
              f"Run a sync first.", file=sys.stderr)
        return 1
    # EACH ROW'S COMPARTMENT AS THE READ PATH RESOLVES IT -- its own
    # field, or followed through a via_field chain -- so "cleared for
    # these rows" means what an ordinary read would have decided.
    for row in rows:
        row["__compartment"] = as_stored_compartment(
            mediator.security_value_of(object_type, row.get(id_field)))
    compartments: dict = {}
    for row in rows:
        compartments[row["__compartment"]] = compartments.get(row["__compartment"], 0) + 1
    compartment = args.compartment
    if compartment is None:
        if len(compartments) > 1:
            listed = ", ".join(f"{value} ({count} rows)" for value, count in
                               sorted(compartments.items(), key=lambda item: str(item[0])))
            print(f"{object_type}'s rows are in {len(compartments)} security compartments: "
                  f"{listed}. Choose one with --compartment; only someone in it may approve "
                  f"what it proposes.", file=sys.stderr)
            return 1
        compartment = next(iter(compartments), None)
    rows = [row for row in rows if row["__compartment"] == compartment]

    model = config.synthesis_model
    digest = declaration_hash(object_type, field_name, enrichment)
    data_dir = Path(paths.data_dir)
    cache = EnrichmentLabelCache(data_dir / "enrichment_recipes.db", digest, model, PROMPT_VERSION)
    started = time.monotonic()
    print(f"{args.field}: {enrichment.instruction}")
    print(f"  {len(rows)} rows in compartment {compartment!r}; sampling "
          f"{min(args.sample, len(rows))}, "
          f"{args.candidates} candidate rule set(s), model {model}")

    def cached(key):
        answer = cache.get(key)
        return UNUSABLE if answer is cache.MISSING else answer

    compiled = compile_recipe(
        build_llm_adapter(config, model), model, enrichment, rows,
        sample_size=args.sample, candidates=args.candidates, seed=args.seed,
        cached_label=cached, remember_label=cache.put,
        progress=lambda step: print(f"  {step}  [{(time.monotonic() - started) / 60:.1f} min]",
                                    flush=True),
        # AS THE SYNC WILL TYPE IT: the locale of the type's silo (DEP-1).
        locale=config.source_locales.get((config.schema[object_type].get("storage") or {})
                                         .get("silo")))

    for reason in compiled.refused:
        print(f"  refused: {reason}")
    if compiled.rules is None:
        print("\nNOTHING PROPOSED. See the reasons above; a larger --sample usually helps.")
        return 1

    evaluation = compiled.evaluation
    held = evaluation["held_out"]
    rule_sets = describe_recipe(compiled.rules)
    if len(rule_sets) == 1:
        print("\nThe rules:")
    else:
        print(f"\n{len(rule_sets)} rule sets, which vote -- each answering set adds its weight to "
              f"its value; the heaviest wins, and a tie is left empty:")
    for index, rule_set in enumerate(rule_sets, start=1):
        if rule_set["weight"] is not None:
            print(f"  Set {index}, weight {rule_set['weight']}:")
        for number, line in enumerate(rule_set["rules"], start=1):
            print(f"  {number}. {line}")
    print(f"\nOn {held['rows']} rows they were NOT written from: answered "
          f"{_percent(held['coverage'])}, and agreed with the model on "
          f"{_percent(held['agreement'])} of those.")
    if not evaluation["enough_to_judge"]:
        print("  That is too few rows to judge by; a larger --sample would say more.")

    recipe_id = EnrichmentRecipeStore(data_dir / "enrichment_recipes.db").propose(
        object_type, field_name, digest, compiled.rules, evaluation,
        {**compiled.provenance, "compartment": compartment})
    print(f"\nPROPOSED as {recipe_id}. Nothing changes until someone approves it in the Inbox "
          f"(Enrichment); the next sync then fills {args.field}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
