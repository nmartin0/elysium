"""
bootstrap_root.py  (create the very first admin user -- run exactly once)

There is no other way to create the first user: every other path
(the /users API endpoint) requires an ALREADY-authenticated caller
with manage:users -- a genuine chicken-and-egg problem this script
exists solely to resolve, once, right after a fresh install.

Generates a real, cryptographically random password via
secrets.token_urlsafe() and prints it exactly once -- never a
hardcoded default, satisfying the project's own standing requirement
that credentials are never baked into source or config. There is no
way to recover this password afterward; losing it means resetting it
via CredentialStore.update_credential() directly.

Used by: scripts/install.sh, immediately after a fresh install, before
         the service is used for real.
"""

import secrets
import sys

from core.deployment_loader import load_deployment, resolve_runtime_paths
from core.user_directory import UserDirectory


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python3 -m scripts.bootstrap_root <username> <role_name>")
        sys.exit(1)

    username, role_name = sys.argv[1], sys.argv[2]
    paths = resolve_runtime_paths()
    config = load_deployment(paths.config_dir)
    password = secrets.token_urlsafe(24)

    user_directory = UserDirectory(paths.data_dir / "credentials.db", config.roles)
    try:
        user_directory.create_user(username, password, None, role_name)
    except ValueError as e:
        print(f"Could not create user: {e}")
        sys.exit(1)

    print(f"Created user {username!r} with role {role_name!r}.")
    print()
    print(f"PASSWORD (shown once -- save it now, it cannot be recovered): {password}")


if __name__ == "__main__":
    main()
