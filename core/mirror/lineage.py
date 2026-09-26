"""Where a silver row came from (GOLD-1, MEDALLION_PIPELINE.md's S6).

WHY GOLD NEEDS IT: when two sources disagree about one entity's field,
survivorship has to say which source won and a person has to be able to
check. A value with no provenance cannot be argued with.

THE SPLIT IS BY STABILITY, and it is not cosmetic. The sync skips
writing a new snapshot when the source is unchanged -- measured at
27.2 MB down to 0.9 -- and that skip compares the rows it would write
against the rows already there. A per-row timestamp changes every run,
so it would defeat the skip and grow the mirror on every sync forever.

  PER ROW, stable unless the row itself changes:
    _silo, _source_table   where this row came from. A gold table
                           merges several, so the row must carry it.
    _row_hash              what this row's declared values were, so a
                           change can be recognised without comparing
                           every column -- what the changelog (GOLD-4)
                           will diff on.

  PER TABLE, as properties, because they are facts about the RUN:
    elysium.source_read_started_at   already there, for the overlay.
    elysium.bronze_snapshot_id       which bronze snapshot silver was
                                     derived from, so any row traces
                                     back to what the source said.
"""

import hashlib
import json

SILO_COLUMN = "_silo"
SOURCE_TABLE_COLUMN = "_source_table"
ROW_HASH_COLUMN = "_row_hash"
LINEAGE_COLUMNS = (SILO_COLUMN, SOURCE_TABLE_COLUMN, ROW_HASH_COLUMN)

# EVERY COLUMN THE PIPELINE WRITES FOR ITSELF, in one place so the
# check that refuses a collision cannot drift from the set it guards.
# The fusion and link-id columns are declared in their own modules;
# importing them here would make lineage depend on both, so they are
# named and a test asserts the two lists agree.
SYSTEM_COLUMNS = (*LINEAGE_COLUMNS, "_fused_from", "_link_id")


def collides_with_a_system_column(names) -> list[str]:
    """Which of these names the pipeline would overwrite.

    WHY THIS EXISTS. `with_lineage` spreads its own values AFTER the
    row, so last-write-wins destroyed any source column called
    `_silo`, `_source_table` or `_row_hash`:

        source: {'customer_id': 'c1', '_silo': 'CUSTOMER VALUE'}
        silver: {'customer_id': 'c1', '_silo': 'primary_sql'}

    No error, no warning, no drift report. Leading underscores are not
    exotic -- they appear routinely in exports, staging tables and
    ORM-generated schemas.

    AND IF THE ONTOLOGY DECLARES THE NAME it is worse in a different
    way: gold's schema gains the column twice and the build raises
    "Column _silo does not exist in schema" -- an opaque message at
    gold-build time rather than a refusal at load.

    THE SECURITY CASE IS WHY IT IS URGENT. A type declaring
    `security: field: _silo` would compare every reader against the
    string "primary_sql" -- identical for every row in the silo. Not
    the wrong compartment: NO compartment. Remote, but it is the same
    failure class as standardising the security field, and it costs
    one list to close.

    FOUND BY THE SECURITY AGENT (LLM3).
    """
    return sorted(set(names) & set(SYSTEM_COLUMNS))

BRONZE_SNAPSHOT_PROPERTY = "elysium.bronze_snapshot_id"


def row_hash(row: dict, columns) -> str:
    """A stable digest of one row's declared values.

    SORTED AND JSON-ENCODED so it does not depend on dict order or on
    Python's repr, and TYPED with the value's class name so 1 and "1"
    do not collide -- a source that changes a column's type has changed
    the row. Hex-truncated to 32 characters: collision-proof enough to
    say "this row changed", which is all it is asked.
    """
    material = [
        [column, type(row.get(column)).__name__, _encodable(row.get(column))]
        for column in sorted(columns)
    ]
    encoded = json.dumps(material, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:32]


def _encodable(value):
    """JSON cannot hold a date or a Decimal; their text is stable."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def with_lineage(rows: list[dict], columns, silo_name: str, table_name: str) -> list[dict]:
    """Each row, carrying where it came from and what it held.

    REFUSES A SOURCE COLUMN OF ITS OWN NAME rather than overwriting
    it. The values below are spread AFTER the row, so last-write-wins
    silently destroyed any source column called `_silo`,
    `_source_table` or `_row_hash` -- and a source column need not be
    declared in the ontology to be present here.

    THE LOAD-TIME CHECK CANNOT SEE THIS ONE: it reads the schema, and
    this is a column the SOURCE has. So the refusal lives at the point
    of loss, which is also the only place that knows.

    REFUSING COSTS A SYNC; overwriting costs a column, silently, for
    as long as nobody looks.
    """
    # ONLY THE COLUMNS THIS FUNCTION WRITES. The wider SYSTEM_COLUMNS
    # set includes `_link_id`, which ELYSIUM ITSELF adds to a join
    # table (PA001-A2's composite key), and `_fused_from`, which gold
    # adds -- so checking the wide set here refused Elysium's own
    # columns and broke every many-to-many sync. Caught by the suite,
    # not by reasoning.
    #
    # The load-time check uses the wide set, correctly: a DECLARED
    # field of any of those names is a mistake wherever it appears.
    clashes = sorted(set(columns) & set(LINEAGE_COLUMNS))
    if clashes:
        raise ValueError(
            f"{silo_name}.{table_name} has {', '.join(repr(c) for c in clashes)}, "
            f"which the pipeline writes for itself -- copying this table would "
            f"replace {'those columns' if len(clashes) > 1 else 'that column'} "
            f"with Elysium's own value. Rename the source column, or exclude it "
            f"from the declared fields."
        )
    return [
        {
            **row,
            SILO_COLUMN: silo_name,
            SOURCE_TABLE_COLUMN: table_name,
            ROW_HASH_COLUMN: row_hash(row, columns),
        }
        for row in rows
    ]
