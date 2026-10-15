"""Proposed enrichment recipes, and what a person decided about them (R41).

A RECIPE is the rules a model compiled for one enriched field, with how
they scored against the model's own answers on a sample. Proposals in,
decisions out, nothing applied on the way -- the same shape as
identity_decisions.py: the sync reads only APPROVED recipes into gold.

TIED TO THE QUESTION. Each recipe records the declaration hash it was
compiled for (enriched_fields.declaration_hash). An approval answers
"may these rules answer THAT question", so when the author changes the
instruction, the inputs or the choices, `approved_rules` stops returning
it and the field goes empty until a recipe for the new question is
approved. Old decisions stay readable; they just no longer apply.

ONE APPROVED RECIPE PER QUESTION. Approving another supersedes the one
before -- recorded, not deleted, so "what were these values chosen by
last month" still has an answer.
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
CREATE TABLE IF NOT EXISTS enrichment_recipes (
    recipe_id TEXT PRIMARY KEY,
    object_type TEXT NOT NULL,
    field_name TEXT NOT NULL,
    declaration_hash TEXT NOT NULL,
    rules TEXT NOT NULL,
    -- How the rules scored against the model's direct answers on the
    -- sample: sizes, coverage, agreement. Shown to the approver.
    evaluation TEXT NOT NULL DEFAULT '{}',
    -- What produced it (R62's rule for anything statistical): the
    -- model, the sample size, the candidates tried.
    provenance TEXT NOT NULL DEFAULT '{}',
    -- proposed | approved | rejected | superseded
    status TEXT NOT NULL DEFAULT 'proposed',
    proposed_at TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS enrichment_recipes_field
    ON enrichment_recipes (object_type, field_name, status);
-- THE MODEL'S DIRECT ANSWERS ON SAMPLED ROWS, kept so a second compile
-- re-asks nothing it already has: a call takes minutes on a CPU. Keyed by
-- everything that would change the answer -- the question, the model,
-- the prompt, the row's inputs. `answer` is NULL for "the record does
-- not say"; an unusable reply is never stored, so it is asked again.
CREATE TABLE IF NOT EXISTS enrichment_labels (
    declaration_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    answer TEXT,
    PRIMARY KEY (declaration_hash, model, prompt, input_hash)
);
"""

STATUSES = ("proposed", "approved", "rejected", "superseded")


@dataclass(frozen=True)
class Recipe:
    recipe_id: str
    object_type: str
    field_name: str
    declaration_hash: str
    rules: list
    evaluation: dict
    provenance: dict
    status: str
    proposed_at: str
    decided_by: str | None
    decided_at: str | None


class EnrichmentRecipeStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def propose(self, object_type: str, field_name: str, declaration_hash: str,
                rules: list, evaluation: dict, provenance: dict) -> str:
        """Stores a proposal. The rules must already have passed
        enriched_fields.check_rules -- this stores, it does not judge."""
        recipe_id = str(uuid.uuid4())
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO enrichment_recipes (recipe_id, object_type, field_name, "
                "declaration_hash, rules, evaluation, provenance, proposed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (recipe_id, object_type, field_name, declaration_hash, json.dumps(rules),
                 json.dumps(evaluation), json.dumps(provenance), datetime.now(UTC).isoformat()))
            conn.commit()
        return recipe_id

    def decide(self, recipe_id: str, approve: bool, by: str) -> "Recipe | None":
        """Approves or rejects a PROPOSED recipe; None if there is no such
        proposal waiting. Approving supersedes any approved recipe for
        the same question, in the same transaction."""
        now = datetime.now(UTC).isoformat()
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM enrichment_recipes WHERE recipe_id = ? "
                               "AND status = 'proposed'", (recipe_id,)).fetchone()
            if row is None:
                return None
            if approve:
                conn.execute(
                    "UPDATE enrichment_recipes SET status = 'superseded' WHERE object_type = ? "
                    "AND field_name = ? AND declaration_hash = ? AND status = 'approved'",
                    (row["object_type"], row["field_name"], row["declaration_hash"]))
            conn.execute("UPDATE enrichment_recipes SET status = ?, decided_by = ?, "
                         "decided_at = ? WHERE recipe_id = ?",
                         ("approved" if approve else "rejected", by, now, recipe_id))
            conn.commit()
        return self.get(recipe_id)

    def get(self, recipe_id: str) -> "Recipe | None":
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM enrichment_recipes WHERE recipe_id = ?",
                               (recipe_id,)).fetchone()
        return _recipe(row) if row else None

    def all(self) -> list[Recipe]:
        """Every recipe, newest first. The route filters by what the
        caller may see; there is no owner, as with merge proposals."""
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM enrichment_recipes "
                                "ORDER BY proposed_at DESC").fetchall()
        return [_recipe(row) for row in rows]

    def approved_rules(self, object_type: str, field_name: str,
                       declaration_hash: str) -> "list | None":
        """The rules gold applies, or None: only an APPROVED recipe for
        exactly this declaration counts."""
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT rules FROM enrichment_recipes WHERE object_type = ? AND "
                    "field_name = ? AND declaration_hash = ? AND status = 'approved' "
                    "ORDER BY decided_at DESC LIMIT 1",
                    (object_type, field_name, declaration_hash)).fetchone()
        except Exception as e:  # noqa: BLE001 - an unreadable store publishes nothing
            logger.warning("could not read enrichment recipes: %s", e)
            return None
        return json.loads(row["rules"]) if row else None


def _recipe(row) -> Recipe:
    return Recipe(
        recipe_id=row["recipe_id"], object_type=row["object_type"],
        field_name=row["field_name"], declaration_hash=row["declaration_hash"],
        rules=json.loads(row["rules"]), evaluation=json.loads(row["evaluation"] or "{}"),
        provenance=json.loads(row["provenance"] or "{}"), status=row["status"],
        proposed_at=row["proposed_at"], decided_by=row["decided_by"],
        decided_at=row["decided_at"])


class EnrichmentLabelCache:
    """The model's direct answers, by what they answered. MISSING means
    never asked (or asked and unusable); None means "the record does not
    say" -- two different things."""

    MISSING = object()

    def __init__(self, db_path: Path, declaration_hash: str, model: str, prompt: str):
        self._db_path = db_path
        self._key = (declaration_hash, model, prompt)

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def get(self, input_hash: str):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT answer FROM enrichment_labels WHERE declaration_hash = ? AND model = ? "
                "AND prompt = ? AND input_hash = ?", (*self._key, input_hash)).fetchone()
        return self.MISSING if row is None else row["answer"]

    def put(self, input_hash: str, answer: "str | None") -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO enrichment_labels (declaration_hash, model, prompt, "
                "input_hash, answer) VALUES (?, ?, ?, ?, ?)", (*self._key, input_hash, answer))
            conn.commit()
