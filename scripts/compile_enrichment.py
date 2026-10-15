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

Runs SYSTEM-HIGH, as a sync does: it reads every row of the type, and the
values it proposes are published to whoever may read the field and its
inputs. The rules it writes can name only the declared inputs and
conclude only a declared choice (core/ontology/enriched_fields.py).
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
    load_deployment,
    resolve_runtime_paths,
)
from core.enrichment_recipes import EnrichmentLabelCache, EnrichmentRecipeStore  # noqa: E402
from core.mirror.catalog import open_mirror_catalog  # noqa: E402
from core.ontology.enriched_fields import (  # noqa: E402
    declaration_hash,
    describe_rule,
    enrichment_of,
)
from core.ontology.gold_view import GOLD_NAMESPACE  # noqa: E402


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
    args = parser.parse_args()

    object_type, _, field_name = args.field.partition(".")
    paths = resolve_runtime_paths()
    config = load_deployment(paths.config_dir)
    field = ((config.schema.get(object_type) or {}).get("fields") or {}).get(field_name)
    enrichment = enrichment_of(field or {})
    if enrichment is None:
        print(f"{args.field} is not an enriched field. Declare it with `enrich: {{from, "
              f"instruction, choices}}` in ontology_schema.yaml first.", file=sys.stderr)
        return 1

    id_field = config.schema[object_type]["id_field"]
    try:
        rows = _gold_rows(paths, config, object_type, [id_field, *enrichment.inputs])
    except Exception as e:  # noqa: BLE001 - said, not raised
        print(f"Could not read gold for {object_type} ({type(e).__name__}: {e}). "
              f"Run a sync first.", file=sys.stderr)
        return 1

    model = config.synthesis_model
    digest = declaration_hash(object_type, field_name, enrichment)
    data_dir = Path(paths.data_dir)
    cache = EnrichmentLabelCache(data_dir / "enrichment_recipes.db", digest, model, PROMPT_VERSION)
    started = time.monotonic()
    print(f"{args.field}: {enrichment.instruction}")
    print(f"  {len(rows)} rows in gold; sampling {min(args.sample, len(rows))}, "
          f"{args.candidates} candidate rule set(s), model {model}")

    def cached(key):
        answer = cache.get(key)
        return UNUSABLE if answer is cache.MISSING else answer

    compiled = compile_recipe(
        build_llm_adapter(config, model), model, enrichment, rows,
        sample_size=args.sample, candidates=args.candidates, seed=args.seed,
        cached_label=cached, remember_label=cache.put,
        progress=lambda step: print(f"  {step}  [{(time.monotonic() - started) / 60:.1f} min]",
                                    flush=True))

    for reason in compiled.refused:
        print(f"  refused: {reason}")
    if compiled.rules is None:
        print("\nNOTHING PROPOSED. See the reasons above; a larger --sample usually helps.")
        return 1

    evaluation = compiled.evaluation
    held = evaluation["held_out"]
    print("\nThe rules:")
    for number, rule in enumerate(compiled.rules, start=1):
        print(f"  {number}. {describe_rule(rule)}")
    print(f"\nOn {held['rows']} rows they were NOT written from: answered "
          f"{_percent(held['coverage'])}, and agreed with the model on "
          f"{_percent(held['agreement'])} of those.")
    if not evaluation["enough_to_judge"]:
        print("  That is too few rows to judge by; a larger --sample would say more.")

    recipe_id = EnrichmentRecipeStore(data_dir / "enrichment_recipes.db").propose(
        object_type, field_name, digest, compiled.rules, evaluation, compiled.provenance)
    print(f"\nPROPOSED as {recipe_id}. Nothing changes until someone approves it in the Inbox "
          f"(Enrichment); the next sync then fills {args.field}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
