"""Creates a SECOND account in the same role, for testing sharing.

Notes are shared with the author's ROLE, not kept private -- that is
the whole point of writing one down rather than remembering it. This
script exists so that claim can be checked rather than assumed: log in
as one account, write a note, log in as the other, and the note should
be there.

Both accounts get the `debug` role and the same MAC region, because
the thing under test is ROLE-SHARING. Two users in different roles
would prove the opposite and look like the same experiment.

DEVELOPMENT ONLY. Idempotent -- an existing account is reported rather
than failing, so re-running after a reboot costs nothing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.deployment_loader import load_deployment, resolve_runtime_paths  # noqa: E402
from core.user_directory import UserDirectory  # noqa: E402

# The same role and region as create_debug_user.py's account. If those
# change, this must change with them or the experiment silently stops
# testing sharing.
ROLE = "debug"
REGION = "us-west"
ACCOUNTS = [("debug", "a"), ("colleague", "a")]


def main() -> int:
    paths = resolve_runtime_paths()
    config = load_deployment(paths.config_dir)

    if ROLE not in config.roles:
        print(
            f"No {ROLE!r} role in {paths.config_dir}/policy.yaml. Set "
            f"ELYSIUM_CONFIG_DIR to tests/integration/fixtures.",
            file=sys.stderr,
        )
        return 1

    paths.data_dir.mkdir(parents=True, exist_ok=True)
    directory = UserDirectory(paths.data_dir / "credentials.db", config.roles)

    for username, password in ACCOUNTS:
        try:
            directory.create_user(username, password, REGION, ROLE)
            print(f"  created {username!r} / {password!r}")
        except Exception as e:
            print(f"  {username!r} not created: {e}")

    print(f"\nBoth hold the {ROLE!r} role and region {REGION!r}.")
    print("\nTo check that notes are shared rather than private:")
    print("  1. Log in as 'debug', open a Customer, write a note.")
    print("  2. Log out, log in as 'colleague', open the SAME Customer.")
    print("  3. The note should be there, attributed to 'debug'.")
    print("\nIf it is missing, sharing is broken -- that is the bug to report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
