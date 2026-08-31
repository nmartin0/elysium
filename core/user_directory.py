"""
user_directory.py  (runtime, database-backed user management --
AUTHORIZATION, not authentication)

A CLASS, not free functions taking db_path (and, for create_user(),
roles) on every call -- same reasoning as core/auth/credential_store.py's
own CredentialStore and core/auth/session_store.py's own SessionStore
(see their docstrings): db_path is genuinely this directory's own
state. roles is ALSO constructor state here, not a per-call parameter
-- it comes from the same static, per-deployment policy.yaml that
never changes across this instance's lifetime, the same character as
db_path, not like username/password (genuine per-call input); only
create_user() actually needs it, but it's still stable, owned
configuration, not operation-specific data. One instance, constructed
once at app-startup (or once per script run), shared by every caller
-- see api/app.py and scripts/bootstrap_root.py.

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
log in). One connection, one commit, both or neither. delete_user()
mirrors this same discipline in reverse -- users, credentials, AND
sessions all cleared in one transaction, so a deleted account can
never be left with a still-valid session token, even if the process
crashed mid-operation.

disable_user() ALSO invalidates every existing session for that
username, in the SAME transaction as flipping the flag -- belt and
suspenders. The per-request check in api/auth_dependency.py (querying
this flag fresh on every request, before a UserRecord is ever
resolved) already means a disabled account's existing session would be
rejected on its very next use regardless; clearing sessions here too
means there's no reliance on exactly one check point holding correctly
forever. Deliberately inline SQL against the sessions table here, NOT
a call to SessionStore.invalidate_all_sessions() -- that manages its
own connection/commit, which would break the "one transaction, both or
neither" guarantee this method exists to provide. delete_user() does
the same, for the same reason, against both credentials and sessions.

`disabled` is DELIBERATELY kept OUT of UserRecord (core/
intermediate_layer/auth.py) entirely -- UserRecord is a pure
authorization snapshot (role + MAC value); account status is a
different KIND of fact, checked once, up front, before authorization
is even resolved, not folded into the same object.

get_user_record() returns a real UserRecord (see core/
intermediate_layer/auth.py) -- ALWAYS, even for an unknown username
(both fields None), same "no special early-exit case" contract
resolve_user_record() (the policy.yaml-backed equivalent) already
follows.

Used by: api/routes.py (root-only routes, gated by the caller checking
         authorize(caller_record, roles, "manage:users") BEFORE ever
         calling any of these -- this class does not check that
         itself; gatekeeping stays at the boundary, not duplicated
         internally, same pattern as every other layer in this
         project), api/auth_dependency.py (is_user_disabled(), on
         every authenticated request), scripts/bootstrap_root.py
"""

import sqlite3
from pathlib import Path

from core.auth.credential_store import insert_credential_using_connection
from core.auth.database import connection
from core.auth.password_hashing import hash_password
from core.intermediate_layer.auth import UserRecord


class UserDirectory:
    def __init__(self, db_path: Path, roles: dict):
        self._db_path = db_path
        self._roles = roles

    def create_user(self, username: str, password: str, mac_value: str | None, role_name: str) -> None:
        if role_name not in self._roles:
            # Fails loudly at creation time, not silently later as a user
            # with a role name that matches nothing in policy.yaml -- such
            # a user would authorize() as if they had NO role at all
            # (authorize() treats an unknown role_name as denied), which
            # would be a confusing, hard-to-diagnose way to fail.
            raise ValueError(f"Unknown role {role_name!r}")

        password_hash = hash_password(password)
        with connection(self._db_path) as conn:
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
                raise ValueError(f"User {username!r} already exists") from None

    def get_user_record(self, username: str) -> UserRecord:
        # Note: no security_attribute parameter needed here, unlike
        # resolve_user_record() -- the database column is always literally
        # named mac_value regardless of what a deployment's policy.yaml
        # calls the concept ("region", "department", etc.); that naming
        # only matters for the dict-shaped, policy.yaml-backed path.
        with connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT mac_value, role_name FROM users WHERE username = ?", (username,)
            ).fetchone()

        if row is None:
            return UserRecord(username, None, None)

        return UserRecord(username, row["mac_value"], row["role_name"])

    def is_user_disabled(self, username: str) -> bool:
        # False for an unknown username too -- "doesn't exist" and
        # "disabled" are different facts, and this method only answers
        # the second one. A caller checking identity should already be
        # handling the "doesn't exist" case via get_user_record()'s own
        # empty-record contract.
        with connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT disabled FROM users WHERE username = ?", (username,)
            ).fetchone()

        if row is None:
            return False

        return bool(row["disabled"])

    def user_exists(self, username: str) -> bool:
        # Distinct from checking get_user_record().role_name is not None --
        # a real user CAN legitimately have no role assigned, so that check
        # alone can't tell "unknown username" apart from "known username,
        # no role." Used where that distinction has real practical value
        # (e.g. an admin debugging tool telling a typo apart from a
        # genuinely empty result) -- not a security-sensitive check, so
        # uniform-denial doesn't apply here.
        with connection(self._db_path) as conn:
            row = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        return row is not None

    def list_users(self) -> list[dict]:
        # Non-sensitive account metadata ONLY -- username, MAC value, role,
        # disabled status. NEVER password hashes; core/auth/credential_store.py's
        # table isn't touched here at all. Safe to expose directly to an
        # admin UI (see api/routes.py's GET /users, gated by manage:users
        # same as every other account-management route).
        with connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT username, mac_value, role_name, disabled FROM users ORDER BY username"
            ).fetchall()

        return [
            {
                "username": row["username"],
                "mac_value": row["mac_value"],
                "role_name": row["role_name"],
                "disabled": bool(row["disabled"]),
            }
            for row in rows
        ]

    def disable_user(self, username: str) -> None:
        with connection(self._db_path) as conn:
            cursor = conn.execute("UPDATE users SET disabled = 1 WHERE username = ?", (username,))
            # Same transaction, same commit -- see module docstring for
            # why this isn't a separate invalidate_all_sessions() call.
            conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"User {username!r} does not exist")

    def enable_user(self, username: str) -> None:
        with connection(self._db_path) as conn:
            cursor = conn.execute("UPDATE users SET disabled = 0 WHERE username = ?", (username,))
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"User {username!r} does not exist")

    def delete_user(self, username: str) -> None:
        with connection(self._db_path) as conn:
            cursor = conn.execute("DELETE FROM users WHERE username = ?", (username,))
            conn.execute("DELETE FROM credentials WHERE username = ?", (username,))
            conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"User {username!r} does not exist")
