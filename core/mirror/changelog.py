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


def diff_snapshot_tables(previous, current, id_column: str,
                         accept_deletions: bool = False,
                         before_images: bool = False) -> ChangeSet:
    """diff_snapshots over two Arrow tables, without turning either into
    Python dicts -- except the rows that actually changed (R5).

    WHY. diff_snapshots builds a dict per row for BOTH snapshots, and
    the sync calls it whenever a table changed at all -- which a live
    table does every run. Measured on 200,000 rows with ONE row changed:
    the re-sync peaked at 880 MB, most of it those dicts. This compares
    column by column in Arrow and builds dicts only for the changes.

    THE SAME ANSWER, by construction and by test: rows are paired by
    `str(id)`, the LAST row wins when an id repeats (a dict's rule), a
    row is unchanged only when every value matches with None equal only
    to None, a change in the SET of columns makes every common row an
    update (two dicts with different keys are unequal), the output order
    is the current table's then the deletions in the previous table's,
    and the partial-read guard counts against the previous size.
    tests/unit/test_changelog_diff_in_arrow.py checks it against
    diff_snapshots on randomised tables.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    def last_per_id(table):
        keys = ["None" if value is None else str(value)
                for value in table.column(id_column).to_pylist()]
        last = {}
        for index, key in enumerate(keys):
            last.pop(key, None)  # re-inserted below, so order is last occurrence
            last[key] = index
        # Dict order is first-insertion; a repeated key must sit where a
        # dict comprehension over the rows would leave it -- its FIRST
        # position, holding its LAST row.
        first_position = {}
        for index, key in enumerate(keys):
            first_position.setdefault(key, index)
        ordered = sorted(last, key=first_position.__getitem__)
        return ordered, [last[key] for key in ordered]

    old_keys, old_rows = last_per_id(previous)
    new_keys, new_rows = last_per_id(current)
    old_index = dict(zip(old_keys, old_rows, strict=True))
    new_set = set(new_keys)

    missing = [key for key in old_keys if key not in new_set]
    if old_keys and len(missing) / len(old_keys) > MAX_DELETED_FRACTION and not accept_deletions:
        return ChangeSet(rows=[], suspected_partial_read=True)

    paired_new = [row for key, row in zip(new_keys, new_rows, strict=True) if key in old_index]
    paired_old = [old_index[key] for key in new_keys if key in old_index]
    same_columns = set(previous.column_names) == set(current.column_names)
    if same_columns and paired_new:
        a = current.take(pa.array(paired_new))
        b = previous.take(pa.array(paired_old))
        unchanged = None
        for name in current.column_names:
            x, y = pc.cast(a.column(name), pa.string()), pc.cast(b.column(name), pa.string())
            both_null = pc.and_(pc.is_null(x), pc.is_null(y))
            equal = pc.fill_null(pc.equal(x, y), False)
            column_same = pc.or_(both_null, equal)
            unchanged = column_same if unchanged is None else pc.and_(unchanged, column_same)
        # No columns at all: two empty rows are equal, as two {} are.
        unchanged_flags = unchanged.to_pylist() if unchanged is not None else [True] * len(paired_new)
    else:
        unchanged_flags = [False] * len(paired_new)
    changed_new = {row for row, same in zip(paired_new, unchanged_flags, strict=True) if not same}

    def as_dicts(table, indices):
        if not indices:
            return {}
        return dict(zip(indices, (_as_strings(row) for row in table.take(pa.array(indices)).to_pylist()),
                        strict=True))

    wanted_new = [row for key, row in zip(new_keys, new_rows, strict=True)
                  if key not in old_index or row in changed_new]
    new_dicts = as_dicts(current, wanted_new)
    old_dicts = as_dicts(previous, [old_index[key] for key, row in zip(new_keys, new_rows, strict=True)
                                    if row in changed_new and before_images]
                         + [old_index[key] for key in missing])

    rows: list[dict] = []
    for key, row in zip(new_keys, new_rows, strict=True):
        if key not in old_index:
            rows.append({**new_dicts[row], "_change": INSERT})
        elif row in changed_new:
            if before_images:
                rows.append({**old_dicts[old_index[key]], "_change": UPDATE_BEFORE})
            rows.append({**new_dicts[row], "_change": UPDATE})
    for key in missing:
        rows.append({**old_dicts[old_index[key]], "_change": DELETE})
    return ChangeSet(rows=rows, suspected_partial_read=False)
