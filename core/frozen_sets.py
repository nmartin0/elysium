"""Frozen sets: membership fixed at an instant (formerly BLOCKING 17, saved selections).

DEV_UI.md 11.3 decided the shape and left one question open. "Live by
default, frozen deliberately -- and both are named": HubSpot's active
and static lists, Amplitude's dynamic and static cohorts, Foundry's
object sets. A saved VIEW here is the live kind -- `saved_views.py`
stores its query, and membership is whatever matches when it is run.
This is the other kind.

THE OPEN QUESTION WAS WHAT A FROZEN SET PINS TO, and Foundry answers
it. Its static object sets "are saved as a list of primary keys" and
"will stay the same regardless of any changes to the input data";
dynamic ones are "a representation of the filters". So membership is
KEYS, and the values shown for those keys are read live, through the
mediator, with today's authority.

WHICH IS WHY "WHAT HAPPENS WHEN THE PUBLICATION IS FORGOTTEN" STOPS
BEING A QUESTION. DEV_UI 11.3 proposed pinning a frozen set to the
gold snapshot it was taken from, so it could reproduce the data as it
was -- an audit artefact HubSpot cannot offer. Pinned as a DEPENDENCY,
gold's retention would break every frozen set older than
`retain_publications`. Pinned as METADATA, nothing breaks: membership
never depended on it. The snapshot is recorded, shown ("frozen 14:22 ·
publication 7" in 11.4's words), and reported as forgotten when it is
-- a fact about the set, not a fault in it.

A MEMBER THAT CAN NO LONGER BE SHOWN IS COUNTED, NOT EXPLAINED. An id
may have been deleted, or may have left the reader's compartment, and
the two must look the same -- uniform denial. "3 of 40 are not shown"
is true and says nothing about which reason applies.

PRIVATE TO THEIR OWNER, for saved_views.py's reason: a list of ids says
those objects exist, which is the leak shape that rule exists for.

FOUNDRY'S DOCS ARE SILENT on what a static set does when a member is
deleted. The counting rule above is this project's own, from its own
uniform-denial principle rather than borrowed.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from core.sqlite_connection import connection_with_schema

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS frozen_sets (
    set_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    object_type TEXT NOT NULL,
    -- THE MEMBERSHIP. Primary keys, as Foundry's static sets store
    -- them, in the order they were frozen.
    member_ids TEXT NOT NULL,
    -- THE LIVE SET IT WAS TAKEN FROM, if it was taken from one, so it
    -- can be handed back to its criteria (DEV_UI 11.3: "conversion
    -- both ways"). Empty for a hand-picked selection, which has no
    -- criteria to hand back to.
    origin TEXT NOT NULL DEFAULT '{}',
    frozen_at TEXT NOT NULL,
    -- WHICH PUBLICATION THE MEMBERSHIP WAS READ FROM. Metadata, never
    -- a dependency; see the module docstring.
    gold_snapshot_id TEXT,
    published_at TEXT
)
"""


@dataclass(frozen=True)
class FrozenSet:
    set_id: str
    name: str
    object_type: str
    member_ids: list[str]
    frozen_at: str
    origin: dict = field(default_factory=dict)
    gold_snapshot_id: str | None = None
    published_at: str | None = None


class FrozenSetStore:
    """One person's frozen sets."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def freeze(self, owner_user_id: str, name: str, object_type: str,
               member_ids: list[str], origin: dict | None = None,
               gold_snapshot_id: str | None = None,
               published_at: str | None = None) -> str | None:
        """Stores one. Replaces an existing one of the same name.

        BY NAME, like a saved view, because that is how a person refers
        to it. Freezing "Q3 escalations" twice is re-taking it, not
        collecting two.

        THE IDS ARRIVE ALREADY AUTHORIZED. This module decides nothing
        about access; its caller resolved them through the mediator as
        the owner, so a set can never hold an id its owner could not see
        at the moment it was frozen.
        """
        set_id = str(uuid.uuid4())
        try:
            with self._connection() as conn:
                conn.execute(
                    "DELETE FROM frozen_sets WHERE owner_user_id = ? AND name = ?",
                    (owner_user_id, name),
                )
                conn.execute(
                    "INSERT INTO frozen_sets (set_id, owner_user_id, name, object_type, "
                    "member_ids, origin, frozen_at, gold_snapshot_id, published_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (set_id, owner_user_id, name, object_type,
                     json.dumps([str(member) for member in member_ids]),
                     json.dumps(origin or {}),
                     datetime.now(UTC).isoformat(),
                     gold_snapshot_id, published_at),
                )
                conn.commit()
        except Exception as e:  # noqa: BLE001 - a frozen set is a convenience
            logger.warning("could not freeze a set for %s: %s", owner_user_id, e)
            return None
        return set_id

    def for_owner(self, owner_user_id: str) -> list[FrozenSet]:
        """One person's frozen sets, newest first. Scoped in SQL."""
        return self._select("WHERE owner_user_id = ? ORDER BY frozen_at DESC",
                            (owner_user_id,))

    def get(self, owner_user_id: str, set_id: str) -> FrozenSet | None:
        """One set, if it belongs to this person.

        OWNER IN THE WHERE CLAUSE, unlike `SavedViewStore.get`, because
        nothing schedules over a frozen set yet and so nothing needs an
        unscoped read. Somebody else's set and no set are the same
        answer.
        """
        found = self._select("WHERE owner_user_id = ? AND set_id = ?",
                             (owner_user_id, set_id))
        return found[0] if found else None

    def delete(self, owner_user_id: str, set_id: str) -> bool:
        try:
            with self._connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM frozen_sets WHERE set_id = ? AND owner_user_id = ?",
                    (set_id, owner_user_id),
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:  # noqa: BLE001
            logger.warning("could not delete frozen set %s: %s", set_id, e)
            return False

    def _select(self, where: str, params: tuple) -> list[FrozenSet]:
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT set_id, name, object_type, member_ids, origin, frozen_at, "
                    f"gold_snapshot_id, published_at FROM frozen_sets {where}",
                    params,
                ).fetchall()
        except Exception as e:  # noqa: BLE001
            logger.warning("could not read frozen sets: %s", e)
            return []
        return [self._row(row) for row in rows]

    @staticmethod
    def _row(row) -> FrozenSet:
        try:
            members = [str(member) for member in json.loads(row["member_ids"])]
        except (TypeError, json.JSONDecodeError):
            # AN UNREADABLE MEMBERSHIP IS AN EMPTY ONE, and says so by
            # showing nothing -- never a guess at what it held.
            members = []
        try:
            origin = json.loads(row["origin"])
        except (TypeError, json.JSONDecodeError):
            origin = {}
        return FrozenSet(
            set_id=row["set_id"], name=row["name"], object_type=row["object_type"],
            member_ids=members, frozen_at=row["frozen_at"],
            origin=origin if isinstance(origin, dict) else {},
            gold_snapshot_id=row["gold_snapshot_id"], published_at=row["published_at"],
        )
