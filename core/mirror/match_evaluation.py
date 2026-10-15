"""How good the matcher is, measured against labels (R59).

    python -m scripts.evaluate_matching Customer --synthetic 40
    python -m scripts.evaluate_matching Customer --labels pairs.csv
    python -m scripts.evaluate_matching Customer --decisions

IT DECIDES NOTHING AND CHANGES NOTHING. It scores a matcher's candidates
against pairs whose answer is known, at every threshold the matcher can
actually produce, and says how sure the numbers are.

PRECEDENT. Splink's own `accuracy_analysis_from_labels_table` takes the
same input -- labelled pairs, `unique_id_l, unique_id_r,
clerical_match_score` -- and gives precision and recall by threshold;
the file format here accepts its column names. It is not called
directly because it scores only Splink, and R56's cascade will put
other stages in front of it that need the same yardstick: this scores
anything satisfying `CandidateMatcher`. Pairs completeness -- the share
of true matches blocking let through to be scored at all -- is the
measure Christen's *Data Matching* (2012, ch. 7) gives for blocking,
which recordlinkage also implements.

THREE SOURCES OF LABELS, AND THEY DO NOT MEASURE THE SAME THING:

  CLUSTERS or SYNTHETIC copies are EXHAUSTIVE: every pair in the
  universe they cover has a known answer, so a true match the matcher
  never proposed is a miss, and recall is measurable.

  A PAIRS FILE, or REVIEWERS' DECISIONS, label only the pairs someone
  chose to label. A decision exists only for a pair the matcher already
  proposed, so the pairs it MISSED are exactly the ones nobody
  labelled. Recall from them would be "of the matches we found, how
  many did we find" -- always 100%, and meaningless. It is reported as
  NOT MEASURABLE rather than as that number.

SMALL SAMPLES GET INTERVALS, NOT BARE PERCENTAGES. The development
deployment has three seeded duplicates; "precision 100%" from three
pairs is a statement nobody should act on. Every rate carries a 95%
Wilson score interval, which Brown, Cai and DasGupta (2001, "Interval
Estimation for a Binomial Proportion") recommend over the textbook
normal interval precisely because that one collapses to zero width at
0% and 100% -- the two values a tiny sample most often produces.
"""

import math
import random
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

Pair = tuple[str, str]


def pair(left: str, right: str) -> Pair:
    """One pair, the same whichever way round it was named."""
    return (left, right) if left <= right else (right, left)


@dataclass(frozen=True)
class Labels:
    """What is known about which pairs are the same object.

    `verdict` answers True, False, or None for a pair outside what the
    labels cover. `matches` is every pair known to match, which is what
    recall and pairs completeness are counted against.
    """

    matches: frozenset[Pair]
    verdict: Callable[[Pair], "bool | None"]
    exhaustive: bool
    source: str
    # What each synthetic record had done to it, for the error listing:
    # a miss is far easier to judge knowing the copy lost its postcode.
    notes: Mapping[str, str] = field(default_factory=dict)


def labels_from_pairs(rows: Iterable[tuple[str, str, bool]], source: str) -> Labels:
    """Explicit pairs, each a match or not. NOT exhaustive."""
    known: dict[Pair, bool] = {}
    for left, right, is_match in rows:
        known[pair(left, right)] = bool(is_match)
    return Labels(
        matches=frozenset(p for p, v in known.items() if v),
        verdict=known.get,
        exhaustive=False,
        source=source,
    )


def labels_from_clusters(cluster_of: Mapping[str, Any], source: str) -> Labels:
    """Every record's entity. Exhaustive over the records named: two of
    them in the same cluster match, two in different clusters do not."""
    members: dict[Any, list[str]] = {}
    for record, cluster in cluster_of.items():
        members.setdefault(cluster, []).append(record)
    matches = frozenset(
        pair(group[i], group[j])
        for group in members.values()
        for i in range(len(group))
        for j in range(i + 1, len(group))
    )

    def verdict(p: Pair) -> "bool | None":
        left, right = p
        if left not in cluster_of or right not in cluster_of:
            return None
        return cluster_of[left] == cluster_of[right]

    return Labels(matches=matches, verdict=verdict, exhaustive=True, source=source)


def wilson(successes: int, trials: int, z: float = 1.959964) -> "tuple[float, float] | None":
    """The 95% Wilson score interval for successes/trials, or None when
    there were no trials -- no interval, rather than (0, 1)."""
    if trials <= 0:
        return None
    p = successes / trials
    denominator = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass(frozen=True)
