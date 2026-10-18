"""Learning a predicted field from the records whose answer is known (R48).

What a declaration means is core/ontology/predicted_fields.py. This is
the machinery: turning records into numbers a model can learn from,
training, and -- before anything is approved or served -- measuring.

GRADIENT-BOOSTED TREES (scikit-learn's HistGradientBoosting). On tables
of the size Elysium holds, "tree-based models remain state-of-the-art on
medium-sized data (~10K samples)" (Grinsztajn et al., NeurIPS 2022), and
these handle missing values and categories natively. Measured on two
threads: 0.3 s to train on 10,000 rows of 12 fields, 0.8 s on 100,000,
6.3 s on a million.

MEASURED ON RECORDS IT NEVER LEARNED FROM. A fifth of the known records
is held out -- the same fifth every time, for the same data, so a score
can be compared with the one approved -- and the model is judged on
them against the NAIVE GUESS: the most common answer, the average
chance, the typical number. SKILL is how much of the way from the naive
guess to perfect the model gets: 0 is no better than guessing, 1 is
never wrong, below 0 is worse than guessing. Nothing is offered for
approval at or below 0.

BROKEN DOWN BY GROUP. An average can hide a group the model fails: 93%
right for most customers and 60% for a small region still averages
well. The same held-out score is shown per value of a field the approver
chooses -- Foundry's evaluation "subsets", and Model Cards' "benchmarked
evaluation ... across different ... groups" (Mitchell et al., 2019) --
and a group too small to judge says so rather than showing a
percentage.

TOO GOOD TO BE TRUE is said, not trusted: a skill near 1 almost always
means an input carries the answer (a cancellation date beside
"cancelled"), and the evaluation says which input mattered most.

NEVER STORED AS A MODEL FILE. A saved scikit-learn model is a pickle,
and loading a pickle can run anything. The sync trains afresh from the
approved declaration (scripts/run_sync.py, with gold), with a fixed
seed, and measures again before it serves.
"""

import datetime
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from core.ontology.predicted_fields import Prediction

#: Fewer known answers than this and nothing is learned.
MIN_KNOWN = 50
#: The share of known records held out to judge the model.
HELD_OUT = 0.2
#: Fewer held-out records than this in a group and its score is not shown.
MIN_GROUP = 30
#: The most groups shown; the rest are summed as "other".
MAX_GROUPS = 20
#: A skill at or above this is too good to be true.
SUSPICIOUS_SKILL = 0.98
#: How far below its approved skill a retrained model may measure and
#: still fill its field. The same records give the same model and the same
#: skill exactly; new records move the held-out fifth, and with it the
#: score, a little either way. 0.05 is a judgement, not a measurement: it
#: lets the ordinary wobble of a growing table through, and stops a model
#: that has lost a twentieth of the way from guessing to perfect.
RETRAIN_TOLERANCE = 0.05
#: The most distinct values of a text input kept as categories; the rest
#: are "other" (the trees' own limit is 255 bins).
MAX_CATEGORIES = 200
SEED = 0
#: The category a blank text value is, kept apart from any real value.
EMPTY = "\x00empty"


class NotLearnable(ValueError):
    """There is not enough to learn from, said in words."""


def _epoch_days(value) -> float:
    if isinstance(value, datetime.datetime):
        return value.timestamp() / 86_400
    if isinstance(value, datetime.date):
        return float(value.toordinal() - datetime.date(1970, 1, 1).toordinal())
    return math.nan


@dataclass
class Encoding:
    """How records become a matrix: per input, its kind and, for text,
    the categories seen in training. Learned from the training rows and
    applied unchanged to every row predicted."""
    inputs: tuple
    kinds: dict
    categories: dict = field(default_factory=dict)

    def matrix(self, rows: Sequence[Mapping]) -> np.ndarray:
        out = np.full((len(rows), len(self.inputs)), np.nan, dtype=np.float64)
        for column, name in enumerate(self.inputs):
            kind = self.kinds[name]
            codes = self.categories.get(name)
            for row_index, row in enumerate(rows):
                value = row.get(name)
                if value is None and kind == "category" and codes is not None:
                    # EMPTY IS A VALUE OF ITS OWN for text: often the
                    # telling one ("no cancellation reason").
                    code = codes.get(EMPTY)
                    out[row_index, column] = math.nan if code is None else code
                    continue
                if value is None:
                    continue
                if kind == "category":
                    assert codes is not None
                    # UNSEEN IS MISSING, not "other": a value the model
                    # never met tells it nothing.
                    code = codes.get(str(value))
                    out[row_index, column] = math.nan if code is None else code
                elif kind == "date":
                    out[row_index, column] = _epoch_days(value)
                else:
                    try:
                        out[row_index, column] = float(value)
                    except (TypeError, ValueError):
                        continue
        return out

    @property
    def categorical_mask(self) -> list[bool]:
        return [self.kinds[name] == "category" for name in self.inputs]


