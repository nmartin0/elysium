"""How many stored values will not convert to a field's new type (R3).

BLOCKING.md, "RETYPE, CHECKED AND SLICED": the count is made from BRONZE,
before the retype is applied, so the person can see how many values would
fail. Bronze holds every raw value as text and is what silver is rebuilt
from, so it is the one place that answers for the rebuild.

THE COUNT IS THE REBUILD'S OWN CONVERSION, not a look-alike: each value goes
through core/mirror/transform.transform_rows with the options the sync gives
it (the column's cleaning rules, the silo's locale for columns that arrived as
text, the silo's date quirks), and a value counts when that raises what the
sync turns into a type mismatch.

WHAT IT IS NOT, and the screen says so:

  * Bronze as of its last snapshot (`as_of`). A value the source has changed
    since is not in it, and the rebuild does not read the source again.
  * Not the rebuild itself. The sync may set aside or drop rows for other
    reasons, and a value in a row it does not keep is still counted here.
  * Values, not rows: one column, so the two are the same number, but what
    happens to them differs (refuse stops the table; quarantine sets the row
    aside) and is said beside it by core/ontology/retype.stored_data.

NOTHING IS GUESSED. A table too large to count at the preview, a bronze table
that does not exist yet, one without the column, or one that cannot be read
is "not counted", with the reason: never zero.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from pyiceberg.exceptions import NoSuchNamespaceError, NoSuchTableError

from elysium.core.lake_names import BRONZE_PREFIX
from elysium.core.mirror.iceberg_sync import SYNC_BATCH_ROWS
from elysium.core.mirror.incremental import TEXT_COLUMNS_PROPERTY
from elysium.core.mirror.transform import transform_rows

#: The most bronze rows counted while a person waits for the preview. Past it
#: the answer is "not counted", never a count of part of the table.
MAX_ROWS_COUNTED = 2_000_000


@dataclass(frozen=True)
class ConversionCount:
    """One table's column, counted (or not) against a new type."""
    table: str                      # "silo.table"
    column: str
    counted: bool
    checked: int = 0                # values read from bronze
    failing: int = 0                # values that would not convert
    as_of: datetime | None = None   # bronze's last snapshot (UTC)
    why_not: str | None = None      # when not counted


def count_unconvertible(catalog, silo: str, table: str, column: str, declared_type: str, *,
                        standardisation: dict | None = None, locale: str | None = None,
                        excel_dates: bool = False, zero_dates: bool = False,
                        max_rows: int = MAX_ROWS_COUNTED) -> ConversionCount:
    """Reads `column` of bronze and counts the values that will not convert to
    `declared_type`. Never raises for a bronze that cannot serve the count:
    that is a result with `why_not`."""
    name = f"{silo}.{table}"

    def not_counted(why: str) -> ConversionCount:
        return ConversionCount(name, column, False, why_not=why)

    try:
        bronze = catalog.load_table(f"{BRONZE_PREFIX}{silo}.{table}")
    except (NoSuchTableError, NoSuchNamespaceError):
        return not_counted("bronze does not hold this table yet, so there is nothing to count")
    except Exception as e:  # noqa: BLE001 - "cannot count" is an answer here
        return not_counted(f"bronze could not be read ({type(e).__name__})")
    try:
        if column not in bronze.schema().column_names:
            return not_counted(f"bronze does not hold the column {column}")
        snapshot = bronze.current_snapshot()
        as_of = None if snapshot is None else datetime.fromtimestamp(snapshot.timestamp_ms / 1000, tz=UTC)
        if snapshot is None:
            return ConversionCount(name, column, True, 0, 0, None)
        # Only this column, so the table is never held whole.
        values = bronze.scan(selected_fields=(column,)).to_arrow()
        if values.num_rows > max_rows:
            return not_counted(f"bronze holds {values.num_rows:,} rows, more than is counted while you wait")
        text_columns = (set(json.loads(bronze.properties.get(TEXT_COLUMNS_PROPERTY) or "[]"))
                        if locale else set())
        rules = {column: standardisation[column]} if standardisation and column in standardisation else None
        failing = 0
        for batch in values.to_batches(max_chunksize=SYNC_BATCH_ROWS):
            result = transform_rows(batch.to_pylist(), [column], {column: declared_type}, rules,
                                    locale=locale, localised_columns=text_columns,
                                    excel_dates=excel_dates, zero_dates=zero_dates)
            failing += len(result.mismatched_row_indices)
        return ConversionCount(name, column, True, values.num_rows, failing, as_of)
    except Exception as e:  # noqa: BLE001 - "cannot count" is an answer here
        return not_counted(f"bronze could not be read ({type(e).__name__})")