class AtThreshold:
    """The matcher's record if every pair scoring at least `threshold`
    were called a match."""

    threshold: float
    true_positives: int
    false_positives: int
    # None when the labels cannot say what was missed.
    false_negatives: "int | None"
    # Predicted pairs the labels say nothing about. Not counted either
    # way; reported, because a large number means the labels do not
    # cover what the matcher is doing.
    unlabelled: int
    declared_as: str = ""

    @property
    def precision(self) -> "float | None":
        judged = self.true_positives + self.false_positives
        return self.true_positives / judged if judged else None

    @property
    def precision_interval(self) -> "tuple[float, float] | None":
        return wilson(self.true_positives, self.true_positives + self.false_positives)

    @property
    def recall(self) -> "float | None":
        if self.false_negatives is None:
            return None
        total = self.true_positives + self.false_negatives
        return self.true_positives / total if total else None

    @property
    def recall_interval(self) -> "tuple[float, float] | None":
        if self.false_negatives is None:
            return None
        return wilson(self.true_positives, self.true_positives + self.false_negatives)


@dataclass(frozen=True)
class Error:
    """One pair the matcher got wrong at the threshold examined."""

    left_id: str
    right_id: str
    kind: str  # "missed" or "false match"
    score: "float | None"  # None: blocking never compared the pair
    agreement: Mapping[str, "bool | None"]
    note: str = ""


@dataclass(frozen=True)
class Evaluation:
    source: str
    exhaustive: bool
    labelled_matches: int
    # True matches that blocking let through to be scored at all.
    # None when the labels are not exhaustive.
    compared_matches: "int | None"
    rows: tuple[AtThreshold, ...]
    errors: tuple[Error, ...]
    errors_at: "float | None"

    @property
    def pairs_completeness(self) -> "float | None":
        if self.compared_matches is None or not self.labelled_matches:
            return None
        return self.compared_matches / self.labelled_matches


def evaluate(candidates: Iterable[Any], labels: Labels,
             declared: "Mapping[str, float] | None" = None,
             errors_at: "float | None" = None) -> Evaluation:
    """Score candidates -- every pair the matcher COMPARED, whatever its
    score -- against labels.

    THE THRESHOLDS ARE THE SCORES THE MATCHER PRODUCED, plus the declared
    ones. With declared weights and exact comparisons a matcher yields a
    handful of distinct scores, one per agreement pattern; a sweep at
    0.01 steps would print fifty identical rows and hide that.

    THE CANDIDATES MUST INCLUDE THE LOW SCORES. Only pairs the matcher
    returned count as compared; a matcher filtered at its review
    threshold would make every lower-scoring true match look like a
    blocking miss. `SplinkMatcher.candidates(at_least=0.0)` is the call.
    """
    declared = dict(declared or {})
    scored: dict[Pair, Any] = {}
    for candidate in candidates:
        key = pair(candidate.left_id, candidate.right_id)
        if key not in scored or candidate.score > scored[key].score:
            scored[key] = candidate
    verdicts = {key: labels.verdict(key) for key in scored}
    compared_matches = (sum(1 for key in labels.matches if key in scored)
                        if labels.exhaustive else None)

    thresholds = sorted({c.score for c in scored.values()} | set(declared.values()),
                        reverse=True)
    named = {value: name for name, value in declared.items()}
    rows = []
    for threshold in thresholds:
        predicted = [key for key, c in scored.items() if c.score >= threshold]
        tp = sum(1 for key in predicted if verdicts[key] is True)
        fp = sum(1 for key in predicted if verdicts[key] is False)
        rows.append(AtThreshold(
            threshold=threshold,
            true_positives=tp,
            false_positives=fp,
            false_negatives=(len(labels.matches) - tp) if labels.exhaustive else None,
            unlabelled=sum(1 for key in predicted if verdicts[key] is None),
            declared_as=named.get(threshold, ""),
        ))

    errors: list[Error] = []
    if errors_at is not None:
        for key, candidate in sorted(scored.items()):
            called = candidate.score >= errors_at
            truth = verdicts[key]
            if called and truth is False:
                errors.append(_error(key, "false match", candidate, labels))
            elif not called and truth is True:
                errors.append(_error(key, "missed", candidate, labels))
        if labels.exhaustive:
            errors.extend(_error(key, "missed", None, labels)
                          for key in sorted(labels.matches) if key not in scored)
    return Evaluation(
        source=labels.source,
        exhaustive=labels.exhaustive,
        labelled_matches=len(labels.matches),
        compared_matches=compared_matches,
        rows=tuple(rows),
        errors=tuple(errors),
        errors_at=errors_at,
    )


def _error(key: Pair, kind: str, candidate: Any, labels: Labels) -> Error:
    note = "; ".join(labels.notes[i] for i in key if i in labels.notes)
    return Error(
        left_id=key[0], right_id=key[1], kind=kind,
        score=None if candidate is None else candidate.score,
        agreement=dict(candidate.agreement) if candidate is not None else {},
        note=note,
    )


# --- synthetic duplicates -------------------------------------------------

