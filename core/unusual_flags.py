"""Records flagged as unusual for their kind, and what a person decided
about them (R51).

Flags in, decisions out, nothing changed on the way -- the shape of
rule_suggestions.py and enrichment_recipes.py. The sync REPLACES a type's
flags each time its gold is rebuilt (core/mirror/unusual_scan.py); the
decisions are kept apart, so they outlive the flags they were about.

"EXPECTED" IS REMEMBERED BY WHAT WAS JUDGED -- the record, the field and
the value -- so the flag does not come back while the value stays the
same, and does come back if it changes: a person who looked at 4,980
did not look at 49,800.

THE COMPARTMENT IS STORED AS JSON, so "none" and "" stay two facts, as
mediator.security_value_of keeps them.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.sqlite_connection import connection_with_schema

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS unusual_flags (
    object_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    field TEXT NOT NULL,
    compartment TEXT NOT NULL,
    value REAL NOT NULL,
    -- [[field, value], ...]: the kind it was compared within.
    kind TEXT NOT NULL,
    median REAL NOT NULL,
    low REAL NOT NULL,
    high REAL NOT NULL,
    group_size INTEGER NOT NULL,
    score REAL NOT NULL,
    found_at TEXT NOT NULL,
    PRIMARY KEY (object_type, record_id, field)
);
-- HOW MANY THERE WERE, per type and compartment, when more than the
-- MAX_FLAGS kept -- so a short list can say "and N more".
CREATE TABLE IF NOT EXISTS unusual_totals (
    object_type TEXT NOT NULL,
    compartment TEXT NOT NULL,
    total INTEGER NOT NULL,
    PRIMARY KEY (object_type, compartment)
);
CREATE TABLE IF NOT EXISTS unusual_decisions (
    object_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    field TEXT NOT NULL,
    value REAL NOT NULL,
    -- expected | worth_a_look
    decision TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    PRIMARY KEY (object_type, record_id, field, value)
);
"""

DECISIONS = ("expected", "worth_a_look")


@dataclass(frozen=True)
class StoredFlag:
    object_type: str
    record_id: str
    field: str
    compartment: Any
    value: float
    kind: tuple
    median: float
    low: float
    high: float
    group_size: int
    score: float
    found_at: str
    #: What a person decided about this value, if anything.
    decision: "str | None" = None
    decided_by: "str | None" = None

    def reason(self) -> str:
        from core.unusual import Flag

        return Flag(self.record_id, self.field, self.value, self.kind, self.median, self.low,
                    self.high, self.group_size, self.score).reason()


class UnusualFlagStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def replace(self, object_type: str, by_compartment: dict) -> None:
        """A type's flags, as just found: {compartment: (flags, total)}.
        Every earlier flag of the type goes, in one transaction -- a record
        no longer unusual is no longer flagged."""
        now = datetime.now(UTC).isoformat()
        with self._connection() as conn:
            conn.execute("DELETE FROM unusual_flags WHERE object_type = ?", (object_type,))
            conn.execute("DELETE FROM unusual_totals WHERE object_type = ?", (object_type,))
            for compartment, (flags, total) in by_compartment.items():
                key = json.dumps(compartment)
                conn.executemany(
                    "INSERT OR REPLACE INTO unusual_flags VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(object_type, flag.record_id, flag.field, key, flag.value,
                      json.dumps([list(pair) for pair in flag.kind], default=str), flag.median,
                      flag.low, flag.high, flag.group_size, flag.score, now) for flag in flags])
                conn.execute("INSERT INTO unusual_totals VALUES (?, ?, ?)",
                             (object_type, key, total))
            conn.commit()

    def flags(self, object_type: "str | None" = None,
              record_ids: "list[str] | None" = None) -> list[StoredFlag]:
        """Flags with their decisions, furthest first. Unfiltered by who
        may see them: the route decides that. An unreadable store flags
        nothing."""
        sql = ("SELECT f.*, d.decision, d.decided_by FROM unusual_flags f "
               "LEFT JOIN unusual_decisions d ON d.object_type = f.object_type AND "
               "d.record_id = f.record_id AND d.field = f.field AND d.value = f.value")
        clauses, params = [], []
        if object_type is not None:
            clauses.append("f.object_type = ?")
            params.append(object_type)
        if record_ids is not None:
            if not record_ids:
                return []
            clauses.append(f"f.record_id IN ({','.join('?' * len(record_ids))})")
            params.extend(record_ids)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ABS(f.score) DESC, f.record_id, f.field"
        try:
            with self._connection() as conn:
                rows = conn.execute(sql, params).fetchall()
        except Exception as e:  # noqa: BLE001 - an unreadable store flags nothing
            logger.warning("could not read unusual flags: %s", e)
            return []
        return [StoredFlag(
            row["object_type"], row["record_id"], row["field"], json.loads(row["compartment"]),
            row["value"], tuple(tuple(pair) for pair in json.loads(row["kind"])), row["median"],
            row["low"], row["high"], row["group_size"], row["score"], row["found_at"],
            row["decision"], row["decided_by"]) for row in rows]

    def totals(self, object_type: str) -> dict:
        """{compartment: how many were found}."""
        try:
            with self._connection() as conn:
                rows = conn.execute("SELECT compartment, total FROM unusual_totals WHERE "
                                    "object_type = ?", (object_type,)).fetchall()
        except Exception:  # noqa: BLE001
            return {}
        return {json.loads(row["compartment"]): row["total"] for row in rows}

    def decide(self, object_type: str, record_id: str, field: str, value: float,
               decision: str, by: str) -> None:
        if decision not in DECISIONS:
            raise ValueError(f"A decision is one of {', '.join(DECISIONS)}.")
        with self._connection() as conn:
            conn.execute("INSERT OR REPLACE INTO unusual_decisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (object_type, record_id, field, value, decision, by,
                          datetime.now(UTC).isoformat()))
            conn.commit()
