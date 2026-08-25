"""
credential_store.py  (create/verify/update a user's login credential)

Two DELIBERATELY separate write operations, not one ambiguous
"create-or-overwrite": create_credential() rejects if the username
already exists (never silently resets a password by accident);
update_credential() rejects if it does NOT exist (can't update what
isn't there). Each failure mode is a genuine, distinct mistake worth
its own clear error, not one function papering over two different
intents.

verify_credential() is timing-safe by construction: a nonexistent
username still performs a REAL argon2id verification (against
password_hashing.DUMMY_HASH) before returning False, so response
timing alone never reveals which usernames exist -- skipping the
expensive hash step for a missing user would create exactly that side
channel.

Used by: api/routes.py (via the auth dependency), never by anything in
         core/ontology or core/agent -- authentication is a front gate,
         completely separate from the authorization (RBAC/MAC) system
         everything downstream already uses.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core.auth.database import connection
from core.auth.password_hashing import hash_password, verify_password, DUMMY_HASH


def create_credential(db_path: Path, username: str, password: str) -> None:
    password_hash = hash_password(password)
    with connection(db_path) as conn:
        try:
            conn.execute(
                "INSERT INTO credentials (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, password_hash, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"User {username!r} already exists")


def update_credential(db_path: Path, username: str, new_password: str) -> None:
    password_hash = hash_password(new_password)
    with connection(db_path) as conn:
        cursor = conn.execute(
            "UPDATE credentials SET password_hash = ? WHERE username = ?",
            (password_hash, username),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"User {username!r} does not exist")


def verify_credential(db_path: Path, username: str, password: str) -> bool:
    with connection(db_path) as conn:
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
