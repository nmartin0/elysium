"""
changelog.py  (what changed between two syncs, and in which direction)

WHY A CHANGELOG AT ALL, and it is not performance. A source database
holds "now". It has no record that a customer's region was us-west last
March, and no re-sync can recover what it has since overwritten. If
that history matters to anyone, only we can keep it.

That makes this the point at which the mirror stops being a CACHE and
becomes a SYSTEM OF RECORD -- which is why durable storage landed
first, and why ELT_ROADMAP.md calls it the reversibility line.

WHAT THIS IS NOT. It is not change data capture. Real CDC receives a
feed from the source; this DIFFS two snapshots we took ourselves, which
Foundry documents as the fallback for exactly our case: "my source
system sends a full snapshot every sync. My transforms apply CDC to
detect inserts, updates, and deletes, then write only the changes as
APPEND transactions."

THE LIMIT THAT FOLLOWS, stated plainly because it is inherent rather
than a gap to be closed later: bronze retains two snapshots, so a
changelog can only describe consecutive syncs. A sync that is missed
loses the intervening state permanently. Diffing sees where the data
got to, never the path it took.

IDENTIFIER MODE, which we qualify for. Foundry describes two: an
"identifier changelog (recommended): one or more identifier columns
provided", which is "more performant" and gives "richer semantics,
including update-before and update-after records", and a "net changes"
mode for data without reliable keys. Every object type in our ontology
declares an id_field, so the rows can be paired and an UPDATE told from
a DELETE plus an INSERT.

PLAIN PYTHON, NOT A QUERY ENGINE. A DuckDB anti-join does this 19.7x
faster -- measured, 0.050s against 0.984s for 200,000 rows a side. At
our scale that is under a second in a nightly job, and a dependency
that saves under a second is not worth its failure modes. The
measurement is recorded so the decision can be revisited when a table
is large enough to change it.
"""

from dataclasses import dataclass

# CHANGE TYPES, named as Iceberg's own changelog does.
INSERT = "INSERT"
UPDATE = "UPDATE"
DELETE = "DELETE"

# HOW MUCH OF A TABLE MAY VANISH before we refuse to call it deleted.
#
# Deletions are INFERRED here -- our sources do not report them, so
# absence from the new snapshot is the only signal we have. That is
# sound when a sync read the whole table, and catastrophic when one
# partially failed: a read that returned half the rows would be
# recorded as half the table being deleted, and a changelog is the one
# place that cannot be undone by re-syncing.
#
# So a drop beyond this fraction is treated as a failed read rather
# than as news. Foundry's equivalent instinct is the rule that
# retention "will never delete transactions that are in the latest view
# of any branch" -- when in doubt about destruction, refuse.
MAX_DELETED_FRACTION = 0.5


@dataclass(frozen=True)
class ChangeSet:
    """The difference between two snapshots of the same table."""

    rows: list[dict]
    """Each row as it now stands, plus a `_change` key. A DELETE
    carries the row as it LAST stood, since that is the only version
    of it that will ever exist again."""

    suspected_partial_read: bool
    """True when so much of the table vanished that a failed read is
    likelier than a real deletion. The caller records nothing."""

    @property
    def is_empty(self) -> bool:
        return not self.rows


def _as_strings(row: dict) -> dict:
    """Every value as a string, so the two sides are comparable.

    THE BUG THIS FIXES, found by a test rather than reasoning. The
    previous snapshot is read from BRONZE, which stores every value as
    a string; the current rows come from the ADAPTER, which returns
    whatever the source's types produce. So 10.5 from the database
    never equalled "10.5" from bronze, and EVERY ROW of any numeric
    table was recorded as changed on every sync -- measured: three
    UPDATE rows when one value had moved.

    A changelog that reports everything as changed is worse than none:
    it costs a full table copy per sync AND hides the real change in
    noise.

    Normalising here rather than at either source, because both are
    right about their own representation and only the COMPARISON needs
    them to agree.
    """
    return {
        key: (None if value is None else str(value))
        for key, value in row.items()
    }


def diff_snapshots(previous: list[dict], current: list[dict], id_column: str) -> ChangeSet:
    """What changed between two reads of one table.

    ROWS COMPARED WHOLE, not field by field. A row whose every value
    matches is unchanged; anything else is an UPDATE. Recording WHICH
    field moved would be finer, and is deliberately not done: it
    doubles the row count for a question nobody has asked yet, and the
    before-row is recoverable from the previous changelog entry.

    AN EMPTY PREVIOUS IS NOT A TABLE FULL OF INSERTS. The first sync
    after a changelog is enabled has no prior snapshot, and recording
    every existing row as newly inserted would be a lie that is
    expensive to store. The caller decides; this reports it honestly as
    all-inserts and lets the caller skip the first run.
    """
    old = {str(row[id_column]): _as_strings(row) for row in previous}
    new = {str(row[id_column]): _as_strings(row) for row in current}

    rows: list[dict] = []
    for key, row in new.items():
        was = old.get(key)
        if was is None:
            rows.append({**row, "_change": INSERT})
        elif was != row:
            rows.append({**row, "_change": UPDATE})

    missing = [key for key in old if key not in new]

    # THE GUARD. Checked against the PREVIOUS size, not the current
    # one: a read that returned nothing would divide by zero on the
    # current, and "everything vanished" is precisely the case this
    # exists to catch.
    if old and len(missing) / len(old) > MAX_DELETED_FRACTION:
        return ChangeSet(rows=[], suspected_partial_read=True)

    for key in missing:
        rows.append({**old[key], "_change": DELETE})

    return ChangeSet(rows=rows, suspected_partial_read=False)
