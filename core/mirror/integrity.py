"""
integrity.py  (does the mirror still make sense on its own terms?)

WHAT THIS ANSWERS, and it is a narrow question deliberately: given a
warehouse and a catalog, is what they contain self-consistent? Not "is
the data correct" -- correctness is a property of the SOURCE, and the
mirror cannot know it. Self-consistency is a property of the mirror,
and the mirror is the only thing that can check it.

WHY IT MATTERS MORE THAN IT USED TO. Until the changelog existed,
everything here was derivable: if the mirror was wrong, delete it and
re-sync. The changelog is not derivable -- a source holds "now" and
cannot tell you what a value used to be -- so from that point on the
mirror holds something only it holds, and "is it intact" becomes a
question with consequences.

WHAT EACH CHECK IS FOR:

  SILVER HAS A BRONZE. Silver is derived FROM bronze, so a silver
  table with no bronze counterpart is either a sync that half-failed
  or a layer someone built by hand. Both are worth knowing about.

  ROW COUNTS AGREE. Bronze and silver hold the same rows; only the
  types differ. A count mismatch means a transform dropped rows
  silently, which no other check would catch.

  DECLARED COLUMNS ARE PRESENT. The ontology says a field exists;
  silver either has that column or the UI shows a blank cell for a
  field the schema promised.

  THE CATALOG LISTS WHAT THE WAREHOUSE HOLDS. A table on disk that the
  catalog does not know about is invisible and unreadable. This is the
  check that matters most for a teardown, because our catalog is a
  SQLite file beside the warehouse -- lose it and the lake is a
  directory of Parquet nobody can interpret.

REPORTS RATHER THAN RAISES. An integrity problem is something a person
decides about, and one that stopped the process at the first fault
would hide the rest. A caller that wants an exception can read the
report and raise its own.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IntegrityReport:
    """What was checked, and what did not hold."""

    tables_checked: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def note(self, problem: str) -> None:
        self.problems.append(problem)


def check_mirror(catalog, schema: dict | None = None,
                  warehouse_dir: Path | None = None) -> IntegrityReport:
    """Checks a mirror's internal consistency.

    THE SCHEMA IS OPTIONAL, because the most valuable case is the one
    where it is absent: a lake preserved through a teardown, being
    inspected before a new Elysium is configured on top of it. The
    structural checks still run; the ontology-aware ones are skipped
    rather than guessed at.
    """
    report = IntegrityReport()

    silver, bronze = _partition_tables(catalog)
    report.tables_checked = len(silver) + len(bronze)

    for identifier in sorted(silver):
        silo, table_name = identifier.split(".", 1)
        bronze_identifier = f"bronze_{silo}.{table_name}"

        if bronze_identifier not in bronze:
            # A SYNC THAT HALF-FAILED, or a layer built by hand. Bronze
            # tolerates its own failures so the sync can continue, so
            # this is exactly the state that tolerance produces.
            report.note(
                f"{identifier}: no bronze table, so its rows cannot be traced "
                f"back to what the source said"
            )
            continue

        silver_rows = _row_count(catalog, identifier)
        bronze_rows = _row_count(catalog, bronze_identifier)
        # NAME THE TABLE THAT FAILED, not the pair. A first version
        # reported the silver identifier whichever of the two could not
        # be read, so a broken BRONZE table was reported as a broken
        # silver one -- and the first thing anyone does with that
        # message is look at the wrong table.
        if silver_rows is None:
            report.note(f"{identifier}: could not be read")
        if bronze_rows is None:
            report.note(f"{bronze_identifier}: could not be read")
        if silver_rows is None or bronze_rows is None:
            continue

        if silver_rows != bronze_rows:
            # THE DIRECTION SAYS WHICH FAULT IT IS, and a first version
            # reported both as "a transform dropped rows silently".
            # That is right for one of them and misleading for the
            # other -- seen on a real deployment reporting 67 served
            # against 7 fetched, where nothing had been dropped and
            # silver was simply months out of date.
            #
            # FEWER SERVED THAN FETCHED: bronze took rows silver
            # refused to interpret, so the last sync was rejected.
            #
            # MORE SERVED THAN FETCHED: bronze is current and silver is
            # not, which happens when the source SHRANK and the sync
            # that would have shrunk silver was refused.
            #
            # Either way the last successful sync is older than the
            # last attempt, which is the fact worth reporting.
            behind = "refused to accept what bronze fetched" \
                if silver_rows < bronze_rows \
                else "is older than bronze, which has since shrunk"
            report.note(
                f"{identifier}: serving {silver_rows} rows against "
                f"{bronze_rows} fetched -- silver {behind}"
            )

    if schema is not None:
        _check_declared_columns(catalog, schema, silver, report)

    if warehouse_dir is not None:
        _check_catalog_covers_warehouse(catalog, warehouse_dir, silver | bronze, report)

    return report


def _partition_tables(catalog) -> tuple[set[str], set[str]]:
    """Every table, split into silver and bronze by namespace."""
    silver: set[str] = set()
    bronze: set[str] = set()
    for namespace in catalog.list_namespaces():
        for identifier in catalog.list_tables(namespace):
            name = ".".join(identifier)
            # CHANGELOG TABLES ARE NEITHER, and are excluded rather
            # than mis-sorted: they are append-only history whose row
            # count deliberately does NOT match anything.
            if name.startswith("changelog_"):
                continue
            (bronze if name.startswith("bronze_") else silver).add(name)
    return silver, bronze


def _row_count(catalog, identifier: str) -> "int | None":
    """How many rows a table holds, from METADATA rather than data.

    `scan().to_arrow().num_rows` reads every row to learn how many
    there are. Measured at 70ms on a SEVEN-ROW table, because the cost
    is materialising an Arrow table rather than the rows themselves --
    so it does not get better with fewer rows and gets much worse with
    more.

    ICEBERG ALREADY KNOWS. Every snapshot carries `total-records` in
    its summary, maintained as part of the commit. Reading it takes
    0.9ms, agrees with the scan on every table checked, and is the
    number Iceberg itself uses.

    THAT MATTERS BECAUSE OF WHO CALLS THIS. The mirror panel counts
    two layers per table on every load, so a fifty-table deployment
    was scanning a hundred tables to draw a screen -- which ruled out
    refreshing it, which was the gap that prompted looking.

    FALLS BACK TO SCANNING when a snapshot has no summary. Old tables
    written by other tools may not carry one, and a slow count beats
    no count.
    """
    try:
        table = catalog.load_table(identifier)
        snapshot = table.current_snapshot()
        if snapshot is not None:
            recorded = snapshot.summary.get("total-records")
            if recorded is not None:
                return int(recorded)
        return table.scan().to_arrow().num_rows
    except Exception:  # noqa: BLE001 - see below
        # BROAD ON PURPOSE, and differently from manifest.py, which an
        # audit narrowed. The distinction is what the caller does with
        # it: there, a swallowed error became a warning that
        # MISDIAGNOSED the fault. Here, whatever went wrong, the true
        # statement is "this table could not be read" -- which is
        # exactly what gets reported.
        #
        # A programming error still surfaces, as a problem in the
        # report rather than a crash. That is acceptable for a check
        # whose whole job is to list what is wrong.
        return None


def _check_declared_columns(catalog, schema: dict, silver: set[str],
                             report: IntegrityReport) -> None:
    """Every field the ontology declares should exist in silver.

    A MISSING COLUMN IS INVISIBLE WITHOUT THIS. The UI renders a blank
    cell, which reads as "this object has no value" rather than "this
    column was never synced" -- and those are very different things to
    tell someone.
    """
    for object_type, type_def in schema.items():
        storage = type_def.get("storage") or {}
        table_name = storage.get("table")
        if table_name is None:
            continue

        matching = [name for name in silver if name.split(".", 1)[1] == table_name]
        if not matching:
            report.note(
                f"{object_type}: declared table {table_name!r} is not in the mirror"
            )
            continue

        try:
            present = set(catalog.load_table(matching[0]).schema().column_names)
        except Exception:  # noqa: BLE001 - reported below as unreadable
            report.note(f"{matching[0]}: could not be read")
            continue

        for field_name, field_def in (type_def.get("fields") or {}).items():
            # LINKS HAVE NO COLUMN OF THEIR OWN when they are declared
            # on the far side, so their absence is not a fault.
            if field_def.get("type") == "link":
                continue
            column = field_def.get("column", field_name)
            if column not in present:
                report.note(
                    f"{object_type}.{field_name}: declared but column {column!r} "
                    f"is missing from {matching[0]}"
                )


def _check_catalog_covers_warehouse(catalog, warehouse_dir: Path,
                                     known: set[str], report: IntegrityReport) -> None:
    """Data on disk the catalog does not know about.

    THE CHECK THAT MATTERS MOST FOR A TEARDOWN. Our catalog is a SQLite
    file beside the warehouse; lose it and the lake becomes a directory
    of Parquet nobody can interpret. This is how that is noticed while
    it is still recoverable.

    BY DIRECTORY, not by Parquet file. A table's data files live under
    <warehouse>/<namespace>/<table>/, so a directory holding a
    `metadata` folder is a table -- and one the catalog has not listed
    is one nothing can read.
    """
    if not warehouse_dir.is_dir():
        report.note(f"warehouse directory {warehouse_dir} does not exist")
        return

    for metadata_dir in warehouse_dir.rglob("metadata"):
        if not metadata_dir.is_dir():
            continue
        table_dir = metadata_dir.parent
        namespace = table_dir.parent.name
        identifier = f"{namespace}.{table_dir.name}"
        if identifier not in known and not identifier.startswith("changelog_"):
            report.note(
                f"{identifier}: data is on disk but the catalog does not list it, "
                f"so nothing can read it"
            )
