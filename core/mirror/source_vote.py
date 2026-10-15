"""Where three or more sources hold a field: which value most INDEPENDENT
sources agree on, and which sources look like copies (R60, the voting
half). Evidence only.

R60's other half, source_record.py, learns from how a disagreement
between two sources ENDS, because with two a snapshot says nothing.
With three or more, a snapshot does say something: the value most of
them hold is more likely true than one held by a single source. That is
plain voting, and it has one well-known way to go wrong.

COPIES OUTVOTE THE TRUTH. If the CRM is loaded nightly from billing,
the two agree on everything, including billing's mistakes, and two
votes for a wrong value beat one for the right one. The answer used
here is Dong, Berti-Equille and Srivastava's DEPEN model, "Integrating
Conflicting Data: The Role of Source Dependence" (PVLDB 2(1), 2009):

  SHARED MISTAKES ARE THE TELL. Two independent sources rarely make the
  SAME mistake -- there are many wrong values and one right one -- so a
  pair agreeing on values the vote calls false is probably one copying
  the other. Over the items two sources both hold, count kt (same, and
  the vote says true), kf (same, false), kd (different). With error
  rate e, n possible false values and copy rate c:

      independent  Pt = (1-e)^2          Pf = e^2/n          Pd = 1-Pt-Pf
      copying      Pt' = (1-e)c + Pt(1-c)  Pf' = ec + Pf(1-c)  Pd' = Pd(1-c)

  and Bayes, with prior a that a pair copies, gives the posterior that
  it does.

  A COPY'S VOTE IS DISCOUNTED. Among the sources holding a value, taken
  in a fixed order, each votes 1 times (1 - c * P(it copies one already
  counted)) for each of them -- the paper's independent vote count, with
  a fixed order where the paper estimates who copied whom.

  AND THE TWO ARE ITERATED. The vote decides what is true, which decides
  who looks like a copy, which changes the vote -- until it stops
  changing, or for at most a few rounds.

EACH SOURCE'S ERROR RATE IS ESTIMATED; THE REST ARE DECLARED. n, c and
a are the paper's defaults (100, 0.8, 0.2). e was declared too, at the
paper's 0.2, and its own test found what that does: two ACCURATE sources
agreeing on all eleven items they shared read as 65% likely to be
copying, because sources wrong a fifth of the time "should" differ on a
third of items, and never differing looked suspicious. Real sources are
mostly right, so nearly every accurate pair would have been discounted.
So e is estimated per source, as the paper's ACCU does: each round, the
share of voted items where the source differs from the majority, between
0.01 and 0.5. Two accurate sources that always agree then come out as
"cannot tell" -- correctly, since copying an accurate source leaves no
trace -- and only shared MISTAKES make a copy.

WHAT IT CANNOT TELL YOU. A majority is evidence, not truth: three
sources fed by one clerk who mistyped once agree on the typo. And a
source copying selectively -- only some fields -- looks independent on
the rest.

EVIDENCE ONLY. Survivorship still decides by the declared order.
"""

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

ERROR_RATE = 0.2   # before the first vote has estimated anything
ERROR_FLOOR = 0.01
# AND A CEILING: a source differing from the majority on its only item
# estimates at 1.0, which makes every shared value impossible (log 0).
# Past a half, "wrong more often than right" is all the estimate can say.
ERROR_CEILING = 0.5
FALSE_VALUES = 100
COPY_RATE = 0.8
COPY_PRIOR = 0.2
ROUNDS = 5


@dataclass(frozen=True)
class Copying:
    sources: tuple[str, str]  # sorted
    probability: float
    shared_true: int
    shared_false: int
    different: int


@dataclass(frozen=True)
class Vote:
    """One entity's field, held by three or more sources."""

    entity_id: str
    field: str
    # The sources holding the value with the most independent votes;
    # empty on a tie, where the vote says nothing.
    majority: tuple[str, ...]
    sources: tuple[str, ...]


@dataclass
class Outcome:
    votes: list[Vote] = field(default_factory=list)
    copying: list[Copying] = field(default_factory=list)
    # (field, source) -> (agreed with the majority, items voted on)
    agreement: dict[tuple[str, str], tuple[int, int]] = field(default_factory=dict)


def _items(current: Mapping[str, Mapping[str, Mapping[str, Any]]]
           ) -> dict[tuple[str, str], dict[str, str]]:
    """(entity, field) -> source -> value, where three or more sources
    hold a value. Compared as text, as the conflicts table stores them."""
    found = {}
    for entity_id, fields in current.items():
        for field_name, by_source in fields.items():
            held = {source: str(value) for source, value in by_source.items()
                    if value is not None}
            if len(held) >= 3:
                found[(str(entity_id), field_name)] = held
    return found


