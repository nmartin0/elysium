#!/usr/bin/env python3
"""
embedding_bench.py  (how fast this machine embeds, before relying on it)

    python -m scripts.embedding_bench SupportTicket
    python -m scripts.embedding_bench SupportTicket --sample 64

Embeds a sample of a type's published rows with the deployment's
`llm.embedding_model`, and says how long the first call took (the model
loading), how many rows a minute it then managed, and so how long a
first pass over the whole table would take -- in one sync, or spread
over several at `llm.embedding_budget_seconds` each.

NOTHING IS STORED. It reads gold and the model, and writes nothing: the
sync is what embeds for real.

WHY IT EXISTS. Embedding throughput depends on the model, the CPU and
the length of the text, and none of those can be measured anywhere but
the machine that will run it. A first pass that takes ten minutes and
one that takes ten hours need different plans, and the difference
should be known before a large table is declared.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.deployment_loader import (  # noqa: E402
    build_embedder,
    load_deployment_bundle,
    resolve_runtime_paths,
)
from core.embeddings import BATCH, text_of, unit  # noqa: E402
from core.mirror.catalog import open_mirror_catalog  # noqa: E402
from core.ontology.gold_view import GOLD_NAMESPACE  # noqa: E402
from core.ontology.semantic_search import semantic_search_of  # noqa: E402


def _duration(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} seconds"
    if seconds < 90 * 60:
        return f"{seconds / 60:.0f} minutes"
    return f"{seconds / 3600:.1f} hours"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("object_type")
    parser.add_argument("--sample", type=int, default=32,
                        help=f"rows to embed (default 32, in batches of {BATCH})")
    args = parser.parse_args(argv)

    paths = resolve_runtime_paths()
    config, _mediator, _writers = load_deployment_bundle(paths.config_dir, paths.data_dir,
                                                         paths.log_dir)
    type_def = (config.schema or {}).get(args.object_type)
    search = semantic_search_of(type_def or {})
    if search is None:
        print(f"{args.object_type} does not declare semantic_search. Add "
              f"`semantic_search: {{from: [fields]}}` to it in ontology_schema.yaml first.",
              file=sys.stderr)
        return 1
    embedder = build_embedder(config)
    catalog = open_mirror_catalog(Path(paths.data_dir) / "mirror", dict(config.mirror_storage))
    try:
        rows = catalog.load_table(f"{GOLD_NAMESPACE}.{args.object_type}").scan(
            selected_fields=tuple(search.inputs)).to_arrow().to_pylist()
    except Exception as e:  # noqa: BLE001 - said, not raised
        print(f"Could not read gold for {args.object_type} ({type(e).__name__}: {e}). Run a "
              f"sync first.", file=sys.stderr)
        return 1
    texts = [text for row in rows if (text := text_of(row, search.inputs))]
    if not texts:
        print(f"{args.object_type} has no rows with text in {', '.join(search.inputs)}.")
        return 1
    sample = texts[:max(1, args.sample)]
    print(f"{args.object_type}: {len(texts)} rows with text; embedding {len(sample)} with "
          f"{config.embedding_model} ({embedder.version()})")

    started = time.monotonic()
    first = embedder.embed(sample[:1])
    loaded = time.monotonic() - started
    dims = unit(first[0]).size
    print(f"  first call (includes loading the model): {loaded:.1f} s; {dims} numbers per row")

    started = time.monotonic()
    done = 0
    for start in range(0, len(sample), BATCH):
        batch = sample[start:start + BATCH]
        embedder.embed(batch)
        done += len(batch)
    elapsed = max(time.monotonic() - started, 1e-6)
    per_minute = done / elapsed * 60
    average = sum(len(text) for text in sample) / len(sample)
    print(f"  then {done} rows in {elapsed:.1f} s: about {per_minute:,.0f} rows a minute "
          f"(average {average:,.0f} characters each)")

    whole = len(texts) / per_minute * 60
    budget = config.embedding_budget_seconds
    syncs = max(1, -(-whole // budget))
    print(f"\nA first pass over all {len(texts)} rows: about {_duration(whole)}.")
    print(f"At llm.embedding_budget_seconds = {budget:g}, that is {int(syncs)} sync(s); after "
          f"that, each sync embeds only rows whose text changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