def _typo(value: str, rng: random.Random) -> str:
    """One keyboard slip: a character dropped, doubled, swapped with its
    neighbour, or replaced. The four edits Damerau (1964) found account
    for most single misspellings."""
    if len(value) < 2:
        return value + value
    i = rng.randrange(len(value) - 1)
    edit = rng.choice(("drop", "double", "swap", "replace"))
    if edit == "drop":
        return value[:i] + value[i + 1:]
    if edit == "double":
        return value[:i] + value[i] + value[i:]
    if edit == "swap":
        return value[:i] + value[i + 1] + value[i] + value[i + 2:]
    letters = "abcdefghijklmnopqrstuvwxyz0123456789"
    return value[:i] + rng.choice([c for c in letters if c != value[i].lower()]) + value[i + 1:]


def _abbreviate(value: str) -> "str | None":
    words = value.split()
    if len(words) < 2:
        return None
    return " ".join([words[0][0] + "."] + words[1:])


def _corrupt(value: Any, rng: random.Random) -> tuple[Any, str]:
    """A plausible re-entry of one value, and what was done to it."""
    if value is None:
        return None, ""
    text = str(value)
    options = ["typo", "blank"]
    if _abbreviate(text) is not None:
        options.append("abbreviated")
    choice = rng.choice(options)
    if choice == "blank":
        return None, "blank"
    if choice == "abbreviated":
        return _abbreviate(text), "abbreviated"
    return _typo(text, rng), "typo"


SYNTHETIC_PREFIX = "synthetic-"


def synthetic_duplicates(type_def: dict, rows_by_storage: Mapping[Any, list[dict]],
                         compare: Iterable[str], count: int, rate: float = 0.3,
                         seed: int = 0) -> tuple[dict[Any, list[dict]], Labels]:
    """Real rows copied with seeded damage, and labels saying which copy
    is which (R59).

    THE METHOD IS FEBRL'S AND GECO'S (Christen, *Data Matching*, 2012,
    ch. 8): take records, duplicate some, corrupt the duplicates the way
    re-entry does -- a typo, a blank, a forename cut to an initial. Each
    compared field of each copy is damaged with probability `rate`, so
    some copies are exact and some lose two fields; what was done is
    kept, and shown beside any miss.

    THE LABELS COVER ONLY PAIRS TOUCHING A COPY. A copy matches its
    original and nothing else. A pair of two ORIGINAL rows is
    unlabelled, because the data may already hold real duplicates --
    the development deployment seeds three -- and calling them
    non-matches would count the matcher finding them as an error.

    THE SAME ASSUMPTION, ONE STEP OUT, IS KEPT: a copy against any row
    but its original is labelled a non-match. If that row is a real
    duplicate of the original -- the same person in the CRM -- the
    matcher pairing it with the copy is right and is counted wrong.
    Every error names the original the copy came from, so a reader can
    see it; leaving those pairs unlabelled instead would leave false
    matches with nothing to be counted against.

    SAME RNG, SAME COPIES. `seed` makes a run repeatable, so two
    settings can be compared on identical data.
    """
    compare = tuple(compare)
    fields = type_def.get("fields") or {}
    id_column = type_def["storage"]["id_column"]
    originals = [row for row in rows_by_storage.get(None) or []
                 if row.get(id_column) is not None]
    rng = random.Random(seed)
    chosen = rng.sample(originals, min(count, len(originals)))
    copies: list[dict] = []
    origin: dict[str, str] = {}
    notes: dict[str, str] = {}
    for number, original in enumerate(chosen, start=1):
        copy = dict(original)
        copy_id = f"{SYNTHETIC_PREFIX}{number}"
        copy[id_column] = copy_id
        damage = []
        for name in compare:
            if rng.random() >= rate:
                continue
            column = (fields.get(name) or {}).get("column", name)
            copy[column], what = _corrupt(copy.get(column), rng)
            if what:
                damage.append(f"{name} {what}")
        copies.append(copy)
        record = f"primary:{copy_id}"
        origin[record] = f"primary:{original[id_column]}"
        notes[record] = f"{record} copies {origin[record]}: " + (
            ", ".join(damage) if damage else "exact copy")

    def verdict(p: Pair) -> "bool | None":
        left, right = p
        if left not in origin and right not in origin:
            return None
        return origin.get(left, left) == origin.get(right, right)

    rows = {key: list(value) for key, value in rows_by_storage.items()}
    rows[None] = list(rows.get(None) or []) + copies
    labels = Labels(
        matches=frozenset(pair(copy, original) for copy, original in origin.items()),
        verdict=verdict,
        exhaustive=True,
        source=f"{len(copies)} synthetic copies (damage rate {rate:g}, seed {seed})",
        notes=notes,
    )
    return rows, labels