def copy_probability(shared_true: int, shared_false: int, different: int,
                     error: float = ERROR_RATE, error_other: "float | None" = None,
                     false_values: int = FALSE_VALUES, copy: float = COPY_RATE,
                     prior: float = COPY_PRIOR) -> float:
    """The posterior that one of two sources copies the other, from what
    they share (the module docstring has the model), given each one's
    error rate. In logs, because a few hundred items underflow a product
    of probabilities."""
    other = error if error_other is None else error_other
    mean = (error + other) / 2  # the copied source's, not known which
    pt = (1 - error) * (1 - other)
    pf = error * other / false_values
    pd = 1 - pt - pf
    pt_c = (1 - mean) * copy + pt * (1 - copy)
    pf_c = mean * copy + pf * (1 - copy)
    pd_c = pd * (1 - copy)
    log_independent = (math.log(1 - prior) + shared_true * math.log(pt)
                       + shared_false * math.log(pf) + different * math.log(pd))
    log_copying = (math.log(prior) + shared_true * math.log(pt_c)
                   + shared_false * math.log(pf_c) + different * math.log(pd_c))
    top = max(log_independent, log_copying)
    a, b = math.exp(log_copying - top), math.exp(log_independent - top)
    return a / (a + b)


def _winners(items: Mapping[tuple[str, str], Mapping[str, str]],
             copying: Mapping[frozenset, float]) -> dict[tuple[str, str], "str | None"]:
    """Each item's value with the most independent votes; None on a tie."""
    winners = {}
    for key, held in items.items():
        tally: dict[str, float] = {}
        for value in set(held.values()):
            providers = sorted(source for source, v in held.items() if v == value)
            total = 0.0
            for i, source in enumerate(providers):
                weight = 1.0
                for earlier in providers[:i]:
                    weight *= 1 - COPY_RATE * copying.get(frozenset((source, earlier)), 0.0)
                total += weight
            tally[value] = total
        best = max(tally.values())
        leaders = [value for value, votes in tally.items() if math.isclose(votes, best)]
        winners[key] = leaders[0] if len(leaders) == 1 else None
    return winners


def _error_rates(items: Mapping[tuple[str, str], Mapping[str, str]],
                 winners: Mapping[tuple[str, str], "str | None"]) -> dict[str, float]:
    """Each source's share of voted items where it differs from the
    majority, floored: ACCU's estimate, from this round's vote."""
    seen: dict[str, list[int]] = {}
    for key, held in items.items():
        winner = winners[key]
        for source, value in held.items():
            counts = seen.setdefault(source, [0, 0])
            if winner is not None:
                counts[0] += value != winner
                counts[1] += 1
    return {source: min(ERROR_CEILING, max(ERROR_FLOOR, wrong / total)) if total else ERROR_RATE
            for source, (wrong, total) in seen.items()}


def vote(current: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> Outcome:
    """Vote on every item three or more sources hold, discounting copies.

    `current` is entity -> field -> source -> value, as
    source_record.current_values gives it.
    """
    items = _items(current)
    outcome = Outcome()
    if not items:
        return outcome
    sources = sorted({source for held in items.values() for source in held})
    copying: dict[frozenset, float] = {}
    winners = _winners(items, copying)
    counts: dict[frozenset, tuple[int, int, int]] = {}
    for _ in range(ROUNDS):
        errors = _error_rates(items, winners)
        counts = {}
        for a, b in combinations(sources, 2):
            kt = kf = kd = 0
            for key, held in items.items():
                if a not in held or b not in held or winners[key] is None:
                    continue
                if held[a] != held[b]:
                    kd += 1
                elif held[a] == winners[key]:
                    kt += 1
                else:
                    kf += 1
            counts[frozenset((a, b))] = (kt, kf, kd)
        updated = {}
        for pair, seen in counts.items():
            if sum(seen):
                a, b = sorted(pair)
                updated[pair] = copy_probability(*seen, error=errors[a], error_other=errors[b])
        new_winners = _winners(items, updated)
        stable = new_winners == winners
        copying, winners = updated, new_winners
        if stable:
            break

    for pair, probability in sorted(copying.items(), key=lambda item: sorted(item[0])):
        if probability > 0.5:
            kt, kf, kd = counts[pair]
            outcome.copying.append(Copying(tuple(sorted(pair)), probability, kt, kf, kd))  # type: ignore[arg-type]
    agreement: dict[tuple[str, str], list[int]] = {}
    for (entity_id, field_name), held in sorted(items.items()):
        winner = winners[(entity_id, field_name)]
        majority = tuple(sorted(s for s, v in held.items() if winner is not None and v == winner))
        outcome.votes.append(Vote(entity_id, field_name, majority, tuple(sorted(held))))
        if winner is None:
            continue
        for source, value in held.items():
            sided = agreement.setdefault((field_name, source), [0, 0])
            sided[0] += value == winner
            sided[1] += 1
    outcome.agreement = {key: (a, n) for key, (a, n) in agreement.items()}
    return outcome


def disputed(votes: Iterable[Vote]) -> list[Vote]:
    """The votes worth keeping per entity: where the sources did not all
    agree. A unanimous field has no conflict row to annotate."""
    return [v for v in votes if set(v.majority) != set(v.sources)]
