"""Notifications, in the product, per recipient.

WHAT A NOTIFICATION IS HERE: a row somebody will see next time they
look. Not an email, not a webhook. Both of those are places data
LEAVES the deployment, and each needs its own decision about what may
cross that line; in-product needs none, because nothing crosses.

ONE PER RECIPIENT, NEVER ONE SHARED. A notification carries only what
its recipient's own evaluation produced -- never a number computed
once and handed to several people. Filtering-after-assembly is where
these systems leak, because the unfiltered thing existed.

SO THERE IS NO "NOTIFICATION" OBJECT with a recipient list. There are
rows, each belonging to one person, each written from an evaluation
run as that person.

NOT A MESSAGE BUS. No delivery guarantees, no retries, no ordering
beyond newest-first. A missed notification is a row that was never
written, and the condition that would have written it will be checked
again on the next sync.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.sqlite_connection import connection_with_schema

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    notification_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail TEXT,
    seen INTEGER NOT NULL DEFAULT 0
);
-- Every read is "what is waiting for ME, newest first". One index on
-- the two columns every query uses together.
CREATE INDEX IF NOT EXISTS notifications_user_created
    ON notifications (user_id, created_at DESC);

-- WHAT A CONDITION LAST SAW, so a standing condition does not
-- re-notify on every sync. Keyed by the condition and the person,
-- because the same condition may be true for one recipient and not
-- another.
CREATE TABLE IF NOT EXISTS notification_state (
    condition_key TEXT NOT NULL,
    user_id TEXT NOT NULL,
    last_fired_at TEXT NOT NULL,
    last_summary TEXT NOT NULL,
    -- HOW MANY THE CONDITION MATCHED, last time, for this person.
    --
    -- A COUNT, NOT THE SET. Every alerting system worth copying stores
    -- state rather than results: Databricks keeps OK/TRIGGERED/ERROR
    -- per evaluation, Google Cloud compares a row count against a
    -- threshold over a lookback window, and the canonical
    -- change-detection pattern is a saved watermark.
    --
    -- WHICH MAKES PER-RECIPIENT STORAGE FREE. Storing each person's
    -- previous RESULT SET would be tens of thousands of ids times
    -- however many recipients; an integer each is nothing, and it is
    -- the only thing a "3 more than last time" notification needs.
    --
    -- NULL MEANS NEVER EVALUATED, which is not the same as zero. The
    -- first evaluation records a BASELINE and notifies nobody --
    -- otherwise every condition fires a flood on the day it is
    -- declared.
    last_count INTEGER,
    -- THE CONFIGURATION THIS COUNT WAS MEASURED UNDER.
    --
    -- A COUNT IS A FACT ABOUT WHAT ONE PERSON COULD SEE, and what a
    -- person can see is decided by policy.yaml -- which
    -- `source_digest` covers. So a count measured under one
    -- configuration is not comparable with one measured under
    -- another: somebody granted a new region sees more objects
    -- without anything having been added, and somebody who lost one
    -- sees fewer without anything having been removed.
    --
    -- BOTH DIRECTIONS, not only the fall. A grant change can make a
    -- count rise spuriously as easily as drop.
    last_digest TEXT,
    PRIMARY KEY (condition_key, user_id)
);
"""


@dataclass(frozen=True)
class Notification:
    notification_id: str
    created_at: str
    kind: str
    summary: str
    detail: str | None
    seen: bool


