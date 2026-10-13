"""Write every object type's ODCS data contract (R16).

    python -m scripts.export_contracts [--out DIR]

One `<Type>.odcs.yaml` per object type, describing its GOLD table --
the columns, their types, the key, classifications, declared
constraints and the freshness target. Default directory: ./contracts.

GENERATED FROM THE ONTOLOGY, so re-run it after an ontology change
rather than editing a file: an edited contract promises things nothing
checks. The same contract, one type at a time, is served at
/api/admin/contracts/<Type> to anyone holding manage:users, as /api/config is.

Validate one with the standard's own tool, if you have it:

    datacontract lint contracts/Customer.odcs.yaml
"""

import argparse
import sys
from pathlib import Path

from core.deployment_loader import load_deployment, resolve_runtime_paths
from core.mirror.data_contracts import contract_yaml, data_contract


def run(out: Path, paths=None) -> int:
    paths = paths or resolve_runtime_paths()
    config = load_deployment(paths.config_dir)
    namespace = config.lineage.get("namespace") or "elysium"
    out.mkdir(parents=True, exist_ok=True)
    for object_type in sorted(config.schema or {}):
        contract = data_contract(object_type, config.schema,
                                 config.freshness_targets.get(object_type), namespace=namespace)
        path = out / f"{object_type}.odcs.yaml"
        path.write_text(contract_yaml(contract))
        print(f"wrote {path}  ({contract['version']})")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("contracts"))
    sys.exit(run(parser.parse_args().out))
