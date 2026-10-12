"""Who would gain and lose which fields if label enforcement were on (formerly BLOCKING 6).

    python -m scripts.label_access_diff

Read before setting `access: {label_enforcement: true}` in config.yaml.
With it on, a field carrying classification labels is readable only by
a role holding read:label:<every one of them>, and read:label:<L> grants
every L field in the types a role can read. This prints, per role, the
field grants that would appear and the ones that would become discover-
only -- the role may still see the field exists, not its value.

Changes nothing. Runs against the configuration and role store this
deployment would load.
"""

import sys

from core.deployment_loader import load_deployment, resolve_runtime_paths


def run(paths=None) -> int:
    from core.deployment_loader import _with_effective_roles
    from core.ontology.classifications import label_access_changes

    paths = paths or resolve_runtime_paths()
    config = _with_effective_roles(load_deployment(paths.config_dir), paths.data_dir)
    state = "ON" if config.label_enforcement else "off"
    print(f"label enforcement is {state} in this deployment\n")
    for role_name, (gained, lost) in sorted(label_access_changes(config.roles,
                                                                 config.schema).items()):
        if not gained and not lost:
            print(f"{role_name}: no change")
            continue
        print(f"{role_name}:")
        for grant in gained:
            print(f"  + {grant}")
        for grant in lost:
            print(f"  - {grant}  (discover only)")
    return 0


if __name__ == "__main__":
    sys.exit(run())