def learn_encoding(rows: Sequence[Mapping], inputs: Sequence[str],
                   data_types: Mapping[str, str]) -> Encoding:
    kinds = {}
    categories = {}
    for name in inputs:
        data_type = data_types.get(name) or "string"
        if data_type in ("date", "timestamp", "timestamptz"):
            kinds[name] = "date"
        elif data_type in ("integer", "number", "decimal", "boolean"):
            kinds[name] = "number"
        else:
            kinds[name] = "category"
            # EMPTY COUNTS AS A CATEGORY. Left as missing, a text input
            # with one value and blanks is a constant to the trees --
            # scikit-learn 1.9 never splits it, measured 18 October --
            # though "blank" may be exactly what tells the answer.
            counts = Counter(EMPTY if row.get(name) is None else str(row.get(name))
                             for row in rows)
            kept = [value for value, _ in counts.most_common(MAX_CATEGORIES)]
            # OTHERS SHARE ONE CODE, the one after the kept ones.
            categories[name] = {value: index for index, value in enumerate(kept)}
            for value in counts:
                categories[name].setdefault(value, len(kept))
    return Encoding(tuple(inputs), kinds, categories)


def _answer(prediction: Prediction, value):
    """A known answer as the model learns it, or None when unknown."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if prediction.kind == "number":
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None
    if prediction.kind == "chance":
        return 1 if _same(value, prediction.chance_of) else 0
    return _label(value)


def _label(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _same(value, wanted) -> bool:
    return _label(value).casefold() == _label(wanted).casefold()


def _model(prediction: Prediction, encoding: Encoding, seed: int):
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

    options = {"categorical_features": encoding.categorical_mask, "random_state": seed}
    if prediction.kind == "number":
        return HistGradientBoostingRegressor(**options)
    return HistGradientBoostingClassifier(**options)


def _split(count: int, labels, prediction: Prediction, seed: int):
    """(train, held-out) positions: the same for the same data and seed,
    and keeping each answer's share in both for a text answer."""
    from sklearn.model_selection import train_test_split

    positions = np.arange(count)
    stratify = None
    if prediction.kind != "number":
        counts = Counter(labels)
        if min(counts.values()) >= 2:
            stratify = labels
    return train_test_split(positions, test_size=HELD_OUT, random_state=seed,
                            stratify=stratify)


def _score(prediction: Prediction, truth, guess) -> float:
    """The plain measure: share right, chance error (Brier), or typical
    miss -- for skill, compared with the naive guess's."""
    truth = np.asarray(truth)
    guess = np.asarray(guess)
    if prediction.kind == "class":
        return float(np.mean(truth == guess))
    if prediction.kind == "chance":
        return float(np.mean((guess - truth) ** 2))
    return float(np.mean(np.abs(guess - truth)))


def _skill(prediction: Prediction, model_score: float, naive_score: float) -> float:
    """0 = no better than the naive guess, 1 = never wrong. Accuracy is
    higher-better; the chance error and the miss are lower-better."""
    if prediction.kind == "class":
        return 0.0 if naive_score >= 1 else (model_score - naive_score) / (1 - naive_score)
    return 0.0 if naive_score <= 0 else 1 - model_score / naive_score


