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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from core.sqlite_connection import add_column_if_missing, connection_with_schema

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_views (
    view_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    object_type TEXT NOT NULL,
    query_text TEXT NOT NULL DEFAULT '',
    conditions TEXT NOT NULL DEFAULT '[]',
    -- HOW THE OWNER LIKES TO LOOK AT IT: sort order, table or chart.
    --
    -- SEPARATE FROM THE QUERY, not discarded. An earlier version of
    -- this file argued that `sort` and `view` "describe how a person
    -- likes to look at it" and left them out -- right about what a
    -- CONDITION needs, wrong about what a SAVED VIEW is. Somebody
    -- restoring one and finding their sort gone would have lost
    -- something the browser-local version kept.
    --
    -- A CONDITION NEVER READS THIS. It is opaque to the evaluator,
    -- which is what "separate" is for: the query stays clean without
    -- the presentation being thrown away.
    presentation TEXT NOT NULL DEFAULT '{}',
    -- HOW THE PERSON GOT HERE: {type, id, field}, the one link they
    -- followed to arrive at this search. DEV_UI.md 11.2 names it as
    -- the third part of what a set IS -- "object type + conditions +
    -- the traversal chain that produced it" -- and it was the part
    -- this table dropped.
    --
    -- "Ada Okafor's transactions" saved and reopened came back as
    -- transactions filtered by customer_id, which is the same ROWS
    -- and a different thing to a reader: the filter survived and the
    -- reason for it did not.
    --
    -- NO NEW EXPOSURE. The origin's id is already in this table, as a
    -- value inside `conditions` -- the trail only shows while a filter
    -- naming that exact id is present, which is what makes it a
    -- description of the current filter rather than history.
    origin TEXT NOT NULL DEFAULT '{}',
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
    presentation: dict
    created_at: str
    # LAST, AND DEFAULTED, so that every existing caller constructing
    # one positionally keeps working. Two test fixtures and a declared
    # trigger build these by position, and a required field in the
    # middle broke all three at once -- for a value none of them has.
    origin: dict = field(default_factory=dict)


class SavedViewStore:
    """One person's saved searches, readable by a scheduler."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        # THE MIGRATION IS THE FIX FOR A BUG THIS FILE SHIPPED. The
        # `presentation` column was added to SCHEMA alone, and a
        # database created before that returned no views at all.
        return connection_with_schema(
            self._db_path, SCHEMA,
            migrations=(
                add_column_if_missing(
                    "saved_views", "presentation", "TEXT NOT NULL DEFAULT '{}'",
                ),
                # AND THE SAME FOR `origin`, for the same reason. The
                # comment above is a record of what happens without
                # one: a database created before the column existed
                # returned no views at all.
                add_column_if_missing(
                    "saved_views", "origin", "TEXT NOT NULL DEFAULT '{}'",
                ),
            ),
        )

    def save(self, owner_user_id: str, name: str, object_type: str,
             query_text: str = "", conditions: list | None = None,
             presentation: dict | None = None,
             origin: dict | None = None) -> str | None:
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
                    "object_type, query_text, conditions, presentation, "
                    "origin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (view_id, owner_user_id, name, object_type, query_text,
                     json.dumps(conditions or []),
                     json.dumps(presentation or {}),
                     json.dumps(origin or {}),
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
                    "conditions, presentation, origin, created_at FROM saved_views "
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
                    "conditions, presentation, origin, created_at FROM saved_views "
                    "WHERE view_id = ?",
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
        try:
            presentation = json.loads(row["presentation"])
        except (TypeError, json.JSONDecodeError):
            presentation = {}
        try:
            origin = json.loads(row["origin"])
        except (TypeError, json.JSONDecodeError, IndexError, KeyError):
            # THE SAME BARGAIN THE FILTERS GET, and one more exception
            # than they need: a row from before the migration ran has
            # no such column at all, and a view that vanished would be
            # blamed on the product where a missing trail will not be.
            origin = {}
        # BY KEYWORD, not by position. The positional form is what
        # made adding a field a breaking change for every caller, and
        # this one has to agree with the SELECT's column order as
        # well -- two orderings to keep in step instead of none.
        return SavedView(
            view_id=row["view_id"],
            name=row["name"],
            object_type=row["object_type"],
            query_text=row["query_text"],
            conditions=conditions,
            presentation=presentation,
            created_at=row["created_at"],
            origin=origin if isinstance(origin, dict) else {},
        )
