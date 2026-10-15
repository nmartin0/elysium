"""The matching pipeline as a cascade (R56).

    1. RULE           identity.match_on, exact on canonical keys. Decides;
                      the gold build merges without asking (identity.py).
    2. BLOCKING       which of the remaining pairs are compared at all
                      (block_on; several entries are OR'd).
    3. SCORING        Fellegi-Sunter with DECLARED weights, a field
                      exact, close (if declared fuzzy) or different.
    4. A PERSON       everything scoring above review_above, pre-selected
                      as R57 allows. Nothing is merged without one.

EACH STAGE SEES ONLY WHAT THE ONES BEFORE IT LEFT UNDECIDED. That is
what makes it a cascade rather than four opinions. Stages 2 to 4 are
the record-linkage pipeline of Christen's *Data Matching* (2012, ch. 2):
indexing, comparison, classification, clerical review. Stage 1 first
is this project's own rule, from the fusion-and-identity design: "THE
DECLARED RULE IS THE PRIMARY PATH", and inference "only ever ADDS
PROPOSALS to" it.

FOUND MISSING WHEN THIS WAS BUILT: stage 3 scored pairs stage 1 had
already merged. Two records sharing an email were merged by the rule
and ALSO sent to a reviewer, who was asked to decide what was decided.
Approving did nothing and rejecting did nothing (the rule wins at build
time), so the queue carried work with no effect -- and since R57 a
rejection there would have been read as calibration evidence about a
pair the matcher was never really judging.

NO LLM STAGE (owner, 15 October). If R59's harness shows a band that
fuzzy comparison cannot settle, an LLM may be added as a note on the
review card, never a score.

THE HARNESS SCORES THE WHOLE CASCADE: a rule pair counts as found, at
score 1.0, labelled by stage, so recall is what the pipeline achieves
rather than what one stage of it does.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.mirror.identity import _match_key, rule_for
from core.mirror.matching import Candidate

RULE = "rule"
PROBABILISTIC = "probabilistic"


@dataclass(frozen=True)
class Staged:
    candidate: Candidate
    stage: str

    # The harness reads candidates by these; a Staged passes for one.
    @property
    def left_id(self) -> str:
        return self.candidate.left_id

    @property
    def right_id(self) -> str:
        return self.candidate.right_id

    @property
    def score(self) -> float:
        return self.candidate.score

    @property
    def agreement(self):
        return self.candidate.agreement


def _record_ids(type_def: dict, rows_by_storage: dict) -> "list[tuple[str, Any, dict]]":
    """(record id as the matcher names it, storage key, row)."""
    storages: dict[Any, dict] = {None: type_def["storage"]}
    storages.update(type_def.get("additional_storage") or {})
    found = []
    for storage_key, storage in storages.items():
        prefix = "primary" if storage_key is None else str(storage_key)
        for row in rows_by_storage.get(storage_key) or []:
            found.append((f"{prefix}:{row.get(storage['id_column'])}", storage_key, row))
    return found


def rule_groups(type_def: dict, rows_by_storage: dict) -> dict[str, tuple]:
    """Record id -> the declared key it shares with at least one other
    record. Records whose key is unique, or missing, are absent: the
    rule decided nothing about them."""
    rule = rule_for(type_def)
    if rule is None:
        return {}
    keyed: dict[tuple, list[str]] = {}
    for record, storage_key, row in _record_ids(type_def, rows_by_storage):
        key = _match_key(row, rule, type_def, storage_key)
        if key is not None:
            keyed.setdefault(key, []).append(record)
    return {record: key for key, records in keyed.items() if len(records) > 1
            for record in records}


def cascade(type_def: dict, rows_by_storage: dict,
            score: Callable[..., list[Candidate]],
            at_least: "float | None" = None,
            include_rule: bool = False) -> list[Staged]:
    """Run the stages. `score` is stage 3 -- a CandidateMatcher's
    `candidates` -- called with `at_least`.

    For PROPOSALS (`include_rule=False`, the sync): only what scoring
    found among pairs the rule left undecided. For the HARNESS
    (`include_rule=True`): the rule's pairs too, at 1.0, so recall is
    the pipeline's.
    """
    groups = rule_groups(type_def, rows_by_storage)
    staged: list[Staged] = []
    if include_rule:
        members: dict[tuple, list[str]] = {}
        for record, key in groups.items():
            members.setdefault(key, []).append(record)
        rule = rule_for(type_def)
        agreed = {name: True for name in (rule.match_on if rule else ())}
        for records in members.values():
            ordered = sorted(records)
            for i, left in enumerate(ordered):
                for right in ordered[i + 1:]:
                    staged.append(Staged(Candidate(left, right, 1.0, dict(agreed)), RULE))
    for candidate in score(type_def, rows_by_storage, at_least=at_least):
        same = groups.get(candidate.left_id)
        if same is not None and same == groups.get(candidate.right_id):
            continue  # decided by stage 1
        staged.append(Staged(candidate, PROBABILISTIC))
    return staged
