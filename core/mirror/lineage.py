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
    """Each row, carrying where it came from and what it held."""
    return [
        {
            **row,
            SILO_COLUMN: silo_name,
            SOURCE_TABLE_COLUMN: table_name,
            ROW_HASH_COLUMN: row_hash(row, columns),
        }
        for row in rows
    ]