@dataclass
class Trained:
    """A model fitted on every known record, with how it measured."""
    prediction: Prediction
    encoding: Encoding
    model: Any
    evaluation: dict[str, Any]

    def predict(self, rows: Sequence[Mapping]) -> list:
        """The predicted field's value for each row: None where the answer
        is already known, which the real field then shows."""
        unknown = [index for index, row in enumerate(rows)
                   if _answer(self.prediction, row.get(self.prediction.target)) is None]
        values: list = [None] * len(rows)
        if not unknown:
            return values
        matrix = self.encoding.matrix([rows[index] for index in unknown])
        if self.prediction.kind == "number":
            guesses = self.model.predict(matrix)
            for index, guess in zip(unknown, guesses, strict=True):
                values[index] = float(round(guess, 6))
        elif self.prediction.kind == "chance":
            positive = list(self.model.classes_).index(1)
            chances = self.model.predict_proba(matrix)[:, positive]
            for index, chance in zip(unknown, chances, strict=True):
                values[index] = float(round(chance, 3))
        else:
            for index, guess in zip(unknown, self.model.predict(matrix), strict=True):
                values[index] = str(guess)
        return values


def train(rows: Sequence[Mapping], prediction: Prediction, data_types: Mapping[str, str],
          group_by: "str | None" = None, seed: int = SEED, explain: bool = True) -> Trained:
    """Measure on held-out records, then fit on every known one.
    NotLearnable when there is not enough to learn from. `explain=False`
    skips which inputs matter -- for the sync, which only needs the score
    and pays for importance once per input per repeat."""
    known = [(row, answer) for row in rows
             if (answer := _answer(prediction, row.get(prediction.target))) is not None]
    if len(known) < MIN_KNOWN:
        raise NotLearnable(f"only {len(known)} records have a known "
                           f"{prediction.target!r}; at least {MIN_KNOWN} are needed to learn "
                           f"from")
    labels = [answer for _, answer in known]
    if prediction.kind != "number" and len(set(labels)) < 2:
        raise NotLearnable(f"every known {prediction.target!r} is the same, so there is "
                           f"nothing to tell apart")
    train_at, test_at = _split(len(known), labels, prediction, seed)
    train_rows = [known[index][0] for index in train_at]
    test_rows = [known[index][0] for index in test_at]
    train_y = np.asarray([labels[index] for index in train_at])
    test_y = np.asarray([labels[index] for index in test_at])

    encoding = learn_encoding(train_rows, prediction.inputs, data_types)
    held_model = _model(prediction, encoding, seed).fit(encoding.matrix(train_rows), train_y)
    test_matrix = encoding.matrix(test_rows)
    guesses = _guesses(prediction, held_model, test_matrix)
    naive = _naive(prediction, train_y, len(test_y))
    model_score = _score(prediction, test_y, guesses)
    naive_score = _score(prediction, test_y, naive)
    skill = _skill(prediction, model_score, naive_score)

    evaluation: dict[str, Any] = {
        "kind": prediction.kind, "known": len(known), "learned_from": len(train_rows),
        "judged_on": len(test_rows), "measure": _MEASURE[prediction.kind],
        "score": round(model_score, 4), "naive_score": round(naive_score, 4),
        "skill": round(skill, 4),
        "important": _importance(prediction, held_model, test_matrix, test_y, seed)
        if explain else [],
        "groups": None if group_by is None else _groups(
            prediction, group_by, test_rows, test_y, guesses, naive),
        "group_by": group_by,
    }
    if prediction.kind == "chance":
        evaluation["share_right"] = round(float(np.mean((guesses >= 0.5) == (test_y == 1))), 4)
    if skill >= SUSPICIOUS_SKILL:
        top = evaluation["important"][0]["field"] if evaluation["important"] else "an input"
        evaluation["warning"] = (f"Too good to be true: almost never wrong usually means an "
                                 f"input carries the answer. Check {top!r} first.")

    # THE MODEL SERVED learns from every known record; the score above is
    # the one it earned on records it had not seen.
    all_rows = [row for row, _ in known]
    encoding = learn_encoding(all_rows, prediction.inputs, data_types)
    model = _model(prediction, encoding, seed).fit(encoding.matrix(all_rows),
                                                   np.asarray(labels))
    return Trained(prediction, encoding, model, evaluation)


def data_types_of(fields: Mapping) -> dict[str, str]:
    """Each field's declared data type, text when undeclared -- what
    train() reads the inputs and the answer as."""
    return {name: (field or {}).get("data_type") or "string" for name, field in fields.items()}


