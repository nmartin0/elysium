"""Cleaning-rule suggestions a person accepts or dismisses (R31).

THE OWNER'S SHAPE, 14 Oct: a review queue, and the YAML stays the only
source of rules. scripts/suggest_declarations.py has always found values
that announce themselves as absences -- "N/A", 999-999-9999, 1900-01-01
-- and printed the YAML to declare. It forgot everything between runs,
so the same "N/A" in a free-text column, which somebody had already
judged to be a real sentence, came back every time.

SO THIS KEEPS THE JUDGEMENT, NOT THE RULE. A suggestion is accepted or
dismissed. Dismissed is remembered and never suggested again. Accepted
shows the exact YAML to add to ontology_schema.yaml; once the schema
declares it, the next scan marks it declared. Nothing here changes the
configuration or the data -- whether configuration may be written from
the UI is a separate, open decision.

A LEAF, like the other stores: it imports only the connection helper,
and knows nothing about bronze, schemas or who may decide.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.sqlite_connection import connection_with_schema

PENDING, ACCEPTED, DISMISSED, DECLARED = "pending", "accepted", "dismissed", "declared"
DECISIONS = (ACCEPTED, DISMISSED)

#: A value meaning "there was none", for null_if.
ABSENCE = "absence"
#: Dates outside anything the business has, for constraints min/max.
RANGE = "range"

SCHEMA = """
CREATE TABLE IF NOT EXISTS rule_suggestions (
    suggestion_id TEXT PRIMARY KEY,   -- a hash of type, field, kind, value
    object_type TEXT NOT NULL,
    field TEXT NOT NULL,
    kind TEXT NOT NULL,
    -- the value for an absence; '' for a range, which is per field
    value TEXT NOT NULL,
    -- what was seen: a count, why it looks wrong, examples for a range
    seen INTEGER NOT NULL,
    why TEXT NOT NULL,
    examples TEXT NOT NULL,
    state TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT,
    last_seen TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Suggestion:
    suggestion_id: str
    object_type: str
    field: str
    kind: str
    value: str
    seen: int
    why: str
    examples: tuple
    state: str
    decided_by: "str | None"
    decided_at: "str | None"
    last_seen: str


def suggestion_id(object_type: str, field: str, kind: str, value: str) -> str:
    """Stable across scans, and safe in a URL: a value such as "N/A"
    carries a slash, which a path parameter cannot."""
    import hashlib

    return hashlib.sha256("\x00".join((object_type, field, kind, value)).encode()).hexdigest()[:24]


class RuleSuggestionStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def record_scan(self, found: list[dict], declared: "set[str]") -> dict:
        """One scan's findings, merged in. Returns counts by outcome.

        `found`: {object_type, field, kind, value, seen, why, examples}.
        `declared`: suggestion ids the schema already declares.

        A DISMISSAL IS PERMANENT and a scan never reopens it: that is the
        memory this store exists for. A pending or accepted suggestion
        the schema now declares becomes DECLARED -- accepting it worked.
        Counts are refreshed on every scan, so the screen shows today's.
        """
        now = datetime.now(UTC).isoformat()
        outcome = {"new": 0, "updated": 0, "declared": 0, "kept_dismissed": 0}
        with self._connection() as conn:
            for item in found:
                sid = suggestion_id(item["object_type"], item["field"], item["kind"],
                                    item["value"])
                row = conn.execute("SELECT state FROM rule_suggestions WHERE suggestion_id = ?",
                                   (sid,)).fetchone()
                state = DECLARED if sid in declared else PENDING
                if row is None:
                    conn.execute(
                        "INSERT INTO rule_suggestions (suggestion_id, object_type, field, kind, "
                        "value, seen, why, examples, state, last_seen) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (sid, item["object_type"], item["field"], item["kind"], item["value"],
                         item["seen"], item["why"], json.dumps(list(item["examples"])),
                         state, now))
                    outcome["declared" if state == DECLARED else "new"] += 1
                    continue
                if row["state"] == DISMISSED:
                    outcome["kept_dismissed"] += 1
                    continue
                new_state = DECLARED if sid in declared else row["state"]
                conn.execute(
                    "UPDATE rule_suggestions SET seen = ?, why = ?, examples = ?, state = ?, "
                    "last_seen = ? WHERE suggestion_id = ?",
                    (item["seen"], item["why"], json.dumps(list(item["examples"])), new_state,
                     now, sid))
                outcome["declared" if new_state == DECLARED else "updated"] += 1
            conn.commit()
        return outcome

    def all(self) -> list[Suggestion]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM rule_suggestions ORDER BY object_type, field, kind, value"
            ).fetchall()
        return [Suggestion(row["suggestion_id"], row["object_type"], row["field"], row["kind"],
                           row["value"], row["seen"], row["why"],
                           tuple(json.loads(row["examples"])), row["state"],
                           row["decided_by"], row["decided_at"], row["last_seen"])
                for row in rows]

    def decide(self, sid: str, decision: str, by: str) -> bool:
        """Accept or dismiss. False for an unknown id or one already
        declared (the schema has settled it; there is nothing to decide)."""
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}, got {decision!r}")
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE rule_suggestions SET state = ?, decided_by = ?, decided_at = ? "
                "WHERE suggestion_id = ? AND state != ?",
                (decision, by, datetime.now(UTC).isoformat(), sid, DECLARED)).rowcount
            conn.commit()
        return bool(changed)
