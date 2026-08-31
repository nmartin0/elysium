"""
credential_store.py  (create/verify/update a user's login credential)

A CLASS, not free functions taking db_path on every call -- db_path is
genuinely this store's own state (which physical database it talks
to), so it belongs on self, encapsulated the same way every other
per-deployment store in this project now is (see core/ontology/
write_log.py's own docstring for the identical reasoning, applied
here). One instance, constructed once at app-startup, shared by every
caller -- see api/app.py.

Two DELIBERATELY separate write operations, not one ambiguous
"create-or-overwrite": create_credential() rejects if the username
already exists (never silently resets a password by accident);
update_credential() rejects if it does NOT exist (can't update what
isn't there). Each failure mode is a genuine, distinct mistake worth
its own clear error, not one function papering over two different
intents.

insert_credential_using_connection() stays a MODULE-LEVEL function, not
a method -- it takes an already-open connection directly, needing no
instance state at all, and is a genuinely shared building block, not a
private implementation detail reached across a module boundary:
core/user_directory.py's UserDirectory.create_user() needs the users
table AND the credentials table written in ONE transaction (same
connection, one commit), so it can't go through a CredentialStore
instance's own create_credential() (that manages its own
connection/commit). Exposing this as a real, public, minimal primitive
both callers can build their own transaction around is more honest
than either duplicating the INSERT here and there, or importing
something named as private.

verify_credential() is timing-safe by construction: a nonexistent
username still performs a REAL argon2id verification (against
password_hashing.DUMMY_HASH) before returning False, so response
timing alone never reveals which usernames exist -- skipping the
expensive hash step for a missing user would create exactly that side
channel.

Used by: api/routes.py (via the auth dependency, and directly for
         /login), core/user_directory.py (insert_credential_using_connection
         only). Never by anything in core/ontology or core/agent --
         authentication is a front gate, completely separate from the
         authorization (RBAC/MAC) system everything downstream already
         uses.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from core.auth.database import connection
from core.auth.password_hashing import DUMMY_HASH, hash_password, verify_password


def insert_credential_using_connection(conn: sqlite3.Connection, username: str, password_hash: str) -> None:
    # Does NOT commit -- the caller controls the transaction boundary,
    # since this may be one write among several that must all succeed
    # or none at all (see core/user_directory.py's UserDirectory.create_user()).
    conn.execute(
        "INSERT INTO credentials (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, password_hash, datetime.now(UTC).isoformat()),
    )


class CredentialStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def create_credential(self, username: str, password: str) -> None:
        password_hash = hash_password(password)
        with connection(self._db_path) as conn:
            try:
                insert_credential_using_connection(conn, username, password_hash)
                conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(f"User {username!r} already exists") from None

    def update_credential(self, username: str, new_password: str) -> None:
        password_hash = hash_password(new_password)
        with connection(self._db_path) as conn:
            cursor = conn.execute(
                "UPDATE credentials SET password_hash = ? WHERE username = ?",
                (password_hash, username),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"User {username!r} does not exist")

    def verify_credential(self, username: str, password: str) -> bool:
        with connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT password_hash FROM credentials WHERE username = ?", (username,)
            ).fetchone()

        if row is None:
            # See module docstring -- a real verification against a dummy
            # hash, so this path costs the same as a real user's wrong
            # password, not a fast early return.
            verify_password(DUMMY_HASH, password)
            return False

        return verify_password(row["password_hash"], password)