class NotificationStore:
    """Notifications, one row per recipient."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def notify(self, user_id: str, kind: str, summary: str,
               detail: str | None = None) -> str | None:
        """Writes one notification for one person.

        RETURNS THE ID, or None if it could not be written. Best-effort
        by design: a condition that fired is a fact about the
        deployment, and failing to record a notice about it should not
        stop whatever noticed.
        """
        notification_id = str(uuid.uuid4())
        try:
            with self._connection() as conn:
                conn.execute(
                    "INSERT INTO notifications (notification_id, user_id, "
                    "created_at, kind, summary, detail) VALUES (?, ?, ?, ?, ?, ?)",
                    (notification_id, user_id, datetime.now(UTC).isoformat(),
                     kind, summary, detail),
                )
                # EXPLICIT, because open_connection sets
                # isolation_level='': an implicit transaction is ROLLED
                # BACK on close unless committed. sync_attempts.py
                # learned this the hard way.
                conn.commit()
        except Exception as e:  # noqa: BLE001 - see the docstring
            logger.warning("could not write a notification for %s: %s",
                           user_id, e)
            return None
        return notification_id

    def for_user(self, user_id: str, limit: int = 50) -> list[Notification]:
        """What is waiting for one person, newest first.

        SCOPED BY user_id IN THE QUERY, not filtered afterwards. There
        is no call that returns everyone's notifications, so there is
        no privileged view for a bug to leak from.
        """
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT notification_id, created_at, kind, summary, "
                    "detail, seen FROM notifications WHERE user_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
        except Exception as e:  # noqa: BLE001
            logger.warning("could not read notifications for %s: %s", user_id, e)
            return []
        return [
            Notification(
                row["notification_id"], row["created_at"], row["kind"],
                row["summary"], row["detail"], bool(row["seen"]),
            )
            for row in rows
        ]

    def mark_seen(self, user_id: str, notification_id: str) -> bool:
        """Marks one notification seen, if it belongs to this person.

        THE user_id IS IN THE WHERE CLAUSE, so marking somebody else's
        notification seen is not a permission failure -- it matches no
        row. A check that compared ownership in Python would be a
        second, weaker copy of the same rule.
        """
        try:
            with self._connection() as conn:
                cursor = conn.execute(
                    "UPDATE notifications SET seen = 1 WHERE notification_id = ? "
                    "AND user_id = ?",
                    (notification_id, user_id),
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:  # noqa: BLE001
            logger.warning("could not mark %s seen: %s", notification_id, e)
            return False

    def unseen_count(self, user_id: str) -> int:
        try:
            with self._connection() as conn:
                return conn.execute(
                    "SELECT count(*) FROM notifications WHERE user_id = ? "
                    "AND seen = 0",
                    (user_id,),
                ).fetchone()[0]
        except Exception as e:  # noqa: BLE001
            logger.warning("could not count notifications for %s: %s", user_id, e)
            return 0

    def already_notified(self, condition_key: str, user_id: str,
                         summary: str) -> bool:
        """Whether this person has already been told this same thing.

        A STANDING CONDITION IS TRUE UNTIL SOMEBODY FIXES IT. A sync
        that has been failing for a week is still failing on the
        hundredth check, and a notification per check is a channel
        nobody reads by the time it matters.

        COMPARES THE SUMMARY, not just the key: "3 tables stale"
        becoming "5 tables stale" is news, and the same text is not.
        """
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT last_summary FROM notification_state WHERE "
                    "condition_key = ? AND user_id = ?",
                    (condition_key, user_id),
                ).fetchone()
        except Exception as e:  # noqa: BLE001
            logger.warning("could not read notification state: %s", e)
            # CANNOT SAY MEANS NOTIFY. A duplicate notice is a smaller
            # failure than a silent one.
            return False
        return row is not None and row["last_summary"] == summary

    def last_measurement(self, condition_key: str,
                         user_id: str) -> tuple[int | None, str | None]:
        """The last count AND the configuration it was taken under.

        BOTH OR NEITHER. A count without its configuration cannot be
        compared safely, so they are read together and a caller cannot
        accidentally use one without the other.
        """
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT last_count, last_digest FROM notification_state "
                    "WHERE condition_key = ? AND user_id = ?",
                    (condition_key, user_id),
                ).fetchone()
        except Exception as e:  # noqa: BLE001
            logger.warning("could not read notification state: %s", e)
            return None, None
        if row is None:
            return None, None
        return row["last_count"], row["last_digest"]

    def last_count(self, condition_key: str, user_id: str) -> int | None:
        """How many this condition matched for this person last time.

        None MEANS NEVER EVALUATED, which is not the same as zero. A
        condition evaluated for the first time must record a BASELINE
        and notify nobody -- otherwise every condition fires a flood
        on the day it is declared, which a monitoring tool that hit it
        states plainly: "the first successful run creates a baseline,
        never a flood of fake new ads".
        """
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT last_count FROM notification_state WHERE "
                    "condition_key = ? AND user_id = ?",
                    (condition_key, user_id),
                ).fetchone()
        except Exception as e:  # noqa: BLE001
            logger.warning("could not read notification state: %s", e)
            # CANNOT SAY MEANS TREAT AS NEW, which records a baseline
            # and stays quiet. The alternative -- treating it as zero --
            # would report every match as a gain.
            return None
        return None if row is None else row["last_count"]

    def record_count(self, condition_key: str, user_id: str,
                     count: int, digest: str | None = None) -> None:
        """Records what this person's evaluation matched, this time.

        WRITTEN WHETHER OR NOT ANYTHING WAS SENT. A condition that
        stopped matching still moved, and the next evaluation compares
        against where it actually is rather than where it last made
        news.
        """
        try:
            with self._connection() as conn:
                conn.execute(
                    "INSERT INTO notification_state (condition_key, user_id, "
                    "last_fired_at, last_summary, last_count, last_digest) "
                    "VALUES (?, ?, ?, '', ?, ?) "
                    "ON CONFLICT(condition_key, user_id) DO UPDATE SET "
                    "last_count = excluded.last_count, "
                    "last_digest = excluded.last_digest",
                    (condition_key, user_id, datetime.now(UTC).isoformat(),
                     count, digest),
                )
                conn.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("could not record a count: %s", e)

    def record_notified(self, condition_key: str, user_id: str,
                        summary: str) -> None:
        try:
            with self._connection() as conn:
                conn.execute(
                    # UPSERT, NOT "INSERT OR REPLACE". Replace deletes
                    # the row and inserts a new one, which silently
                    # wiped last_count -- a condition would record a
                    # baseline, notify, and then compare against
                    # nothing on the next evaluation. Found by probing
                    # the two methods together rather than apart.
                    "INSERT INTO notification_state (condition_key, user_id, "
                    "last_fired_at, last_summary) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(condition_key, user_id) DO UPDATE SET "
                    "last_fired_at = excluded.last_fired_at, "
                    "last_summary = excluded.last_summary",
                    (condition_key, user_id, datetime.now(UTC).isoformat(),
                     summary),
                )
                conn.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("could not record notification state: %s", e)
