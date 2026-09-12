"""
drift_policy.py  (what a sync does when the source changes shape)

WHY A TABLE AND NOT A CHAIN OF IFS. Before this, one drift shape had an
answer and the rest had BEHAVIOUR. Type drift raised; a column that
disappeared from the source produced whatever the adapter's SELECT
happened to do. Nobody decided that, and nobody could say what a NEW
shape would do without running it.

That is the fault Palantir spent a major version escaping. Object
Storage v1's semantics were "generally dictated by the behavior of the
underlying data store, given its tight coupling with the underlying
distributed document store and search engine" -- it did not have a
schema-change policy, it had a storage engine whose behaviour became
one. What transfers is not their migration framework, which is
machinery for recovering from that coupling. It is the principle:
STORAGE BEHAVIOUR MUST NOT BECOME POLICY BY DEFAULT.

So every shape here is named. A shape with no entry has no verdict
function to call, which means it cannot be handled by accident -- the
caller has to add one, and adding one is where the decision gets made.

THE RULE FOR DESTRUCTIVE CHANGE IS FOUNDRY'S, and it is sharper than
"always refuse". In Object Storage v2 a schema change is breaking only
if the property HAS RECEIVED USER EDITS; deleting one nobody ever
edited is not breaking at all. The write log is the same thing under
another name, so a removal's verdict depends on what it holds.

WHAT THIS MODULE DOES NOT DO: apply a disposition. Removing a field
from the ontology is an edit to ontology_schema.yaml, which is the
operator's to make and is reviewable where a silent mutation would not
be. This decides and explains; acting stays where the permissions are.
"""

from dataclasses import dataclass
from enum import Enum


class DriftShape(Enum):
    """The kinds of source change this sync recognises.

    An enum rather than strings, so an unhandled shape fails at the
    match site instead of a typo silently taking a default branch.
    """

    COLUMN_REMOVED = "column_removed"
    TYPE_CHANGED = "type_changed"


@dataclass(frozen=True)
class DriftVerdict:
    """What to do, and what to tell the operator when the answer is no."""

    absorbed: bool
    shape: DriftShape
    # Written for someone reading a failed sync log at an hour they did
    # not choose. Names the table, the field, what depends on it, and
    # what they can do. An error that only says "drift detected" makes
    # them find all four themselves.
    detail: str


def verdict_for_removed_column(silo: str, table: str, column: str, field: str | None,
                                edits: dict | None) -> DriftVerdict:
    """A column the ontology declares has gone from the source.

    BREAKING ONLY IF SOMETHING WROTE TO IT -- Foundry's line, not an
    arbitrary one. See the module docstring.

    `edits` is None when the caller could not consult a write log. That
    REFUSES, because absorbing on the strength of a check that did not
    happen is the silent substitution this whole module exists to
    prevent: the answer would look identical to "nothing was written",
    and it is not the same claim.
    """
    described = f"field {field!r}" if field else "no declared field"

    if edits is None:
        return DriftVerdict(
            absorbed=False,
            shape=DriftShape.COLUMN_REMOVED,
            detail=(
                f"{silo}.{table}: source column {column!r} backing {described} is "
                f"gone, and no write log was available to check what depends on "
                f"it. Refusing rather than assuming nothing does. The mirror is "
                f"unchanged and still serving its last good contents."
            ),
        )

    applied = edits.get("applied", 0)
    pending = edits.get("pending", 0)

    if applied == 0 and pending == 0:
        return DriftVerdict(
            absorbed=True,
            shape=DriftShape.COLUMN_REMOVED,
            detail=(
                f"{silo}.{table}: source column {column!r} backing {described} is "
                f"gone, and no write has ever touched it. Syncing the remaining "
                f"columns; remove {field or column!r} from ontology_schema.yaml "
                f"when convenient."
            ),
        )

    # PENDING IS THE WORSE HALF and is named first. An applied write is
    # history -- the value was set and dropping the field does not
    # unmake it. A pending write is an OBLIGATION: proposed, undecided,
    # and targeting a field that no longer exists, so it can never be
    # applied and would sit in the queue forever.
    return DriftVerdict(
        absorbed=False,
        shape=DriftShape.COLUMN_REMOVED,
        detail=(
            f"{silo}.{table}: source column {column!r} backing {described} is gone, "
            f"and {pending} pending and {applied} applied write(s) reference it. "
            f"The mirror is unchanged and still serving its last good contents.\n"
            f"Options, in the order most deployments want them:\n"
            f"  1. Restore the column upstream, if its removal was unintended.\n"
            f"  2. Repoint the field at its new column in ontology_schema.yaml, "
            f"if it was renamed rather than dropped.\n"
            f"  3. Remove the field from ontology_schema.yaml, accepting that "
            f"{pending} pending write(s) can never be applied and {applied} "
            f"applied write(s) stay in the log as history.\n"
            f"Elysium will not choose: each option loses something different."
        ),
    )


def verdict_for_type_change(silo: str, table: str, column: str) -> DriftVerdict:
    """A column's values no longer match its declared type.

    ALWAYS REFUSED, and unlike a removal this does not soften when
    nothing has been written: the column is still THERE and still READ,
    so absorbing it means serving values of a type the ontology says
    they are not. That reaches every reader, where a removal's damage
    is confined to writers.
    """
    return DriftVerdict(
        absorbed=False,
        shape=DriftShape.TYPE_CHANGED,
        detail=(
            f"{silo}.{table}: column {column!r} no longer holds the type the "
            f"ontology declares. The mirror is unchanged. Correct the declared "
            f"type in ontology_schema.yaml or fix the source; Elysium will not "
            f"cast between them silently."
        ),
    )
