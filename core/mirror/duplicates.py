"""What silver does when two rows claim the same identity (GOLD-1,
MEDALLION_PIPELINE.md's S4).

WHY THIS IS NOT AN ORDINARY EXPECTATION. Every other rule is about one
row's values; this is about two rows disagreeing about who they are. An
object type is BACKED BY a table keyed on its id, and the precedent is
blunt about what that requires: Foundry fails an indexing run outright
when a batch holds duplicate primary keys, because the ontology cannot
say which row the object is.

THE DEFAULT IS TO QUARANTINE EVERY COPY, and to name the key. Keeping
one silently would pick a winner nobody chose, and the row that lost
might be the true one; dropping both without a word would hide a real
problem in the source. Quarantined, the key is reported, both copies
stay in bronze, and the object simply is not in silver until the source
is fixed -- which is honest: nothing can say which row it was.

THE ALTERNATIVES ARE DECLARED, per table:

  quarantine (default)  every copy held back, the key reported.
  fail                  the build stops, the mirror unchanged, for a
                        source where a duplicate means something is
                        badly wrong upstream.
  keep_last_by: COLUMN  the copy with the greatest value in COLUMN
                        survives; the others are quarantined, never
                        silently dropped. This is Foundry's own
                        resolution rule -- the most recent transaction
                        wins -- and needs a column that says which is
                        most recent. A tie leaves it ambiguous, so
                        every copy is quarantined.
"""

from dataclasses import dataclass
from typing import Any, cast

QUARANTINE = "quarantine"
FAIL = "fail"
KEEP_LAST_BY = "keep_last_by"


@dataclass(frozen=True)
class DuplicatePolicy:
    action: str = QUARANTINE
    column: str | None = None


def policy_for_storage(storage: dict) -> DuplicatePolicy:
    """The declared policy for one table, or the default.

    Raises on anything else: a typo here decides what happens to rows.
    """
    declared = storage.get("duplicate_keys", QUARANTINE)
    if declared in (QUARANTINE, FAIL):
        return DuplicatePolicy(action=declared)
    if isinstance(declared, dict) and set(declared) == {KEEP_LAST_BY}:
        column = declared[KEEP_LAST_BY]
        if not isinstance(column, str) or not column:
            raise ValueError(f"duplicate_keys.{KEEP_LAST_BY} must name a column, got {column!r}.")
        return DuplicatePolicy(action=KEEP_LAST_BY, column=column)
    raise ValueError(
        f"duplicate_keys must be {QUARANTINE!r}, {FAIL!r}, or "
        f"{{{KEEP_LAST_BY}: COLUMN}}, got {declared!r}."
    )


class DuplicateKeys(Exception):
    """A table declares `fail` and its source holds duplicate keys."""

    def __init__(self, id_column: str, keys: list):
        self.keys = keys
        shown = ", ".join(repr(key) for key in keys[:5])
        more = f" and {len(keys) - 5} more" if len(keys) > 5 else ""
        super().__init__(
            f"{id_column}: duplicate key(s) {shown}{more}. This table declares "
            f"duplicate_keys: fail, so the mirror is unchanged."
        )


def split_duplicates(rows: list[dict], id_column: str, policy: DuplicatePolicy):
    """(kept, held) -- held as (row, key, why) for the quarantine table."""
    by_key: dict[Any, list[dict]] = {}
    for row in rows:
        by_key.setdefault(row.get(id_column), []).append(row)

    duplicated = {key: copies for key, copies in by_key.items() if len(copies) > 1}
    if duplicated and policy.action == FAIL:
        raise DuplicateKeys(id_column, sorted(duplicated, key=repr))

    kept: list[dict] = []
    held: list[tuple[dict, Any, str]] = []
    for key, copies in by_key.items():
        if len(copies) == 1:
            kept.append(copies[0])
            continue
        if policy.action == KEEP_LAST_BY:
            ordering = [row.get(policy.column) for row in copies]
            # A TIE, OR A MISSING ORDERING VALUE, falls through to the
            # default: nothing says which copy is most recent, so the
            # rule cannot choose and every copy is held.
            distinct_types = {type(value) for value in ordering}
            decidable = (
                None not in ordering
                and len({repr(value) for value in ordering}) == len(ordering)
                and len(distinct_types) == 1
            )
            if decidable:
                # BY VALUE, never by text: repr() would order 10 before
                # 9, and the ordering column is usually a number or a
                # timestamp. Mixed types cannot be compared at all, and
                # fall through to holding every copy.
                winner = max(copies, key=lambda row: cast(Any, row.get(policy.column)))
                kept.append(winner)
                held.extend(
                    (row, key,
                     f"duplicate {id_column} {key!r}: a copy with a later "
                     f"{policy.column} was kept")
                    for row in copies if row is not winner
                )
                continue
        held.extend(
            (row, key,
             f"duplicate {id_column} {key!r}: {len(copies)} rows claim this "
             f"identity, so none can be the object")
            for row in copies
        )
    return kept, held
