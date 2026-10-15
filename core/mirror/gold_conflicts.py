"""Why the golden record says Leeds: the reader for the losing values.

SURVIVORSHIP'S OWN DOCSTRING PROMISED THIS AND NOTHING DELIVERED IT.
`core/mirror/survivorship.py` states the rule it was built on, quoting
the MDM research this project recorded: "deleting losing values
destroys trust. A person asking why the golden record says Leeds needs
to see that the CRM said Hull and was outranked -- otherwise the answer
is an assertion. Losers go to the conflicts table, not to the bin."

They go to the conflicts table. `gold.py:_write_conflicts` appends
them, append-only, "because a record that can be rewritten is not a
record". And until this module, a repository-wide search for
`gold_conflicts` found the writer, the namespace constant, and two
assertions in `test_survivorship.py`. No reader, no route, no screen.
A table nobody can read is the bin with extra steps.

IT IS THE ONLY PER-FIELD, PER-SOURCE RECORD IN THE SYSTEM, which is
what makes it worth reading rather than merely tidy. Everything else
the lake records about origin is per ROW: `_silo` and `_source_table`
name one source for a whole object, and `_fused_from` names every
storage that contributed without saying which contributed WHAT --
`fusion.py` says so in those words, "lineage per PROPERTY is what
GOLD-6's review will need; this is the honest thing available now".
A customer fused from two databases reports one silo for every field
including the ones that came from the other. These rows are the
exception: entity, field, chosen, chosen source, losing, losing source.

WHAT IT DOES NOT HOLD, so nobody reads it expecting more. Only a
DISAGREEMENT is recorded -- `survivorship.py` appends a Conflict in the
branch where two sources both had something to say and said different
things. A null filled in from a lower-preference source writes nothing,
so "the primary had this" and "the primary was silent and the CRM
supplied it" are indistinguishable afterwards. That gap is
`AUDIT_CHECKLIST.csv` R67(a) and is not this module's to close.

NO ACCESS CONTROL HERE, AND THAT IS DELIBERATE -- the contract
`read_provenance` and `read_history` beside it both state: this reads
the mirror directly, and anything exposing it to a user must filter per
caller itself. The route above it does: the object's own visibility,
then per-field read grants on the VALUES, which are real customer data
and not metadata.
"""

from pyiceberg.exceptions import NoSuchNamespaceError, NoSuchTableError

from core.mirror.gold import CONFLICT_NAMESPACE


class ConflictsNotRecorded(LookupError):
    """No conflicts table for this type, so nothing can be said.

    DISTINCT FROM "no conflicts for this object", which is an ordinary
    empty answer. A deployment that declares no identity resolution
    never creates the table at all, and a deployment that does but has
    never found a disagreement creates it empty -- "we have never
    looked" and "we looked and found none" are different facts, and the
    second is the reassuring one.
    """


def read_conflicts(catalog, object_type: str, object_id: str) -> list[dict]:
    """Every disagreement recorded about this one entity, newest first.

    NEWEST FIRST because the table is APPEND-ONLY and every publication
    that still disagrees writes another row. An object whose sources
    have disagreed about `name` through forty publications has forty
    rows; the current one is the only one describing what gold holds
    now, and the rest are the history of the argument.

    THE WHOLE TABLE, filtered here rather than pushed down, matching
    `read_provenance` and `read_history` beside it. A predicate on
    entity_id would be faster and is the obvious next step; doing it
    here alone would leave three readers of the same shape behaving
    differently for no stated reason.
    """
    rows = [
        row for row in read_all_conflicts(catalog, object_type)
        if str(row.get("entity_id")) == str(object_id)
    ]
    # BY recorded_at, DESCENDING, and ties keep the order the table
    # holds them in -- `sorted` is stable, so rows written by one
    # publication (which share a timestamp to the microsecond, being
    # formatted once per call) stay in the order survivorship produced
    # them, which is the declared field order.
    return sorted(rows, key=lambda row: row.get("recorded_at") or "", reverse=True)


def read_all_conflicts(catalog, object_type: str) -> list[dict]:
    """Every row of a type's conflicts table, in table order: the whole
    history of every argument, which R60's track record reads to find
    the ones that have ended. Raises ConflictsNotRecorded as above."""
    identifier = f"{CONFLICT_NAMESPACE}.{object_type}"
    try:
        table = catalog.load_table(identifier)
    except (NoSuchTableError, NoSuchNamespaceError):
        raise ConflictsNotRecorded(identifier) from None
    return table.scan().to_arrow().to_pylist()
