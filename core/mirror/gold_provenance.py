"""Where one gold row came from: the reader for lineage already written.

DEV_UI.md section 5 item 5 asks for "A PROVENANCE PANEL: which source,
which bronze snapshot, which publication, when", and notes that "the
lineage for this now exists". It does -- and like the changelog before
it, nothing could read it back for one object.

`core/mirror/lineage.py` records the two halves separately, and its own
comment says why the split is not cosmetic: the sync skips writing a
snapshot when the source is unchanged, "measured at 27.2 MB down to
0.9", and a per-row timestamp "would defeat the skip and grow the
mirror on every sync forever". So:

    PER ROW     `_silo`, `_source_table`  -- which source this row came
                from, which a gold table merging several has to carry
                row by row; and `_row_hash`, what its declared values
                were.

    PER TABLE   `elysium.bronze_snapshot_id` -- which bronze snapshot
                silver was derived from, "so any row traces back to what
                the source said"; and `elysium.source_read_started_at`,
                when that read began.

Together those are exactly the four things the panel asks for, and this
function is the one place that puts them back together.

NO ACCESS CONTROL HERE, AND THAT IS DELIBERATE -- the same contract
`read_history` states for itself: this reads the mirror directly, "and
anything exposing it to a user must filter per caller itself". The
route above it does, and a test holds it to that.
"""

from pyiceberg.exceptions import NoSuchNamespaceError, NoSuchTableError

from core.carried_columns import (
    ROW_HASH_COLUMN,
    SILO_COLUMN,
    SOURCE_TABLE_COLUMN,
)
from core.mirror.lineage import BRONZE_SNAPSHOT_PROPERTY
from core.ontology.gold_view import GOLD_NAMESPACE


class ProvenanceNotRecorded(LookupError):
    """The gold table is not there, so nothing can be said about a row
    in it. Distinct from a row that is absent FROM a table that exists,
    which is an ordinary empty answer rather than a fault."""


def read_provenance(catalog, object_type: str, id_field: str,
                    object_id: str) -> "dict | None":
    """Where this one object's row came from, or None if there is no
    such row.

    NONE RATHER THAN AN EXCEPTION for an absent row, because "no such
    object" and "an object you may not read" must look the same to the
    caller above, and that caller cannot make them look the same if one
    of them arrives as a raised error and the other as a value.
    """
    identifier = f"{GOLD_NAMESPACE}.{object_type}"
    try:
        table = catalog.load_table(identifier)
    except (NoSuchTableError, NoSuchNamespaceError):
        raise ProvenanceNotRecorded(identifier) from None

    # THE WHOLE TABLE, filtered here rather than pushed down, matching
    # read_history beside it. A predicate on the id column would be
    # faster and is the obvious next step; it is not this patch's, and
    # doing it here while the changelog reader still scans would leave
    # two readers of the same shape behaving differently for no stated
    # reason.
    for row in table.scan().to_arrow().to_pylist():
        if str(row.get(id_field)) != str(object_id):
            continue
        return {
            "silo": row.get(SILO_COLUMN),
            "source_table": row.get(SOURCE_TABLE_COLUMN),
            "row_hash": row.get(ROW_HASH_COLUMN),
            # PROPERTIES ARE FACTS ABOUT THE RUN, not about the row, so
            # they come off the table and are the same for every row in
            # it. Reporting them per object is still right: the question
            # "where did THIS value come from" is answered by both
            # halves together, and a reader should not have to go and
            # find the other one.
            "bronze_snapshot_id": table.properties.get(BRONZE_SNAPSHOT_PROPERTY),
        }
    return None
