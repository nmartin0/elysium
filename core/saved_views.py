"""Saved views, where something scheduled can reach them.

WHY THEY MOVE. A `SavedView` was `{name, url}` in the browser's
localStorage -- which worked perfectly for a person returning to a
search, and is invisible to everything else. A condition that runs
after a sync cannot read a browser.

A STORED QUERY, NOT A URL. The URL carried `type`, `q`, `sort`,
`view` and `filters`; only the first three and the filters describe
WHAT MATCHES. `sort` and `view` describe how a person likes to look
at it, which a condition evaluating a count does not need and should
not be made to parse a URL to ignore.

PRIVATE TO THEIR OWNER, AND THAT IS NOT A LIMITATION.

A saved view's QUERY can name specific object ids -- "customer_id =
cust_001" says cust_001 exists -- which is the same leak shape that
deferred the Query panel's starter questions. So the query is never
shown to anybody but its owner.

A CONDITION STILL WORKS ACROSS RECIPIENTS, because a recipient never
sees the query. They see the condition's DESCRIPTION, which its author
wrote, and their OWN count from running that query with their OWN
authority. The query is used on their behalf and never disclosed to
them.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.sqlite_connection import connection_with_schema

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_views (
    view_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    object_type TEXT NOT NULL,
    query_text TEXT NOT NULL DEFAULT '',
    conditions TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
-- Every read is "mine, by name". One index on the pair.
CREATE INDEX IF NOT EXISTS saved_views_owner_name
    ON saved_views (owner_user_id, name);
"""


@dataclass(frozen=True)
class SavedView:
    view_id: str
    name: str
    object_type: str
    query_text: str
    conditions: list
    created_at: str


class SavedViewStore:
    """One person's saved searches, readable by a scheduler."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def save(self, owner_user_id: str, name: str, object_type: str,
             query_text: str = "", conditions: list | None = None) -> str | None:
        """Stores one view. Replaces an existing one of the same name.

        BY NAME, NOT BY ID, because that is how a person thinks about
        it: saving "High-value transactions" twice means updating it,
        not collecting two.
        """
        view_id = str(uuid.uuid4())
        try:
            with self._connection() as conn:
                conn.execute(
                    "DELETE FROM saved_views WHERE owner_user_id = ? "
                    "AND name = ?",
                    (owner_user_id, name),
                )
                conn.execute(
                    "INSERT INTO saved_views (view_id, owner_user_id, name, "
                    "object_type, query_text, conditions, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (view_id, owner_user_id, name, object_type, query_text,
                     json.dumps(conditions or []),
                     datetime.now(UTC).isoformat()),
                )
                conn.commit()
        except Exception as e:  # noqa: BLE001 - a saved view is a convenience
            logger.warning("could not save a view for %s: %s", owner_user_id, e)
            return None
        return view_id

    def for_owner(self, owner_user_id: str) -> list[SavedView]:
        """One person's views, newest first.

        SCOPED IN THE QUERY, not filtered afterwards. There is no call
        that returns everybody's, so there is no privileged view for a
        bug to leak from.
        """
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT view_id, name, object_type, query_text, "
                    "conditions, created_at FROM saved_views "
                    "WHERE owner_user_id = ? ORDER BY created_at DESC",
                    (owner_user_id,),
                ).fetchall()
        except Exception as e:  # noqa: BLE001
            logger.warning("could not read views for %s: %s", owner_user_id, e)
            return []
        return [self._row_to_view(row) for row in rows]

    def get(self, view_id: str) -> SavedView | None:
        """One view, by id, WITHOUT an owner check.

        FOR THE SCHEDULER, which has no user. A condition names a view
        by id and runs it as each recipient -- so the QUERY is read
        here and the RESULTS come from `search_object(user_record,
        ...)`, which is where authority is applied.

        NEVER CALL THIS TO SERVE A REQUEST. `for_owner` is the
        request-side call, and it scopes in SQL.
        """
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT view_id, name, object_type, query_text, "
                    "conditions, created_at FROM saved_views WHERE view_id = ?",
                    (view_id,),
                ).fetchone()
        except Exception as e:  # noqa: BLE001
            logger.warning("could not read view %s: %s", view_id, e)
            return None
        return self._row_to_view(row) if row else None

    def delete(self, owner_user_id: str, view_id: str) -> bool:
        """Deletes one, if it belongs to this person.

        THE OWNER IS IN THE WHERE CLAUSE, so deleting somebody else's
        matches no row -- the same answer as "no such view", and not a
        second ownership check in Python to get wrong.
        """
        try:
            with self._connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM saved_views WHERE view_id = ? "
                    "AND owner_user_id = ?",
                    (view_id, owner_user_id),
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:  # noqa: BLE001
            logger.warning("could not delete view %s: %s", view_id, e)
            return False

    @staticmethod
    def _row_to_view(row) -> SavedView:
        try:
            conditions = json.loads(row["conditions"])
        except (TypeError, json.JSONDecodeError):
            # A VIEW WITH UNREADABLE FILTERS IS STILL A VIEW. Its
            # object type and text survive, and an empty filter list
            # matches more rather than less -- which a person will
            # notice, where a missing view they would simply blame on
            # the product.
            conditions = []
        return SavedView(
            row["view_id"], row["name"], row["object_type"],
            row["query_text"], conditions, row["created_at"],
        )
