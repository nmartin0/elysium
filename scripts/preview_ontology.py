"""Preview an ontology change against the real sources before it goes live (R20).

    python -m scripts.preview_ontology /path/to/candidate/etc

Builds the WHOLE pipeline -- bronze, silver, gold -- for the candidate
configuration into a scratch mirror, reading the same sources the live
deployment reads, and compares the candidate's gold with the gold
readers are served today: types and properties added or removed, rows
gained or lost, and values that would change, per property. Nothing
live is touched: not the mirror, not a store, not the server.

WHY A SCRATCH MIRROR AND NOT AN ICEBERG BRANCH, which the audit row
named. Gold already publishes through a branch (write-audit-publish),
and that is the right tool for "these ROWS, before readers see them".
It is the wrong tool for an ontology change, because an ontology change
is mostly a SCHEMA change -- a new property, a changed type, a renamed
column -- and an Iceberg schema belongs to the table, not to a branch:
evolving it on a branch evolves it for main. A preview that altered the
live table's schema to show what the change would do would have done
it. So the candidate is built beside the live lake, the way dbt builds
a pull request into its own schema and data-diff compares the two.

THE SOURCES ARE READ, NEVER WRITTEN: the sync uses the read-only
adapters, and a silo whose path is relative to the data directory is
linked into the scratch one rather than copied.

COSTS ONE FULL READ OF EVERY SOURCE TABLE THE CANDIDATE NAMES. On a
large deployment, run it when a sync would run.
"""

import contextlib
import io
import shutil
import sys
import tempfile
from pathlib import Path

from core.deployment_loader import RuntimePaths, load_deployment, resolve_runtime_paths
from core.mirror.catalog import open_mirror_catalog
from core.mirror.gold import _latest_published_snapshot

SAMPLE = 5


def _gold_rows(catalog, object_type: str, id_field: str) -> "dict[str, dict] | None":
    try:
        table = catalog.load_table(f"gold.{object_type}")
    except Exception:  # noqa: BLE001 - no gold for this type is an answer
        return None
    snapshot = _latest_published_snapshot(table)
    if snapshot is None:
        return None
    rows = table.scan(snapshot_id=snapshot).to_arrow().to_pylist()
    return {str(row.get(id_field)): row for row in rows}


def compare(live_catalog, live_schema: dict, preview_catalog, preview_schema: dict) -> list[str]:
    """What the candidate would change, as lines a person reads."""
    lines = []
    for object_type in sorted(set(preview_schema) - set(live_schema)):
        lines.append(f"+ {object_type}: a new type")
    for object_type in sorted(set(live_schema) - set(preview_schema)):
        lines.append(f"- {object_type}: removed -- readers lose every {object_type}")
    for object_type in sorted(set(live_schema) & set(preview_schema)):
        live_fields = set(live_schema[object_type].get("fields") or {})
        new_fields = set(preview_schema[object_type].get("fields") or {})
        id_field = preview_schema[object_type]["id_field"]
        changes = [f"    + property {name}" for name in sorted(new_fields - live_fields)]
        changes += [f"    - property {name}" for name in sorted(live_fields - new_fields)]
        live = _gold_rows(live_catalog, object_type, live_schema[object_type]["id_field"])
        preview = _gold_rows(preview_catalog, object_type, id_field)
        if preview is None:
            changes.append("    NOT BUILT -- see the sync output above for why")
        elif live is not None:
            gained = sorted(set(preview) - set(live))
            lost = sorted(set(live) - set(preview))
            if gained:
                changes.append(f"    {len(gained)} object(s) gained: {', '.join(gained[:SAMPLE])}")
            if lost:
                changes.append(f"    {len(lost)} object(s) lost: {', '.join(lost[:SAMPLE])}")
            for name in sorted(live_fields & new_fields):
                differing = [object_id for object_id in sorted(set(live) & set(preview))
                             if str(live[object_id].get(name)) != str(preview[object_id].get(name))]
                if differing:
                    changes.append(f"    {name}: {len(differing)} value(s) would change -- "
                                   f"{', '.join(differing[:SAMPLE])}")
        if changes:
            lines.append(f"~ {object_type}")
            lines.extend(changes)
        else:
            lines.append(f"= {object_type}: unchanged")
    return lines


def _link_relative_silos(config, live_data_dir: Path, scratch_data_dir: Path) -> None:
    """A silo whose path is relative to the data directory is linked into
    the scratch one, so the candidate reads the same file -- read-only,
    as every sync does."""
    for silo in config.silo_configs.values():
        path = (silo.get("connection") or {}).get("path")
        if not path or Path(path).is_absolute():
            continue
        target = scratch_data_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.symlink_to((live_data_dir / path).resolve())


def run(candidate_config_dir: Path, paths=None) -> int:
    from scripts.run_sync import run_sync

    paths = paths or resolve_runtime_paths()
    live_config = load_deployment(paths.config_dir)
    try:
        candidate = load_deployment(candidate_config_dir)
    except Exception as e:  # noqa: BLE001 - the candidate's own error is the answer
        print(f"The candidate configuration does not load: {e}")
        print("Fix it first; python -m scripts.lint_deployment lists every problem.")
        return 1

    scratch = Path(tempfile.mkdtemp(prefix="elysium-preview-"))
    try:
        scratch_paths = RuntimePaths(candidate_config_dir, scratch / "data", scratch / "log")
        scratch_paths.data_dir.mkdir(parents=True)
        scratch_paths.log_dir.mkdir(parents=True)
        _link_relative_silos(candidate, paths.data_dir, scratch_paths.data_dir)

        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
            status = run_sync(scratch_paths)
        refusals = [line for line in printed.getvalue().splitlines()
                    if line.startswith(("FAILED", "REFUSED", "DRIFT", "skipped"))]
        print("candidate sync:" + ("" if refusals else " clean"))
        for line in refusals:
            print(f"  {line}")

        live = open_mirror_catalog(paths.data_dir / "mirror", dict(live_config.mirror_storage))
        preview = open_mirror_catalog(scratch_paths.data_dir / "mirror")
        print("\nwhat readers would see, against today:")
        for line in compare(live, live_config.schema, preview, candidate.schema):
            print(f"  {line}")
        print("\nNothing live was changed. To adopt it, replace the configuration and "
              "reload (POST /api/admin/reload), then sync.")
        return 0 if status == 0 else 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(run(Path(sys.argv[1])))
