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
    # A REMOVAL WITH A SUSPECT STANDING NEXT TO IT. A rename reaches
    # this module as two unrelated facts -- one declared column gone,
    # one undeclared column present -- because that is all a source
    # can tell us: no database records "this used to be called tier".
    #
    # A SEPARATE SHAPE RATHER THAN A FOOTNOTE, because what the
    # operator should DO differs. A dropped column wants the field
    # removed from the ontology; a renamed one wants the field
    # REPOINTED, and following the first instruction for the second
    # case throws away a field whose values are still there. Those are
    # different enough to be different shapes.
    #
    # AND, SINCE 21 OCTOBER, A DIFFERENT VERDICT: held, not absorbed.
    # See verdict_for_removed_column.
    COLUMN_RENAMED = "column_renamed"


#: What a suspected rename costs (config.yaml `on_suspected_rename`).
ON_SUSPECTED_RENAME = ("hold", "serve_empty")


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
                                edits: dict | None,
                                appeared: "tuple[str, ...]" = (),
                                on_suspected_rename: str = "hold",
                                unrecorded: bool = False,
                                undeclared_earlier: "tuple[str, ...]" = ()) -> DriftVerdict:
    """A column the ontology declares has gone from the source.

    BREAKING ONLY IF SOMETHING WROTE TO IT -- Foundry's line, not an
    arbitrary one. See the module docstring.

    `edits` is None when the caller could not consult a write log. That
    REFUSES, because absorbing on the strength of a check that did not
    happen is the silent substitution this whole module exists to
    prevent: the answer would look identical to "nothing was written",
    and it is not the same claim.

    `appeared` NAMES THE COLUMNS THE SAME SYNC FOUND THAT WERE NOT THERE
    BEFORE and the ontology does not declare, which is the only evidence
    a rename leaves. No source records that `tier` became `tier_name`;
    a sync sees one column gone and one column arrived, in the same
    table, in the same run, and that is all anybody gets.

    A SUSPECTED RENAME HOLDS THE TABLE (21 October, with the owner).
    Until then it was absorbed: the mirror served NULL in every row for
    a field whose values were still in the source under the new name --
    a reader seeing empty where a value exists, which Elysium's own rule
    calls wrong. The precedent splits. Replicators carry on: Fivetran
    keeps the old column "with the data that existed before" and writes
    NULL only for new rows, and Airbyte propagates by default. Strict
    modes stop: dlt's `freeze` loads nothing, Auto Loader's
    `failOnNewColumns` "fails and does not restart unless you update
    the provided schema", and Airbyte offers "Pause connection". Elysium
    serves the current state rather than keeping history, so carrying
    on means NULL in every row, not just new ones -- worse than
    Fivetran's default, and so it holds. A deployment that would rather
    serve the field empty says `on_suspected_rename: serve_empty`.

    `unrecorded`: no record of the source's earlier columns (a first
    sync, or bronze written before the record existed), so every
    undeclared column is a candidate and the message says it cannot
    tell which are new rather than claiming they all are.

    A RENAME IN TWO RELEASES IS NOT SEEN, and `undeclared_earlier` is
    the most that can be said about it. Add the new column and copy the
    values in one release, drop the old one in the next, and by the drop
    the new column is not new -- indistinguishable from one that has
    always been there. The removal is absorbed, as a plain drop is, and
    the message names the undeclared columns that might be its new home
    (found in review, 21 October; BLOCKING.md records the limit).

    IT DOES NOT CLAIM A RENAME HAPPENED. It names the candidates and
    puts the costly mistake first, because `tier` really might have
    been dropped in the same release that added an unrelated column.
    """
    described = f"field {field!r}" if field else "no declared field"
    shape = DriftShape.COLUMN_RENAMED if appeared else DriftShape.COLUMN_REMOVED
    suspects = ", ".join(repr(name) for name in appeared)

    if edits is None:
        return DriftVerdict(
            absorbed=False,
            shape=shape,
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
        if appeared and on_suspected_rename != "serve_empty":
            return DriftVerdict(
                absorbed=False,
                shape=shape,
                detail=(
                    f"{silo}.{table}: source column {column!r} backing {described} "
                    + (f"is gone. Elysium has no record of this source's earlier "
                       f"columns, so cannot tell which of these the ontology does not "
                       f"declare are new: {suspects}. If one is, that is what a rename "
                       if unrecorded else
                       f"is gone, and the same sync found {len(appeared)} column(s) "
                       f"that were not there before: {suspects}. That is what a rename ")
                    + f"looks like, so the mirror is unchanged and still serving its "
                    f"last good contents, rather than {field or column!r} empty in "
                    f"every row. If it was RENAMED, repoint the field's `column:` at "
                    f"the new name in ontology_schema.yaml; if it was dropped, remove "
                    f"the field. To serve the field empty instead whenever this "
                    f"happens, set `on_suspected_rename: serve_empty` in config.yaml."
                ),
            )
        if appeared:
            # THE REMEDY THAT LOSES SOMETHING COMES SECOND. Removing the
            # field is irreversible from the ontology's side and wrong
            # if this was a rename; repointing it is cheap and wrong
            # only in that it fails loudly on the next sync.
            return DriftVerdict(
                absorbed=True,
                shape=shape,
                detail=(
                    f"{silo}.{table}: source column {column!r} backing {described} "
                    f"is gone, and no write has ever touched it. The same sync "
                    f"found {len(appeared)} column(s) the ontology does not "
                    f"declare: {suspects}. If {column!r} was RENAMED, repoint the "
                    f"field's `column:` at the new name in ontology_schema.yaml -- "
                    f"the values are still in the source and the mirror is now "
                    f"serving null for them. If it was genuinely dropped, remove "
                    f"{field or column!r} from ontology_schema.yaml when "
                    f"convenient."
                ),
            )
        return DriftVerdict(
            absorbed=True,
            shape=shape,
            detail=(
                f"{silo}.{table}: source column {column!r} backing {described} is "
                f"gone, and no write has ever touched it. Syncing the remaining "
                f"columns; remove {field or column!r} from ontology_schema.yaml "
                f"when convenient."
                + (f" If it was renamed in an earlier release, its values may be in one "
                   f"of the columns the ontology does not declare -- "
                   f"{', '.join(repr(c) for c in undeclared_earlier)} -- and the field "
                   f"should point there instead." if undeclared_earlier else "")
            ),
        )

    # PENDING IS THE WORSE HALF and is named first. An applied write is
    # history -- the value was set and dropping the field does not
    # unmake it. A pending write is an OBLIGATION: proposed, undecided,
    # and targeting a field that no longer exists, so it can never be
    # applied and would sit in the queue forever.
    # THE CANDIDATE, NAMED IN OPTION 2 RATHER THAN LEFT ABSTRACT. This
    # branch already said "if it was renamed rather than dropped" and
    # left the operator to find the new name themselves -- which the
    # sync knows.
    renamed_to = f" The same sync found: {suspects}." if appeared else ""
    return DriftVerdict(
        absorbed=False,
        shape=shape,
        detail=(
            f"{silo}.{table}: source column {column!r} backing {described} is gone, "
            f"and {pending} pending and {applied} applied write(s) reference it. "
            f"The mirror is unchanged and still serving its last good contents.\n"
            f"Options, in the order most deployments want them:\n"
            f"  1. Restore the column upstream, if its removal was unintended.\n"
            f"  2. Repoint the field at its new column in ontology_schema.yaml, "
            f"if it was renamed rather than dropped.{renamed_to}\n"
            f"  3. Remove the field from ontology_schema.yaml, accepting that "
            f"{pending} pending write(s) can never be applied and {applied} "
            f"applied write(s) stay in the log as history.\n"
            f"Elysium will not choose: each option loses something different."
        ),
    )


def verdict_for_type_change(silo: str, table: str, column: str,
                            also_affected: int = 0) -> DriftVerdict:
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
            f"{silo}.{table}: column {column!r}"
            # AND HOW MANY OTHERS. The per-column detail below already
            # names every one, but a headline naming a single column
            # invites fixing that column and re-running -- discovering
            # the next one a full read of the source later. Saying the
            # count here costs nothing and sets the expectation.
            + (f" and {also_affected} other column(s)" if also_affected else "")
            + f" no longer hold{'' if also_affected else 's'} the type the "
            f"ontology declares. The mirror is unchanged. Correct the declared "
            f"type in ontology_schema.yaml or fix the source; Elysium will not "
            f"cast between them silently."
        ),
    )
