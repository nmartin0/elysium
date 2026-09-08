"""
artifact_store.py  (saved things: searches, selections, pending writes)

One store for anything a user saves and may later reopen. Saved
searches need it; the Approvals inbox needs it; both were blocked on
the same questions, so they are answered once here.

OWNERSHIP IS BY ROLE, NOT BY USER. An artifact is private to its
owner, or shared with a role. Sharing to individual users would be a
second permission model beside RBAC -- and two models is how
permission bugs happen. Roles are already the unit of authorization
everywhere else, so an artifact you may see is one you own or one
shared with the role you hold. That is a single check, using
machinery that exists.

EXPIRY BELONGS TO THE ARTIFACT TYPE, NOT TO THIS STORE. A pending
write dies in fifteen minutes because it is the continuation of one
person's session. A saved search should never die. If the store owned
expiry, every future artifact would inherit a policy designed for one
of them -- so `expires_at` is supplied by the caller and NULL means
"never", which is a legitimate answer rather than a missing one.

WHAT THIS STORE DOES NOT DECIDE. It does not know whether a saved
search's filters are still readable by the person opening it. That is
re-authorization, it needs the ontology and a caller, and it belongs
to whoever reads the artifact back -- see
core/ontology/mediator.py for where field readability is actually
checked. A store that returned "safe" content would be a second place
deciding what a caller may see.

WHY SQLITE. The same reasoning that backs write_log.db and
credentials.db: one process, one writer, and a file that survives a
restart. The earlier framing had this waiting on PostgreSQL, which was
wrong -- Postgres is warranted by sustained concurrent write pressure
or a genuinely multi-worker deployment, and neither exists. See
ROADMAP.md's PostgreSQL scope.
"""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.sqlite_connection import connection_with_schema, immediate_transaction

SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id   TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    shared_role   TEXT,
    body          TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    expires_at    TEXT
);
CREATE INDEX IF NOT EXISTS artifacts_by_owner ON artifacts (owner_user_id);
CREATE INDEX IF NOT EXISTS artifacts_by_role ON artifacts (shared_role);
"""


@dataclass(frozen=True)
class Artifact:
    """One saved thing.

    `body` is opaque to the store -- a saved search's conditions, a
    pending write's sub_writes. Giving the store a schema for each
    kind would make it the place every new artifact type has to change.
    """

    artifact_id: str
    kind: str
    title: str
    owner_user_id: str
    shared_role: str | None
    body: dict
    created_at: str
    expires_at: str | None


class ArtifactStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def save(self, kind: str, title: str, owner_user_id: str, body: dict,
              shared_role: str | None = None, expires_at: datetime | None = None) -> str:
        """Stores an artifact and returns its id.

        `expires_at` of None means never -- see this module's own
        docstring for why the lifetime is the caller's to decide.
        """
        artifact_id = str(uuid.uuid4())
        with self._connection() as conn, immediate_transaction(conn):
            conn.execute(
                "INSERT INTO artifacts (artifact_id, kind, title, owner_user_id, "
                "shared_role, body, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact_id, kind, title, owner_user_id, shared_role,
                    json.dumps(body), datetime.now(UTC).isoformat(),
                    expires_at.isoformat() if expires_at else None,
                ),
            )
        return artifact_id

    def get(self, artifact_id: str, user_id: str, role_name: str | None) -> Artifact | None:
        """One artifact, if this caller may see it.

        Returns None for "no such artifact" AND for "not yours" --
        uniform denial, so a caller cannot discover that an id exists
        by being refused it. The same reasoning as an unreadable field
        being indistinguishable from an absent one.
        """
        self._expire_stale()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        if row is None or not self._visible_to(row, user_id, role_name):
            return None
        return self._as_artifact(row)

    def list_for(self, user_id: str, role_name: str | None,
                  kind: str | None = None) -> list[Artifact]:
        """Everything this caller may see, newest first."""
        self._expire_stale()
        query = "SELECT * FROM artifacts WHERE (owner_user_id = ? OR shared_role = ?)"
        values: list[Any] = [user_id, role_name]
        if kind is not None:
            query += " AND kind = ?"
            values.append(kind)
        with self._connection() as conn:
            rows = conn.execute(query + " ORDER BY created_at DESC", tuple(values)).fetchall()
        return [self._as_artifact(row) for row in rows]

    def delete(self, artifact_id: str, user_id: str) -> bool:
        """Removes an artifact. Only its OWNER may.

        Sharing grants reading, not destruction: someone who can see a
        colleague's saved search must not be able to delete it out from
        under them.
        """
        with self._connection() as conn, immediate_transaction(conn):
            cursor = conn.execute(
                "DELETE FROM artifacts WHERE artifact_id = ? AND owner_user_id = ?",
                (artifact_id, user_id),
            )
            return cursor.rowcount > 0

    def _expire_stale(self) -> None:
        """Drops anything past its expiry.

        On READ rather than on a timer, matching PendingWriteStore: a
        background task is another thing to run and to get wrong, and
        an expired artifact that nobody reads harms nobody.
        """
        with self._connection() as conn, immediate_transaction(conn):
            conn.execute(
                "DELETE FROM artifacts WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (datetime.now(UTC).isoformat(),),
            )

    @staticmethod
    def _visible_to(row: sqlite3.Row, user_id: str, role_name: str | None) -> bool:
        if row["owner_user_id"] == user_id:
            return True
        # `shared_role` NULL means private, and a caller with no role
        # must not match it -- without this check, None == None would
        # make every private artifact visible to a roleless caller.
        return row["shared_role"] is not None and row["shared_role"] == role_name

    @staticmethod
    def _as_artifact(row: sqlite3.Row) -> Artifact:
        return Artifact(
            artifact_id=row["artifact_id"],
            kind=row["kind"],
            title=row["title"],
            owner_user_id=row["owner_user_id"],
            shared_role=row["shared_role"],
            body=json.loads(row["body"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
        )
