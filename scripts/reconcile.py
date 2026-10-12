"""Reconcile gold against the source, read fresh (R8).

    python -m scripts.reconcile

Reads every reconcilable type's source table through the read-only
source adapters -- never the mirror -- and compares it, key by key and
value by value, with the gold publication readers are served. Then the
control totals of every numeric field. See core/mirror/reconcile.py for
what counts as a fault and what does not.

RUN IT JUST AFTER A SYNC for a clean answer. Between syncs, a source
change shows as a difference, because it is one: gold has not seen it
yet. The report prints when the source was read and when each type was
published, so the two cases can be told apart.

EXIT 1 when anything differs that declared standardisation does not
explain, so a cron job or a deploy step can use it without parsing.
"""

import sys

from core.deployment_loader import build_live_read_adapters, load_deployment, resolve_runtime_paths
from core.mirror.catalog import open_mirror_catalog
from core.mirror.gold import published_at
from core.mirror.reconcile import describe, reconcile


def run(paths=None) -> int:
    paths = paths or resolve_runtime_paths()
    config = load_deployment(paths.config_dir)
    catalog = open_mirror_catalog(paths.data_dir / "mirror", dict(config.mirror_storage))
    results = reconcile(catalog, build_live_read_adapters(paths, config), config.schema,
                        published_at(catalog, list(config.schema)))
    for line in describe(results):
        print(line)
    return 0 if all(result.clean or result.skipped for result in results) else 1


if __name__ == "__main__":
    sys.exit(run())
