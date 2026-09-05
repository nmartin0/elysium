"""
credential_store.py  (create/verify/update a user's login credential)

Two real, separate classes -- CredentialReader(InternalReadAdapter) and
CredentialWriter(InternalWriteAdapter) -- not one, combined class,
matching the same real split core/auth/query_rate_limiter.py's own
QueryRateLimitReader/QueryRateLimitWriter already established as the
real, working pattern for this project's internal stores (see core/
internal_storage.py's own module docstring for the fuller design
reasoning -- CQRS, Python's own typeshed precedent -- settled before
either split was written).

Two DELIBERATELY separate write operations on CredentialWriter, not
one ambiguous "create-or-overwrite": create_credential() rejects if the
username already exists (never silently resets a password by
accident); update_credential() rejects if it does NOT exist (can't
update what isn't there). Each failure mode is a genuine, distinct
mistake worth its own clear error, not one function papering over two
different intents.

insert_credential_using_connection() stays a MODULE-LEVEL function, not
a method on either class -- it takes an already-open connection
directly, needing no instance state at all, and is a genuinely shared
building block, not a private implementation detail reached across a
module boundary: core/user_directory.py's UserDirectory.create_user()
needs the users table AND the credentials table written in ONE
transaction (same connection, one commit), so it can't go through
CredentialWriter's own create_credential() (that manages its own
connection/commit). Exposing this as a real, public, minimal primitive
both callers can build their own transaction around is more honest
than either duplicating the INSERT here and there, or importing
something named as private.

CredentialWriter's own methods deliberately do NOT use
InternalWriteAdapter's own, simpler _connection() -- the same real,
considered choice query_rate_limiter.py's own QueryRateLimitWriter
already makes, for the identical reason: the credentials table's own
schema needs to genuinely exist before any write succeeds, and core/
auth/database.py's own schema-aware connection() (lazy, idempotent
CREATE TABLE IF NOT EXISTS) is the real, already-correct mechanism for
that, reused directly rather than duplicated. CredentialReader's own
verify_credential(), by contrast, DOES use InternalReadAdapter's own
_connection() directly -- a real, structurally read-only guarantee
(core/sqlite_connection.py's own open_connection(read_only=True)),
since a read never needs, and must never have, the ability to create
a table it didn't find.

verify_credential() is timing-safe by construction: a nonexistent
username still performs a REAL argon2id verification (against
password_hashing.DUMMY_HASH) before returning False, so response
timing alone never reveals which usernames exist -- skipping the
expensive hash step for a missing user would create exactly that side
channel.

Used by: api/routes.py (via the auth dependency, and directly for
         /login -- CredentialReader only, today; CredentialWriter's
         own create_credential/update_credential have no real,
         production caller yet -- core/user_directory.py's own
         UserDirectory.create_user() uses
         insert_credential_using_connection() directly instead, real,
         genuine, existing capability kept regardless of current
         wiring, not removed as part of this split), core/
         user_directory.py (insert_credential_using_connection only).
         Never by anything in core/ontology or core/agent --
         authentication is a front gate, completely separate from the
         authorization (RBAC/MAC) system everything downstream already
         uses.
"""

import sqlite3
from datetime import UTC, datetime

from core.auth.database import connection
from core.auth.password_hashing import DUMMY_HASH, hash_password, verify_password
from core.internal_storage import InternalReadAdapter, InternalWriteAdapter


def insert_credential_using_connection(conn: sqlite3.Connection, username: str, password_hash: str) -> None:
    # Does NOT commit -- the caller controls the transaction boundary,
    # since this may be one write among several that must all succeed
    # or none at all (see core/user_directory.py's UserDirectory.create_user()).
    conn.execute(
        "INSERT INTO credentials (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, password_hash, datetime.now(UTC).isoformat()),
    )


class CredentialReader(InternalReadAdapter):
    def verify_credential(self, username: str, password: str) -> bool:
        with self._connection() as conn:
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


class CredentialWriter(InternalWriteAdapter):
    def create_credential(self, username: str, password: str) -> None:
        password_hash = hash_password(password)
        with connection(self.db_path) as conn:
            try:
                insert_credential_using_connection(conn, username, password_hash)
                conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(f"User {username!r} already exists") from None

    def update_credential(self, username: str, new_password: str) -> None:
        password_hash = hash_password(new_password)
        with connection(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE credentials SET password_hash = ? WHERE username = ?",
                (password_hash, username),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"User {username!r} does not exist")
