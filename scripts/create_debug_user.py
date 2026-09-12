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
            f"Add one, or point ELYSIUM_CONFIG_DIR at a deployment that "
            f"has it. Both deployment/etc and tests/integration/fixtures "
            f"do.",
            file=sys.stderr,
        )
        return 1

    # REFUSES TO RUN WITHOUT --yes-this-is-development, and the reason
    # is the password. A four-grant admin account with a memorable
    # password is a mistake; a SIXTEEN-grant account whose password is
    # the single character "a" is a back door, and the thing that makes
    # it dangerous is precisely what makes it convenient here.
    #
    # A guard rather than a warning: this script exists to be run
    # without thinking, which is exactly the property that gets it run
    # somewhere it should not be. Nobody types a flag that says
    # "development" onto a production box by accident and on purpose at
    # the same time -- and if they do, they have been told what it
    # costs.
    if "--yes-this-is-development" not in sys.argv:
        print(
            f"REFUSING. This creates {USERNAME!r} with password {PASSWORD!r} and "
            f"every grant the deployment defines.\n"
            f"That is a back door, not an account. If this really is a "
            f"development machine, re-run with:\n\n"
            f"    python -m scripts.create_debug_user --yes-this-is-development\n",
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
