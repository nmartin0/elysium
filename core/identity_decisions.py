"""Proposed merges, and what was decided about them (GOLD-6).

WHY A STORE AND NOT CONFIGURATION. FUSION_AND_IDENTITY.md is explicit:
"an approved inference becomes STORED DATA, not edited config",
because "if approving a merge rewrote ontology_schema.yaml, then
configuration -- the thing a human wrote and reviews -- would silently
grow entries nobody typed". CONFIG IS WHAT SOMEONE WROTE; DECISIONS
ARE WHAT THE SYSTEM WAS TOLD.

WHY A SEPARATE STORE FROM PENDING WRITES. A pending write is an ACTION
TYPE with parameters, bound for the customer's database through an
adapter. A merge changes nothing out there: it changes what Elysium
believes about who is who, and it is applied by the next gold build
rather than by an adapter. Sharing the table would mean teaching every
part of the write path about a write that writes nothing.

WHAT IT KEEPS, AND WHAT IT REFUSES TO KEEP:

  A PROPOSAL IS NEVER APPLIED BY BEING STORED. It waits. The only
  thing that merges anything is an APPROVED decision read at build
  time -- so "inference never decides" is enforced by there being no
  code path from a candidate to a merge that does not pass through a
  person.

  DECISIONS ARE APPEND-ONLY. Changing one's mind is a NEW decision
  about the same pair, and the previous one stays. That is what makes
  "why is this merged?" answerable a year later, and it is the same
  promise the write log and the changelog make.

  AND UNMERGING IS NOT A SPECIAL CASE. A rejected pair is a decision
  like any other; a pair approved and later rejected is two rows, and
  the latest one wins. FUSION_AND_IDENTITY calls this out: "if a merge
  is an approved write, UN-merging is another write, with the same
  trail".
"""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.sqlite_connection import connection_with_schema

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"

SCHEMA = """
CREATE TABLE IF NOT EXISTS merge_proposals (
    proposal_id   TEXT PRIMARY KEY,
    object_type   TEXT NOT NULL,
    left_id       TEXT NOT NULL,
    right_id      TEXT NOT NULL,
    score         REAL NOT NULL,
    agreement     TEXT NOT NULL,
    proposed_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS merge_proposals_type ON merge_proposals (object_type);

CREATE TABLE IF NOT EXISTS merge_decisions (
    decision_id   TEXT PRIMARY KEY,
    proposal_id   TEXT NOT NULL,
    decision      TEXT NOT NULL,
    decided_by    TEXT NOT NULL,
    decided_at    TEXT NOT NULL,
    note          TEXT
);
CREATE INDEX IF NOT EXISTS merge_decisions_proposal ON merge_decisions (proposal_id);
"""


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    object_type: str
    left_id: str
    right_id: str
    score: float
    agreement: str
    proposed_at: str
    decision: str = PENDING
    decided_by: str | None = None


class MergeDecisionStore:
    """Proposals in, decisions out, nothing applied on the way."""

    def __init__(self, database: Path):
        self._database = database
        with self._connection():
            pass  # Creates the schema on first use, via the helper.

    def _connection(self):
        """The project's own helper, which CLOSES what it opens.

        THIS USED TO BE A BARE sqlite3.connect() used as
        `with self._connection() as conn:`. That commits on a clean
        exit and does NOT close -- the documented Python behaviour, and
        a trap, because the `with` makes it look handled. MEASURED
        before fixing: 100 calls to propose()/decide() left 54 file
        descriptors open. run_sync.py builds this store on every sync
        and decides against it per candidate pair, so a large identity
        run ends in "Too many open files" and takes the sync with it.

        connection_with_schema() closes in a `finally`, and brings WAL,
        the per-connection query deadline and once-per-process schema
        verification with it -- none of which this store had while it
        opened its own connections.

        IT DOES NOT AUTO-COMMIT, which the bare connection did. Every
        writer below now commits explicitly; without that this fix
        would have quietly stopped persisting anything, which is worse
        than the leak.
        """
        return connection_with_schema(self._database, SCHEMA)

    def propose(self, object_type: str, left_id: str, right_id: str, score: float,
                agreement: str = "") -> str:
        """Record a candidate as awaiting a person. Returns its id.

        THE PAIR IS ORDERED before storing, so the same two records
        proposed from either direction are one proposal rather than
        two -- otherwise a reviewer decides the same merge twice and
        the second decision looks like a disagreement.
        """
        left, right = sorted((left_id, right_id))
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT proposal_id FROM merge_proposals "
                "WHERE object_type = ? AND left_id = ? AND right_id = ?",
                (object_type, left, right),
            ).fetchone()
            if existing is not None:
                return existing["proposal_id"]
            proposal_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO merge_proposals (proposal_id, object_type, left_id, right_id, "
                "score, agreement, proposed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (proposal_id, object_type, left, right, float(score), agreement,
                 datetime.now(UTC).isoformat()),
            )
            conn.commit()
            return proposal_id

    def decide(self, proposal_id: str, decision: str, decided_by: str,
               note: str | None = None) -> None:
        """Approve or reject. APPENDS: a change of mind is a new row."""
        if decision not in (APPROVED, REJECTED):
            raise ValueError(f"decision must be {APPROVED!r} or {REJECTED!r}, got {decision!r}.")
        with self._connection() as conn:
            if conn.execute("SELECT 1 FROM merge_proposals WHERE proposal_id = ?",
                            (proposal_id,)).fetchone() is None:
                raise ValueError(f"no such proposal: {proposal_id}")
            conn.execute(
                "INSERT INTO merge_decisions (decision_id, proposal_id, decision, "
                "decided_by, decided_at, note) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), proposal_id, decision, decided_by,
                 datetime.now(UTC).isoformat(), note),
            )
            conn.commit()

    def _latest_decisions(self, conn) -> dict[str, sqlite3.Row]:
        rows = conn.execute(
            "SELECT proposal_id, decision, decided_by, decided_at FROM merge_decisions "
            "ORDER BY decided_at, decision_id",
        ).fetchall()
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest[row["proposal_id"]] = row
        return latest

    def proposals(self, object_type: str | None = None,
                  decision: str | None = None) -> list[Proposal]:
        """Proposals with their CURRENT standing, newest decision wins."""
        with self._connection() as conn:
            latest = self._latest_decisions(conn)
            query = "SELECT * FROM merge_proposals"
            parameters: tuple = ()
            if object_type is not None:
                query += " WHERE object_type = ?"
                parameters = (object_type,)
            found = []
            for row in conn.execute(query + " ORDER BY proposed_at, proposal_id", parameters):
                decided = latest.get(row["proposal_id"])
                standing = decided["decision"] if decided else PENDING
                if decision is not None and standing != decision:
                    continue
                found.append(Proposal(
                    proposal_id=row["proposal_id"], object_type=row["object_type"],
                    left_id=row["left_id"], right_id=row["right_id"], score=row["score"],
                    agreement=row["agreement"], proposed_at=row["proposed_at"],
                    decision=standing,
                    decided_by=decided["decided_by"] if decided else None,
                ))
            return found

    def approved_pairs(self, object_type: str) -> list[tuple[str, str]]:
        """The merges a person has approved, for the next gold build.

        THE ONLY WAY A CANDIDATE EVER BECOMES A MERGE. A proposal that
        nobody decided returns nothing, which is what makes "inference
        never decides" a property of the code rather than a promise.
        """
        return [
            (proposal.left_id, proposal.right_id)
            for proposal in self.proposals(object_type, decision=APPROVED)
        ]
