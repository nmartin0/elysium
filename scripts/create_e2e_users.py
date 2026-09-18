"""Creates the two users the browser tests log in as.

WHY A SCRIPT. ui/e2e/shell.spec.ts documented its users as a pair of
`python3 -c "..."` one-liners naming a role -- `editor` -- that this
deployment does not define. So the documented setup could not work,
and the tests sat unrun long enough for nobody to notice.

A command that can be run is the difference between a test suite and a
description of one.

TWO USERS, BECAUSE THE POINT IS THE DIFFERENCE BETWEEN THEM. The nav
is supposed to show Admin to one and not the other, which is a claim
about real grants rather than about rendering, and it cannot be made
with a single account.

RUN FROM THE REPOSITORY ROOT:

    cd ~/elysium
    python -m scripts.create_e2e_users --yes-this-is-development

DEVELOPMENT ONLY, and it refuses without the flag for the same reason
create_debug_user.py does: known usernames with known passwords are a
back door anywhere that matters.
"""

import sys

from core.deployment_loader import load_deployment, resolve_runtime_paths
from core.user_directory import UserDirectory

# THE ROLES THIS DEPLOYMENT ACTUALLY DEFINES, checked rather than
# assumed: customer_service holds read grants and no manage:users,
# admin holds manage:users. The old setup comment named `editor`, which
# does not exist here -- a setup nobody had run since the roles changed.
USERS = [
    ("plainuser", "plainpass123", "us-west", "customer_service"),
    ("adminuser", "adminpass123", "us-west", "admin"),
]


def main() -> int:
    if "--yes-this-is-development" not in sys.argv:
        print(
            "REFUSING. This creates accounts with known passwords, for browser\n"
            "tests. That is a back door on any machine that matters.\n\n"
            "If this really is a development machine, re-run with:\n\n"
            "    python -m scripts.create_e2e_users --yes-this-is-development",
            file=sys.stderr,
        )
        return 1

    paths = resolve_runtime_paths()
    config = load_deployment(paths.config_dir)
    # May not exist on a fresh checkout -- the same guard
    # create_debug_user.py carries, for the same reason.
    paths.data_dir.mkdir(parents=True, exist_ok=True)

    missing = [role for _, _, _, role in USERS if role not in config.roles]
    if missing:
        # NAMED, NOT GUESSED AT. The old path failed with a message
        # about the user rather than about the role, which is why a
        # deployment that had renamed its roles looked like a broken
        # test rather than a stale setup.
        print(
            f"This deployment defines no role(s): {', '.join(missing)}.\n"
            f"It has: {', '.join(sorted(config.roles))}.",
            file=sys.stderr,
        )
        return 1

    directory = UserDirectory(paths.data_dir / "credentials.db", config.roles)

    for username, password, region, role in USERS:
        # REPLACED, NOT SKIPPED. "Already exists" was reported as
        # harmless and was not: an account left from an earlier run
        # can carry a different password or role, so the script said
        # everything was fine and the browser got a 401. That is worse
        # than failing, because the error surfaces two steps away as a
        # missing nav item.
        #
        # These are known-password development accounts, so recreating
        # them costs nothing anyone could miss.
        try:
            directory.delete_user(username)
            print(f"  replaced {username} ({role})")
        except ValueError:
            # NAMED, because that is what an absent user raises --
            # checked rather than assumed. A broad catch here would
            # swallow a permissions error or a corrupt database and
            # still print "created", which is the exact shape of lie
            # this audit is looking for.
            print(f"  created {username} ({role})")

        directory.create_user(username, password, region, role)

    print("\nNow, from ui/: npm run e2e")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
