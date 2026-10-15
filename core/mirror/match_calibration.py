"""Which waiting merges to pre-select, with a stated error rate (R57).

`auto_propose_above` is DECLARED: 0.95 was argued, never measured, and
R59's first run found two compared fields cannot even reach it. This
replaces "a number somebody chose" with "a set whose expected share of
wrong merges is at most the rate somebody chose" -- once there is
evidence to back it, and says UNCALIBRATED until then.

THE METHOD: conformal p-values against a reference set of known
non-matches, then Benjamini-Hochberg. Bates, Candes, Lei, Romano and
Sesia, "Testing for outliers with conformal p-values" (Annals of
Statistics, 2023): with n0 reference nulls exchangeable with the nulls
among the candidates,

    p(s) = (1 + #{reference scores >= s}) / (n0 + 1)

is a valid p-value, the p-values are PRDS, and BH at level alpha then
controls the false discovery rate at alpha. Here a "discovery" is a
pre-selected pair, and a false one is a pre-ticked wrong merge.

THE REFERENCE SET IS REVIEWERS' REJECTIONS, AND ONLY SOME OF THEM
(owner, 15 October):

  REJECTED, because those are the known non-matches.

  NOT PRE-SELECTED WHEN DECIDED. A pair shown already ticked tends to
  be approved because it was ticked; non-matches approved that way
  would be missing from the reference set, which would make every
  p-value too small. Only pairs scoring below the auto_propose_above in
  force -- the band nobody ticked for them -- count.

  SCORED THE SAME WAY AS TODAY'S CANDIDATES. A score is meaningful only
  against the weights, fields and prior that produced it (R62 records
  them per proposal); a rejection scored under other weights is a
  different distribution. The thresholds are part of the key too,
  since they decide which band a decision came from.

  AND THE CANDIDATES COME FROM THE SAME BAND. Exchangeability is the
  whole guarantee; a pending pair scoring above auto_propose_above has
  no reference null anywhere near it. Those stay pre-selected by the
  declared threshold, and the screen says which rule ticked which pair.

TOO FEW REJECTIONS IS UNCALIBRATED, NOT A WEAKER GUARANTEE. The
smallest p-value n0 rejections can produce is 1/(n0 + 1), so at alpha
0.05 nothing can be selected with fewer than 19. Below that, nothing
is calibrated and the declared threshold carries on as before.

19 IS A FLOOR. BH selects the k best of m waiting pairs when the k-th
smallest p-value is at most k * alpha / m. Ten waiting pairs that all
outscore every rejection are all selected with 19; ONE standout among
ten needs p <= 0.005, which takes 199. With few rejections it will
often tick nothing below the declared threshold -- the method declining
to claim more than thin evidence supports, not failing.
"""

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from core.identity_decisions import PENDING, REJECTED
from core.mirror.matching import DEFAULT_FALSE_MERGE_RATE

CALIBRATED = "calibrated"
UNCALIBRATED = "uncalibrated"

# What makes two scores comparable. NOT the Splink version -- declared
# weights give the same score across versions -- and not block_on,
# which decides which pairs are scored, not what they score.
_SCORING_KEYS = ("matcher", "m_probability", "u_probability", "prior", "compare",
                 "review_above", "auto_propose_above")


def rejections_needed(alpha: float) -> int:
    """The fewest reference nulls with which BH at `alpha` can select
    anything: the least n0 with 1/(n0 + 1) <= alpha."""
    return max(1, math.ceil(1 / alpha - 1 - 1e-9))


def scoring_key(provenance: "Mapping[str, Any] | None") -> "tuple | None":
    if not provenance or provenance.get("matcher") is None:
        return None
    return tuple(json.dumps(provenance.get(name), sort_keys=True) for name in _SCORING_KEYS)


def _provenance(proposal: Any) -> "dict | None":
    raw = getattr(proposal, "provenance", "") or ""
    try:
        found = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def conformal_p(score: float, reference: list[float]) -> float:
    return (1 + sum(1 for s in reference if s >= score)) / (len(reference) + 1)


def benjamini_hochberg(p_values: Mapping[str, float], alpha: float) -> frozenset[str]:
    """The ids BH selects at level alpha: the k smallest p-values, k the
    largest rank with p_(k) <= k * alpha / m."""
    ranked = sorted(p_values.items(), key=lambda item: item[1])
    m = len(ranked)
    cut = 0
    for rank, (_, p) in enumerate(ranked, start=1):
        if p <= rank * alpha / m:
            cut = rank
    return frozenset(name for name, _ in ranked[:cut])


@dataclass(frozen=True)
class Calibration:
    status: str
    false_merge_rate: float
    # Counts for the server-side report ONLY. Decisions span every
    # compartment, so a count shown in the browser would say how many
    # pairs exist that the viewer cannot see.
    rejections_used: int
    rejections_needed: int
    # Pending proposals BH selects; empty when uncalibrated.
    selected: frozenset[str] = field(default_factory=frozenset)
    # Pending proposals in the band that were considered.
    considered: int = 0


def calibrate(proposals: Iterable[Any], current_provenance: Mapping[str, Any],
              alpha: float = DEFAULT_FALSE_MERGE_RATE) -> Calibration:
    """Which of `proposals` (one type's, with their standing) to
    pre-select on the evidence of past rejections. See the module
    docstring for what counts as evidence and why."""
    needed = rejections_needed(alpha)
    key = scoring_key(current_provenance)
    auto = current_provenance.get("auto_propose_above") if current_provenance else None
    reference: list[float] = []
    candidates: dict[str, float] = {}
    if key is not None and auto is not None:
        for proposal in proposals:
            if scoring_key(_provenance(proposal)) != key:
                continue
            score = float(proposal.score)
            if score >= float(auto):
                continue  # pre-selected when shown: neither evidence nor candidate
            if proposal.decision == REJECTED:
                reference.append(score)
            elif proposal.decision == PENDING:
                candidates[proposal.proposal_id] = score
    if len(reference) < needed:
        return Calibration(UNCALIBRATED, alpha, len(reference), needed,
                           considered=len(candidates))
    selected = benjamini_hochberg(
        {pid: conformal_p(score, reference) for pid, score in candidates.items()}, alpha)
    return Calibration(CALIBRATED, alpha, len(reference), needed, selected, len(candidates))
