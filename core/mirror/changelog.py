"""
changelog.py  (what changed between two syncs, and in which direction)

WHY A CHANGELOG AT ALL, and it is not performance. A source database
holds "now". It has no record that a customer's region was us-west last
March, and no re-sync can recover what it has since overwritten. If
that history matters to anyone, only we can keep it.

That makes this the point at which the mirror stops being a CACHE and
becomes a SYSTEM OF RECORD -- which is why durable storage landed
first, and why this is the REVERSIBILITY LINE.

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
# THE ROW AS IT STOOD BEFORE AN UPDATE (R10). Iceberg's changelog view
# calls the pair UPDATE_BEFORE / UPDATE_AFTER and Foundry's identifier
# mode promises "update-before and update-after records"; the AFTER
# half keeps the name UPDATE it has always had here, so every changelog
# row written before this change still means what it said.
UPDATE_BEFORE = "UPDATE_BEFORE"

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


def diff_snapshots(previous: list[dict], current: list[dict], id_column: str,
                    accept_deletions: bool = False,
                    before_images: bool = False) -> ChangeSet:
    """What changed between two reads of one table.

    ROWS COMPARED WHOLE, not field by field. A row whose every value
    matches is unchanged; anything else is an UPDATE.

    BEFORE-IMAGES ON REQUEST (R10). This used to say the before-row
    "is recoverable from the previous changelog entry" -- true only for
    a row whose previous state the changelog had seen. A row inserted
    before the changelog began, then updated, had no previous entry, so
    its first update recorded where it went and never where it came
    from. With `before_images`, each UPDATE is preceded by an
    UPDATE_BEFORE row holding the old values, which is what an SCD2
    view needs to close the old version. The source changelog asks for
    them; gold's history keeps one row per change, as it always has.

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
            if before_images:
                rows.append({**was, "_change": UPDATE_BEFORE})
            rows.append({**row, "_change": UPDATE})

    missing = [key for key in old if key not in new]

    # THE GUARD. Checked against the PREVIOUS size, not the current
    # one: a read that returned nothing would divide by zero on the
    # current, and "everything vanished" is precisely the case this
    # exists to catch.
    if old and len(missing) / len(old) > MAX_DELETED_FRACTION and not accept_deletions:
        return ChangeSet(rows=[], suspected_partial_read=True)

    for key in missing:
        rows.append({**old[key], "_change": DELETE})

    return ChangeSet(rows=rows, suspected_partial_read=False)


def scd2_versions(entries: list[dict], id_column: str) -> list[dict]:
    """The changelog read as SCD Type 2: every version of every row,
    with when it became current and when it stopped.

    Kimball's Type 2: "add a new row" per change, with "effective and
    expiration dates" and a current-row flag. Built FROM the changelog
    rather than stored beside it -- the changelog is the record and
    this is a reading of it, so the two can never disagree.

    `_valid_from` and `_valid_to` are when the SYNC NOTICED, which is
    the only clock a snapshot diff has (see `_recorded_at`). A version
    the changelog never saw begin -- the before-image of a row older
    than the changelog -- has `_valid_from` None: it existed, and when
    it started is not known. Said as None, never guessed.
    """
    ordered = sorted(entries, key=lambda entry: (entry.get("_recorded_at") or "",
                                                 entry.get("_change") != UPDATE_BEFORE))
    open_versions: dict[str, dict] = {}
    versions: list[dict] = []

    def close(key: str, at: "str | None") -> None:
        version = open_versions.pop(key, None)
        if version is not None:
            version["_valid_to"] = at
            version["_current"] = False

    for entry in ordered:
        key = str(entry.get(id_column))
        change, at = entry.get("_change"), entry.get("_recorded_at")
        values = {k: v for k, v in entry.items() if not k.startswith("_")}
        if change == UPDATE_BEFORE:
            # The old version, if the changelog never opened it.
            if key not in open_versions:
                version = {**values, "_valid_from": None, "_valid_to": at, "_current": False}
                versions.append(version)
            else:
                close(key, at)
            continue
        close(key, at)
        if change in (INSERT, UPDATE):
            version = {**values, "_valid_from": at, "_valid_to": None, "_current": True}
            versions.append(version)
            open_versions[key] = version
    return versions