def still_earned(skill: float, approved_skill: "float | None") -> bool:
    """Whether a model retrained at a sync may fill its field: better than
    the naive guess, and no more than RETRAIN_TOLERANCE below the skill it
    was approved at. An approval with no recorded skill earns nothing."""
    if not isinstance(approved_skill, (int, float)):
        return False
    return skill > 0 and skill >= approved_skill - RETRAIN_TOLERANCE


def refusal(evaluation: Mapping) -> "str | None":
    """Why a measured prediction may NOT be approved, in words; None when
    it may. The one rule, read by the proposing script, the review and
    the decide route alike:

      - SKILL ABOVE 0: no better than the naive guess is noise with a
        number on it;
      - A BREAKDOWN BY GROUP (the owner, 17 October): every approval sees
        the score per value of a field the approver chose, because an
        average can hide a group the model fails.

    A too-good-to-be-true warning does not refuse: it is for the approver
    to read, and the leak it suspects is theirs to judge."""
    skill = evaluation.get("skill")
    if not isinstance(skill, (int, float)) or skill <= 0:
        shown = "unmeasured" if not isinstance(skill, (int, float)) else f"{skill:.0%}"
        return f"it is no better than the naive guess (skill {shown})."
    if not evaluation.get("groups"):
        return ("its score is not broken down by group; propose it again with --group-by, so "
                "an average cannot hide a group it fails.")
    return None


_MEASURE = {"class": "share right", "chance": "chance error (Brier)",
            "number": "typical miss (mean absolute error)"}


def _guesses(prediction: Prediction, model, matrix: np.ndarray) -> np.ndarray:
    if prediction.kind == "chance":
        return model.predict_proba(matrix)[:, list(model.classes_).index(1)]
    return model.predict(matrix)


def _naive(prediction: Prediction, train_y: np.ndarray, count: int) -> np.ndarray:
    """The guess with no model: the most common answer, the average
    chance, the middle number -- from the training records only."""
    if prediction.kind == "class":
        common = Counter(train_y.tolist()).most_common(1)[0][0]
        return np.asarray([common] * count)
    if prediction.kind == "chance":
        return np.full(count, float(np.mean(train_y)))
    return np.full(count, float(np.median(train_y)))


def _importance(prediction: Prediction, model, matrix, truth, seed: int) -> list[dict]:
    """Which inputs mattered: how much worse the model does on held-out
    records when one input's values are shuffled. Shares of the total."""
    from sklearn.inspection import permutation_importance

    scoring = {"class": "accuracy", "chance": "neg_brier_score",
               "number": "neg_mean_absolute_error"}[prediction.kind]
    result = permutation_importance(model, matrix, truth, scoring=scoring, n_repeats=5,
                                    random_state=seed)
    gains = np.clip(result.importances_mean, 0, None)
    total = float(gains.sum())
    ranked = sorted(zip(prediction.inputs, gains, strict=True), key=lambda pair: -pair[1])
    return [{"field": name, "share": round(float(gain) / total, 3) if total else 0.0}
            for name, gain in ranked]


def _groups(prediction: Prediction, group_by: str, rows, truth, guesses, naive) -> list[dict]:
    """The held-out score per value of `group_by`, largest first; a group
    too small to judge says so instead of showing a number."""
    by_group: dict = {}
    for index, row in enumerate(rows):
        value = row.get(group_by)
        by_group.setdefault("(empty)" if value is None else _label(value), []).append(index)
    ordered = sorted(by_group.items(), key=lambda pair: (-len(pair[1]), pair[0]))
    shown, rest = ordered[:MAX_GROUPS], ordered[MAX_GROUPS:]
    if rest:
        shown.append(("other", [index for _, indexes in rest for index in indexes]))
    out = []
    for value, indexes in shown:
        if len(indexes) < MIN_GROUP:
            out.append({"value": value, "records": len(indexes), "score": None,
                        "skill": None})
            continue
        model_score = _score(prediction, truth[indexes], guesses[indexes])
        naive_score = _score(prediction, truth[indexes], naive[indexes])
        out.append({"value": value, "records": len(indexes), "score": round(model_score, 4),
                    "skill": round(_skill(prediction, model_score, naive_score), 4)})
    return out
