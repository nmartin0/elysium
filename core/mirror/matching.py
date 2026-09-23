"""Proposing that two entities might be one (GOLD-6, the inferred
half).

THIS NEVER DECIDES ANYTHING. FUSION_AND_IDENTITY.md is explicit:
inference "only ever ADDS PROPOSALS to a mechanism that already works
without it", and a proposed merge needs approval "ALWAYS. Never
configurable, because a setting is a thing someone turns off". What
this module produces is candidates with a score and an explanation.
What happens to them is the write queue's business.

TWO THRESHOLDS, from the MDM precedent recorded in
FUSION_AND_IDENTITY.md: above the auto-propose threshold a candidate
becomes a proposal without anyone asking; between the two it goes to
review; below, nothing. Both are declared per type, because only a
deployment knows what a false merge costs it.

WEIGHTS ARE DECLARED, NOT ESTIMATED, and that is a decision rather
than a limitation (LIBRARY_AUDIT.md, GOLD-6's technology note). A
governed system should tell a reviewer why two records scored as they
did in terms somebody CHOSE, not terms an algorithm inferred from data
nobody inspected -- and it routes around a reproduced bug in Splink's
unsupervised training path, measured across six version combinations.

THE BACKEND IS OPTIONAL. Splink brings 186 MB across seven transitive
packages, and inference is off by default, so a deployment that never
turns it on never installs it: `pip install elysium[identity]`. The
import is lazy and the failure names the extra.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# What a deployment declares, under a type's `identity` block:
#
#   identity:
#     match_on: [email]                 # the deterministic rule
#     probabilistic:
#       compare: [name, postcode]       # fields to score on
#       block_on: [postcode]            # only compare rows agreeing here
#
# BLOCKING IS ABOUT SCALE, NOT THE ANSWER. It decides which pairs are
# generated at all -- a matcher blocking on nothing compares every row
# against every other, which is quadratic -- while the thresholds
# decide what the answer is. MEASURED: removing the declared blocking
# from the test fixtures changed no verdict, because the extra pairs
# scored below the review threshold and were dropped. So tune it for
# cost, and do not expect it to make a match appear or disappear.
#       auto_propose_above: 0.95
#       review_above: 0.80
DEFAULT_AUTO_PROPOSE_ABOVE = 0.95
DEFAULT_REVIEW_ABOVE = 0.80


@dataclass(frozen=True)
class Candidate:
    """Two rows that might be one object, and why it was thought so."""

    left_id: str
    right_id: str
    score: float
    # field -> whether the two agreed, which is the explanation a
    # reviewer reads. Splink calls these gamma values; the word is
    # avoided here because a reviewer is not reading Splink.
    agreement: dict[str, bool] = field(default_factory=dict)

    @property
    def disposition(self) -> str:
        return "propose" if self.score >= DEFAULT_AUTO_PROPOSE_ABOVE else "review"


@runtime_checkable
class CandidateMatcher(Protocol):
    """What identity resolution asks of any matcher.

    An interface of ours, exposing only what we use -- so replacing the
    backend is a change to one file (rule 18, and Cox's "abstract the
    dependency").

    RUNTIME-CHECKABLE so a test can assert the backend still satisfies
    it. Without that the protocol is a comment: nothing would notice a
    backend drifting away from the interface it is supposed to honour.
    """

    def candidates(self, type_def: dict, rows_by_storage: dict[Any, list[dict]],
                   ) -> list[Candidate]:
        ...


@dataclass(frozen=True)
class ProbabilisticSettings:
    compare: tuple[str, ...]
    block_on: tuple[str, ...]
    auto_propose_above: float
    review_above: float


def settings_for(type_def: dict) -> ProbabilisticSettings | None:
    """What a type declares, or None when it declares no inference.

    Raises rather than defaulting on a malformed block: a deployment
    that meant to enable matching and typed a key wrongly should be
    told, not quietly left deterministic.

    ACCEPTS FROZEN CONFIGURATION. The loader deep-freezes the schema
    before anything sees it, so a mapping arrives as a mappingproxy and
    a list as a TUPLE. Checking for `dict` and `list` here rejected
    every real deployment while passing every test that built its
    schema by hand -- found by running the pipeline end to end, which
    no unit test would have caught.
    """
    identity = type_def.get("identity") or {}
    declared = identity.get("probabilistic")
    if not declared:
        return None
    if not isinstance(declared, Mapping):
        raise ValueError(f"identity.probabilistic must be a mapping, got {declared!r}.")
    unknown = set(declared) - {"compare", "block_on", "auto_propose_above", "review_above"}
    if unknown:
        raise ValueError(f"unknown identity.probabilistic key(s) {sorted(unknown)}.")
    compare = declared.get("compare")
    if not compare or isinstance(compare, str) or not isinstance(compare, Sequence):
        raise ValueError("identity.probabilistic.compare must be a non-empty list of fields.")
    fields = type_def.get("fields") or {}
    missing = [name for name in compare if name not in fields]
    if missing:
        raise ValueError(f"identity.probabilistic.compare names unknown field(s) {missing}.")
    auto = float(declared.get("auto_propose_above", DEFAULT_AUTO_PROPOSE_ABOVE))
    review = float(declared.get("review_above", DEFAULT_REVIEW_ABOVE))
    if not 0 < review <= auto <= 1:
        raise ValueError(
            f"thresholds must satisfy 0 < review_above ({review}) <= "
            f"auto_propose_above ({auto}) <= 1."
        )
    return ProbabilisticSettings(
        compare=tuple(compare),
        block_on=tuple(declared.get("block_on") or []),
        auto_propose_above=auto,
        review_above=review,
    )


class SplinkNotInstalled(RuntimeError):
    """The extra that carries the probabilistic backend is absent."""

    def __init__(self) -> None:
        super().__init__(
            "probabilistic identity resolution needs the 'identity' extra: "
            "pip install elysium[identity]. The declared rule in identity.match_on "
            "keeps working without it."
        )


class SplinkMatcher:
    """Fellegi-Sunter scoring, with weights this deployment declared."""

    def __init__(self, m_probability: float = 0.9, u_probability: float = 0.01,
                 prior: float = 0.001):
        # THE DECLARED WEIGHTS: a field agreeing is 0.9 likely among
        # matches and 0.01 among non-matches, against a prior that any
        # two records are the same object of 1 in 1,000.
        #
        # CHOSEN BY WORKING OUT WHAT THEY IMPLY, not by feel. With
        # these, and the default thresholds:
        #
        #     1 field agrees   p = 0.083   nothing happens
        #     2 fields agree   p = 0.890   goes to REVIEW
        #     3 fields agree   p = 0.999   becomes a PROPOSAL
        #
        # The first defaults tried (u = 0.05) put two agreeing fields
        # at 0.245, so nothing ever reached the review threshold and
        # the feature was inert -- which nobody would have noticed,
        # because "no candidates" looks exactly like "no duplicates".
        #
        # A deployment tuning these is making a statement it can
        # defend; an algorithm inferring them is not.
        self._m = m_probability
        self._u = u_probability
        self._prior = prior

    def candidates(self, type_def: dict, rows_by_storage: dict[Any, list[dict]],
                   ) -> list[Candidate]:
        settings = settings_for(type_def)
        if settings is None:
            return []
        try:
            import pandas as pd
            import splink.comparison_library as cl
            from splink import DuckDBAPI, Linker, SettingsCreator, block_on
        except ImportError as exc:  # pragma: no cover - depends on the extra
            raise SplinkNotInstalled() from exc

        frame = pd.DataFrame(self._records(type_def, rows_by_storage, settings))
        if frame.empty:
            return []
        # list[Any] because Splink's own annotations are invariant
        # over a union, and this list is handed straight to it.
        comparisons: list[Any] = [
            cl.ExactMatch(name).configure(
                m_probabilities=[self._m, 1 - self._m],
                u_probabilities=[self._u, 1 - self._u],
            )
            for name in settings.compare
        ]
        blocking: list[Any] = [block_on(name) for name in settings.block_on] or [
            block_on(settings.compare[0])]
        linker = Linker(
            frame,
            SettingsCreator(
                link_type="dedupe_only",
                probability_two_random_records_match=self._prior,
                comparisons=comparisons,
                blocking_rules_to_generate_predictions=blocking,
            ),
            DuckDBAPI(),
        )
        predicted = linker.inference.predict(
            threshold_match_probability=settings.review_above,
        ).as_pandas_dataframe()
        return [
            Candidate(
                left_id=str(row["unique_id_l"]),
                right_id=str(row["unique_id_r"]),
                score=float(row["match_probability"]),
                agreement={
                    name: bool(row.get(f"gamma_{name}", 0) > 0)
                    for name in settings.compare
                },
            )
            for _, row in predicted.iterrows()
        ]

    @staticmethod
    def _records(type_def: dict, rows_by_storage: dict[Any, list[dict]],
                  settings: ProbabilisticSettings) -> list[dict]:
        """Every source row, flattened to the fields being compared.

        The id carries its storage, because the whole point is that two
        sources call the same object different things.
        """
        storages: dict[Any, dict] = {None: type_def["storage"]}
        storages.update(type_def.get("additional_storage") or {})
        fields = type_def.get("fields") or {}
        records = []
        for storage_key, storage in storages.items():
            prefix = "primary" if storage_key is None else str(storage_key)
            for row in rows_by_storage.get(storage_key) or []:
                record: dict[str, Any] = {
                    "unique_id": f"{prefix}:{row.get(storage['id_column'])}"}
                for name in settings.compare:
                    column = (fields.get(name) or {}).get("column", name)
                    value = row.get(column)
                    record[name] = None if value is None else str(value)
                records.append(record)
        return records
