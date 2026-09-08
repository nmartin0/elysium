"""Creates the `debug` account for manual UI testing.

One login that reaches every sub-app and reads every object type, so
checking a layout does not mean switching users three times.

Idempotent: run it again after wiping the data directory, or after
adding a sub-app, and it will report rather than fail.

DEVELOPMENT ONLY. The `debug` role in the fixture policy holds every
grant some other role already holds -- it invents no new permission --
but a real deployment gives each role what its work needs, and an
account like this has no place in one.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.deployment_loader import load_deployment, resolve_runtime_paths  # noqa: E402
from core.user_directory import UserDirectory  # noqa: E402

USERNAME = "debug"
PASSWORD = "a"
ROLE = "debug"
REGION = "us-west"


def main() -> int:
    paths = resolve_runtime_paths()
    config = load_deployment(paths.config_dir)

    if ROLE not in config.roles:
        print(
            f"No {ROLE!r} role in {paths.config_dir}/policy.yaml.\n"
            f"This script is for the development fixture deployment; set "
            f"ELYSIUM_CONFIG_DIR to tests/integration/fixtures.",
            file=sys.stderr,
        )
        return 1

    # The directory may not exist on a fresh checkout -- the server
    # creates it at startup, and this script should not require having
    # run the server first.
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    directory = UserDirectory(paths.data_dir / "credentials.db", config.roles)
    try:
        directory.create_user(USERNAME, PASSWORD, REGION, ROLE)
        print(f"Created {USERNAME!r} / {PASSWORD!r}  (region={REGION}, role={ROLE})")
    except Exception as e:
        # Already existing is the common case on a re-run, and is fine.
        print(f"{USERNAME!r} not created: {e}")
        print("If it already exists, that is fine -- log in with it.")

    grants = len(config.roles[ROLE].get("allowed_actions", []))
    print(f"{ROLE!r} holds {grants} grants; every sub-app should be visible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
