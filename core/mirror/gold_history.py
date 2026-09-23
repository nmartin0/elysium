"""What changed between two gold publications (GOLD-4).

WHY IT LIVES AT GOLD rather than at silver. A changelog is only worth
keeping about things people refer to, and what people refer to is
OBJECTS: "when did this customer's region change", not "when did
column cust_region change in table customers". Gold is the first layer
where a row IS an object, keyed by the object's id, with the
ontology's property names -- so a change recorded here can be read
back in the same words a person asked the question in.

IT DIFFS PUBLICATIONS, NOT SYNCS. Every publication is tagged
(patch 341), so "the previous publication" is a thing that exists and
can be read back exactly. Two syncs that changed nothing produce no
publication and therefore no history, which is correct: nothing
happened.

THE DIFF ITSELF IS core/mirror/changelog.py, which was written for
this and never called until now -- identifier mode, rows compared
whole, an empty previous reported honestly as all-inserts for the
caller to decide about.

NO DUCKDB, AND THE ROADMAP EXPECTED ONE. D5 accepted DuckDB "when the
changelog lands", on a measurement of 76 ms for 200,000 rows. MEASURED
HERE BEFORE ADDING IT: the pure-Python diff already in the tree takes
377 ms for the same 200,000 rows. Five times slower, and irrelevant --
this runs once per publication, beside a sync that takes seconds. A
dependency bought for 300 ms once a night is a dependency bought for
nothing, so it is not bought. If a deployment ever publishes millions
of rows hourly, the measurement to repeat is above.
"""

from typing import Any

import pyarrow as pa
from pyiceberg.exceptions import NoSuchNamespaceError, NoSuchTableError

from core.mirror.changelog import diff_snapshots

CHANGELOG_NAMESPACE = "gold_history"

# What a changelog row holds. The object's id and what happened to it,
# plus the values AS OF that change -- stored as text, because this
# table spans every property of every version and a person reading
# history wants to see what was written, not to filter on it.
CHANGE_COLUMN = "_change"
CHANGED_AT_COLUMN = "_changed_at"
SNAPSHOT_COLUMN = "_publication"


def _changelog_schema(id_field: str) -> pa.Schema:
    return pa.schema([
        (id_field, pa.string()),
        (CHANGE_COLUMN, pa.string()),
        (CHANGED_AT_COLUMN, pa.string()),
        (SNAPSHOT_COLUMN, pa.string()),
        # The row as it stood, JSON-encoded. ONE COLUMN rather than one
        # per property, because an object type's properties change over
        # time and a history table that changes shape with them cannot
        # answer questions about the past in the past's terms.
        ("values", pa.string()),
    ])


def record_publication(catalog, object_type: str, id_field: str,
                        previous_rows: "list[dict] | None", current_rows: list[dict],
                        published_at: str, snapshot_id: Any) -> int:
    """Append what changed since the last publication. Returns how many.

    RECORDS NOTHING ON THE FIRST PUBLICATION. A first build has no
    previous state, and writing every existing row as an INSERT would
    claim a history that did not happen -- the changelog module reports
    that case honestly and leaves the decision here.

    RECORDS NOTHING WHEN A READ LOOKS PARTIAL, and that guard lives in
    diff_snapshots rather than here: it returns NO ROWS at all when a
    publication has lost more than half of them, because a changelog
    full of imaginary deletions is worse than a gap -- a gap is
    visible. Checking it again here read as defence and was DEAD CODE:
    the control that removed it could not fail. The guarantee is
    depended on, so it is tested where it is made.
    """
    import json

    if previous_rows is None:
        return 0
    changes = diff_snapshots(previous_rows, current_rows, id_field)
    if changes.is_empty:
        return 0

    rows = [
        {
            id_field: str(row.get(id_field)),
            CHANGE_COLUMN: row["_change"],
            CHANGED_AT_COLUMN: published_at,
            SNAPSHOT_COLUMN: str(snapshot_id),
            "values": json.dumps(
                {key: (None if value is None else str(value))
                 for key, value in row.items() if key != "_change"},
                sort_keys=True,
            ),
        }
        for row in changes.rows
    ]
    schema = _changelog_schema(id_field)
    identifier = f"{CHANGELOG_NAMESPACE}.{object_type}"
    try:
        catalog.create_namespace(CHANGELOG_NAMESPACE)
    except Exception:  # noqa: BLE001 - already there is the normal case
        pass
    try:
        table = catalog.load_table(identifier)
    except (NoSuchTableError, NoSuchNamespaceError):
        table = catalog.create_table(identifier, schema=schema)
    # APPEND, NEVER OVERWRITE: history that can be rewritten is not
    # history. The audit log makes the same promise in the same words.
    table.append(pa.Table.from_pylist(rows, schema=schema))
    return len(rows)


def history_for(catalog, object_type: str, id_field: str, object_id: Any) -> list[dict]:
    """Every recorded change to one object, oldest first.

    Reads the whole changelog for the type and filters here rather than
    pushing a predicate: a changelog is small relative to the data it
    describes, and this is asked one object at a time by a person
    looking at that object.
    """
    import json

    try:
        table = catalog.load_table(f"{CHANGELOG_NAMESPACE}.{object_type}")
    except (NoSuchTableError, NoSuchNamespaceError):
        return []
    wanted = str(object_id)
    found = [
        {
            "change": row[CHANGE_COLUMN],
            "changed_at": row[CHANGED_AT_COLUMN],
            "publication": row[SNAPSHOT_COLUMN],
            "values": json.loads(row["values"]),
        }
        for row in table.scan().to_arrow().to_pylist()
        if row[id_field] == wanted
    ]
    return sorted(found, key=lambda entry: entry["changed_at"])
