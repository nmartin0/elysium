"""
user_directory.py  (runtime, database-backed user management --
AUTHORIZATION, not authentication)

Deliberately separate from core/auth/, even though it shares that
package's physical database (core/auth/database.py's connection()) --
"who exists and what they're allowed to do" is a conceptually different
concern from "how they prove who they are." It happens to be
convenient to store both in one file for a small, single-tenant
deployment; it is not the same knowledge.

WHY THIS EXISTS: policy.yaml's roles stay static, human-edited
config -- what a role MEANS (which read:/write:/tool: actions) changes
rarely and deserves human review. But WHICH person has WHICH role is
exactly the kind of thing "root logs in and adds a new employee" needs
to change at runtime, without a restart -- a YAML file isn't suited to
safe, concurrent, programmatic mutation. This is the runtime-mutable
half of that split; policy.yaml's roles are the static half.

create_user() writes BOTH the users table (mac_value + role_name) AND
a real login credential, atomically, in ONE transaction -- deliberately
NOT two separate calls. If these were independent operations, a crash
between them could leave an orphaned credential (can log in, no
permissions) or an orphaned directory entry (has permissions, can't
log in). One connection, one commit, both or neither.

get_user_record() returns a real UserRecord (see core/
intermediate_layer/auth.py) -- ALWAYS, even for an unknown username
(both fields None), same "no special early-exit case" contract
resolve_user_record() (the policy.yaml-backed equivalent) already
follows.

Used by: the future api/ layer (root-only routes, gated by the caller
         checking authorize(caller_record, roles, "manage:users")
         BEFORE ever calling create_user() -- this module does not
         check that itself; gatekeeping stays at the boundary, not
         duplicated internally, same pattern as every other layer in
         this project).
"""

import sqlite3
from pathlib import Path

from core.auth.credential_store import insert_credential_using_connection
from core.auth.database import connection
from core.auth.password_hashing import hash_password
from core.intermediate_layer.auth import UserRecord


def create_user(db_path: Path, roles: dict, username: str, password: str,
                 mac_value: str | None, role_name: str) -> None:
    if role_name not in roles:
        # Fails loudly at creation time, not silently later as a user
        # with a role name that matches nothing in policy.yaml -- such
        # a user would authorize() as if they had NO role at all
        # (authorize() treats an unknown role_name as denied), which
        # would be a confusing, hard-to-diagnose way to fail.
        raise ValueError(f"Unknown role {role_name!r}")

    password_hash = hash_password(password)
    with connection(db_path) as conn:
        try:
            conn.execute(
                "INSERT INTO users (username, mac_value, role_name) VALUES (?, ?, ?)",
                (username, mac_value, role_name),
            )
            insert_credential_using_connection(conn, username, password_hash)
            conn.commit()
        except sqlite3.IntegrityError:
            # Either INSERT could be the one that collided (a duplicate
            # username in EITHER table) -- rolling back both together
            # (the transaction is never committed) means neither an
            # orphaned users row nor an orphaned credential can result,
            # regardless of which INSERT actually failed.
            raise ValueError(f"User {username!r} already exists")


def get_user_record(db_path: Path, username: str) -> UserRecord:
    # Note: no security_attribute parameter needed here, unlike
    # resolve_user_record() -- the database column is always literally
    # named mac_value regardless of what a deployment's policy.yaml
    # calls the concept ("region", "department", etc.); that naming
    # only matters for the dict-shaped, policy.yaml-backed path.
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT mac_value, role_name FROM users WHERE username = ?", (username,)
        ).fetchone()

    if row is None:
        return UserRecord(username, None, None)

    return UserRecord(username, row["mac_value"], row["role_name"])
