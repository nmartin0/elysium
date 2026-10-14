"""Questions that stopped to wait for a human decision (WIRED-2, AL-12).

THE GAP. When the agent proposes a write that needs approval, the run
ENDS: /query answers 202 with the proposal, and the question goes
unanswered. AgentLoop.resume could carry on after a decision -- built
and tested -- but nothing called it, because two things were missing:
somewhere to keep the paused question while a person decided, and a
decision about who receives the answer. The owner decided the second on
14 Oct: the ASKER, as a notification.

THIS IS THE FIRST. One row per paused write, holding what resume needs
that a PendingWrite does not: the question as asked, what was gathered
before the pause, and the hops already spent (a resume continues that
budget rather than being handed a fresh one).

WHAT IT DOES NOT HOLD IS AUTHORITY. The asker's record is NOT stored:
resume re-resolves them from the user directory before reading anything,
because a decision can take hours and their grants can change in that
time (agentic_loop.resume's docstring). A store that kept the record
would be a second place authorisation could go stale.

GATHERED IS JSON, AND LOSES TYPES ON PURPOSE. A Decimal or a date
becomes its text. Everything gathered is about to be shown to a model,
which reads text; core/llm/prompt_values renders values the same way.

TAKEN, NOT READ. take() removes the row in the same transaction it
returns it, so two workers deciding the same write cannot both resume
it.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.erased_ids import any_erased, ids_in_gathered
from core.sqlite_connection import connection_with_schema

logger = logging.getLogger(__name__)

#: How long a paused question waits. Longer than any write's approval
#: window; a row left past it is a question whose write was never decided.
KEEP_FOR = timedelta(days=7)

SCHEMA = """
CREATE TABLE IF NOT EXISTS paused_queries (
    write_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    gathered TEXT NOT NULL,
    hops_used INTEGER NOT NULL,
    fabricated_finishes TEXT NOT NULL,
    paused_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class PausedQuery:
    write_id: str
    user_id: str
    query_text: str
    gathered: list
    hops_used: int
    fabricated_finishes: tuple


class PausedQueryStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def save(self, write_id: str, user_id: str, query_text: str, gathered: list,
             hops_used: int, fabricated_finishes=()) -> None:
        now = datetime.now(UTC)
        with self._connection() as conn:
            conn.execute("DELETE FROM paused_queries WHERE paused_at < ?",
                         ((now - KEEP_FOR).isoformat(),))
            conn.execute(
                "INSERT OR REPLACE INTO paused_queries (write_id, user_id, query_text, "
                "gathered, hops_used, fabricated_finishes, paused_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (write_id, user_id, query_text, json.dumps(gathered, default=str),
                 int(hops_used), json.dumps(list(fabricated_finishes)), now.isoformat()),
            )
            conn.commit()

    def take(self, write_id: str) -> "PausedQuery | None":
        """The paused question for this write, removed as it is returned."""
        with self._connection() as conn:
            row = conn.execute(
                "DELETE FROM paused_queries WHERE write_id = ? RETURNING user_id, query_text, "
                "gathered, hops_used, fabricated_finishes", (write_id,)).fetchone()
            conn.commit()
        if row is None:
            return None
        return PausedQuery(write_id, row["user_id"], row["query_text"], json.loads(row["gathered"]),
                           row["hops_used"], tuple(json.loads(row["fabricated_finishes"])))

    def forget_erased(self, key_hash, hashes_by_type: dict,
                      withdrawn: "frozenset[str] | set[str]" = frozenset()) -> list[str]:
        """Drops every paused question that read an erased object, or
        whose write was withdrawn for one (R13). Returns, per question
        dropped, the user who asked it -- so they can be told without
        being told whom it concerned.

        THE WHOLE QUESTION, NOT THE ENTRIES. What was read about one
        person shaped every step after it, and the question text may
        name them; a question with them cut out would be finished as if
        they had never been asked about, which is an answer to a
        different question.
        """
        if not hashes_by_type and not withdrawn:
            return []
        with self._connection() as conn:
            rows = conn.execute("SELECT write_id, user_id, gathered FROM paused_queries").fetchall()
            doomed = []
            for row in rows:
                try:
                    gathered = json.loads(row["gathered"])
                except (TypeError, json.JSONDecodeError):
                    gathered = []
                if row["write_id"] in withdrawn or any_erased(
                        key_hash, hashes_by_type, ids_in_gathered(gathered)):
                    doomed.append((row["write_id"], row["user_id"]))
            conn.executemany("DELETE FROM paused_queries WHERE write_id = ?",
                             [(write_id,) for write_id, _ in doomed])
            conn.commit()
        return [user_id for _, user_id in doomed]
