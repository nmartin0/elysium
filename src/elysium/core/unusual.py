"""Finding records whose numbers are unusual for their kind (R51).

What a declaration means is core/ontology/unusual_checks.py. This is the
measuring: each number against the records that share its `within`
values, by Iglewicz and Hoaglin's modified z-score -- 0.6745 (x - median)
/ MAD -- flagged above 3.5, their recommendation and the per-field
check's (core/mirror/outliers.py). Robust to the very values it looks
for, as a mean and standard deviation are not.

WHY NOT AN ISOLATION FOREST, which was the plan (the owner, 19 October,
after seeing the measurement). On 5,000 synthetic records with 20
amounts normal for the table but wrong for their category, and 20 plain
extremes: scikit-learn's IsolationForest flagged 2,405 records at its
default threshold; its top 1% changed with the random seed (29 of 50
the same across five seeds); and it caught 0 to 6 of the 20 wrong-kind
amounts, 7 to 12 with categories one-hot encoded. Scored within each
category, the modified z-score caught all 20 of each, the same every
run, and can say why.

GROUPS TOO SMALL TO JUDGE ARE NOT JUDGED: under MIN_GROUP records, or
with no spread at all (MAD 0), there is no usual to be far from.

A PUBLISHED CUT-OFF, NOT A QUOTA: a clean table gets no flags. But at
most MAX_FLAGS per type and compartment, the furthest first -- a
deployment whose data is far from these assumptions should see a short
list and "N more", not a wall.

PER COMPARTMENT, like predictions (the owner, 17 October): a record is
judged only against records of its own compartment, so a flag never
says something learned from records its reader cannot see.
"""

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

THRESHOLD = 3.5
MIN_GROUP = 20
MAX_FLAGS = 50


@dataclass(frozen=True)
class Flag:
    record_id: str
    field: str
    value: float
    #: ((field, value), ...) -- the kind it was compared within.
    kind: tuple
    median: float
    low: float          # the 5th percentile of its kind
    high: float         # the 95th
    group_size: int
    score: float        # the modified z-score, signed

    def reason(self) -> str:
        """In words, for a person: what, against which records, how far."""
        side = "above" if self.score > 0 else "below"
        like = ", ".join(f"{field} {_shown(value)}" for field, value in self.kind)
        among = f"the {self.group_size} records with {like}" if like else \
            f"all {self.group_size} records"
        return (f"{self.field} {_shown(self.value)} is far {side} the usual {_shown(self.median)} "
                f"for {among}; nine in ten of them are between {_shown(self.low)} and "
                f"{_shown(self.high)}.")


def _shown(value) -> str:
    if value is None:
        return "(empty)"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".") if not value.is_integer() else f"{value:,.0f}"
    return str(value)


def _number(value) -> "float | None":
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def find_unusual(rows: Sequence[Mapping], id_field: str, numbers: Sequence[str],
                 within: Sequence[str]) -> "tuple[list[Flag], int]":
    """(the flags, furthest first, at most MAX_FLAGS; how many there were
    in all). `rows` are one compartment's records."""
    flags: list[Flag] = []
    for field in numbers:
        groups: dict = {}
        for row in rows:
            number = _number(row.get(field))
            if number is None:
                continue
            kind = tuple((name, row.get(name)) for name in within)
            groups.setdefault(kind, []).append((str(row.get(id_field)), number))
        for kind, members in groups.items():
            if len(members) < MIN_GROUP:
                continue
            values = sorted(number for _, number in members)
            median = statistics.median(values)
            mad = statistics.median(abs(number - median) for number in values)
            if mad == 0:
                continue
            low, high = _percentile(values, 0.05), _percentile(values, 0.95)
            for record_id, number in members:
                score = 0.6745 * (number - median) / mad
                if abs(score) > THRESHOLD:
                    flags.append(Flag(record_id, field, number, kind, median, low, high,
                                      len(members), round(score, 2)))
    flags.sort(key=lambda flag: (-abs(flag.score), flag.record_id, flag.field))
    return flags[:MAX_FLAGS], len(flags)


def _percentile(ordered: Sequence[float], share: float) -> float:
    """The value at `share` of the way through, interpolated."""
    position = share * (len(ordered) - 1)
    below = math.floor(position)
    above = min(below + 1, len(ordered) - 1)
    return ordered[below] + (ordered[above] - ordered[below]) * (position - below)
