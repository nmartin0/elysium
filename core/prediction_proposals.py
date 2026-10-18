"""Proposed predictions, and what a person decided about them (R48).

A PROPOSAL is how a predicted field measured when it was trained: the
held-out score against the naive guess, the score per group, which
inputs mattered. NO MODEL IS KEPT -- a saved scikit-learn model is a
pickle, and loading one can run anything. An approval says "a model
trained this way, on these records, may fill this field", and the sync
trains afresh and measures again before it serves (core/predictions.py).

ONE MODEL PER COMPARTMENT (the owner, 17 October). A model learns
patterns from every record it is given, and a guess shown in one
compartment must not be shaped by records of another -- Foundry's rule
that "mandatory controls propagate through derivation". So each proposal
is for one security compartment: trained only on its records, filling
only its records, and seen and decided only by someone in it, as
enrichment recipes are (enrichment_recipes.py).

TIED TO THE QUESTION, as recipes are: each proposal records the
declaration hash (predicted_fields.declaration_hash). When the target,
the inputs or the shape change, `approved` stops returning it and the
field goes empty until a proposal for the new question is approved.

ONE APPROVED PROPOSAL PER QUESTION AND COMPARTMENT. Approving another
supersedes the one before -- recorded, not deleted.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.sqlite_connection import connection_with_schema

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS prediction_proposals (
    proposal_id TEXT PRIMARY KEY,
    object_type TEXT NOT NULL,
    field_name TEXT NOT NULL,
    declaration_hash TEXT NOT NULL,
    -- The security compartment, JSON-encoded: "null" for none, so None
    -- and "" stay two different facts (mediator.security_value_of).
    compartment TEXT NOT NULL,
    -- The held-out measurement, shown to the approver and compared with
    -- the sync's own at every retrain.
    evaluation TEXT NOT NULL,
    -- What produced it: the library, the seed, the records read.
    provenance TEXT NOT NULL DEFAULT '{}',
    -- proposed | approved | rejected | superseded
    status TEXT NOT NULL DEFAULT 'proposed',
    proposed_at TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS prediction_proposals_field
    ON prediction_proposals (object_type, field_name, status);
"""


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    object_type: str
    field_name: str
    declaration_hash: str
    compartment: Any
    evaluation: dict
    provenance: dict
    status: str
    proposed_at: str
    decided_by: str | None
    decided_at: str | None


class PredictionProposalStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def propose(self, object_type: str, field_name: str, declaration_hash: str,
                compartment: Any, evaluation: dict, provenance: dict) -> str:
        proposal_id = str(uuid.uuid4())
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO prediction_proposals (proposal_id, object_type, field_name, "
                "declaration_hash, compartment, evaluation, provenance, proposed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (proposal_id, object_type, field_name, declaration_hash,
                 json.dumps(compartment), json.dumps(evaluation), json.dumps(provenance),
                 datetime.now(UTC).isoformat()))
            conn.commit()
        return proposal_id

    def decide(self, proposal_id: str, approve: bool, by: str) -> "Proposal | None":
        """Approves or rejects a PROPOSED one; None if none is waiting.
        Approving supersedes the approved one for the same question and
        compartment, in the same transaction. Whether it MAY be approved
        is predictions.refusal's to say, before this is called."""
        now = datetime.now(UTC).isoformat()
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM prediction_proposals WHERE proposal_id = ? "
                               "AND status = 'proposed'", (proposal_id,)).fetchone()
            if row is None:
                return None
            if approve:
                conn.execute(
                    "UPDATE prediction_proposals SET status = 'superseded' WHERE object_type = ? "
                    "AND field_name = ? AND declaration_hash = ? AND compartment = ? "
                    "AND status = 'approved'",
                    (row["object_type"], row["field_name"], row["declaration_hash"],
                     row["compartment"]))
            conn.execute("UPDATE prediction_proposals SET status = ?, decided_by = ?, "
                         "decided_at = ? WHERE proposal_id = ?",
                         ("approved" if approve else "rejected", by, now, proposal_id))
            conn.commit()
        return self.get(proposal_id)

    def get(self, proposal_id: str) -> "Proposal | None":
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM prediction_proposals WHERE proposal_id = ?",
                               (proposal_id,)).fetchone()
        return _proposal(row) if row else None

    def all(self) -> list[Proposal]:
        """Every proposal, newest first; the route filters by who may see."""
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM prediction_proposals "
                                "ORDER BY proposed_at DESC").fetchall()
        return [_proposal(row) for row in rows]

    def approved(self, object_type: str, field_name: str,
                 declaration_hash: str) -> list[Proposal]:
        """The APPROVED proposal for exactly this question, one per
        compartment -- what the sync trains. An unreadable store approves
        nothing, and the field stays empty."""
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM prediction_proposals WHERE object_type = ? AND "
                    "field_name = ? AND declaration_hash = ? AND status = 'approved' "
                    "ORDER BY decided_at DESC",
                    (object_type, field_name, declaration_hash)).fetchall()
        except Exception as e:  # noqa: BLE001 - an unreadable store publishes nothing
            logger.warning("could not read prediction proposals: %s", e)
            return []
        latest: dict[str, Proposal] = {}
        for row in rows:
            latest.setdefault(row["compartment"], _proposal(row))
        return list(latest.values())


def _proposal(row) -> Proposal:
    return Proposal(
        proposal_id=row["proposal_id"], object_type=row["object_type"],
        field_name=row["field_name"], declaration_hash=row["declaration_hash"],
        compartment=json.loads(row["compartment"]),
        evaluation=json.loads(row["evaluation"] or "{}"),
        provenance=json.loads(row["provenance"] or "{}"), status=row["status"],
        proposed_at=row["proposed_at"], decided_by=row["decided_by"],
        decided_at=row["decided_at"])
