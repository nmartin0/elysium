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

from pyiceberg.exceptions import NoSuchNamespaceError, NoSuchTableError

from core.mirror.gold_history import CHANGELOG_NAMESPACE as GOLD_HISTORY_NAMESPACE
from core.mirror.manifest import (
    describes_a_different_deployment,
    latest_published,
)
from core.mirror.quarantine_report import QUARANTINE_PREFIX
from core.ontology.gold_view import GOLD_NAMESPACE


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


def unreadable_tables(catalog, identifiers) -> dict[str, str]:
    """{identifier: why} for each table the catalog NAMES but cannot be
    read -- the catalog and the warehouse disagreeing.

    A table that is simply not there yet is not a disagreement: the
    first sync of a table finds nothing and that is normal.

    WHY THE SYNC ASKS THIS FIRST. Iceberg commits by writing a metadata
    file and then swapping the catalog's pointer, and pyiceberg does
    not fsync the file -- so a full disk or a power cut can leave the
    pointer naming content that never landed. It happened to this
    project's own development mirror: the catalog named metadata file
    00008 and only 00007 existed. Until now the sync discovered that
    by dying inside pyiceberg with a bare FileNotFoundError naming a
    path, after reading the source for nothing.
    """
    broken: dict[str, str] = {}
    for identifier in identifiers:
        try:
            catalog.load_table(identifier)
        except (NoSuchTableError, NoSuchNamespaceError):
            continue
        except (FileNotFoundError, OSError, ValueError) as exc:
            broken[identifier] = str(exc)
    return broken


def describe_disagreement(broken: dict[str, str]) -> str:
    """What to tell an operator, including how to repair it."""
    lines = [
        "The catalog and the warehouse disagree, so this sync has done "
        "nothing and the mirror is unchanged:",
    ]
    for identifier, why in sorted(broken.items()):
        lines.append(f"  {identifier}: {why}")
    lines.append(
        "\nThe catalog names metadata that is not on disk -- a full disk or a "
        "power cut between the write and the pointer swap. Repair it with: "
        "python -m scripts.repair_catalog"
    )
    return "\n".join(lines)


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

        # QUARANTINED ROWS ARE NOT MISSING ROWS (PA001-I1). A row held
        # back by a declared expectation or the duplicate policy is a
        # DELIBERATE outcome, and it is still in the lake -- in
        # quarantine_<silo>, on purpose, where an operator can look at
        # it.
        #
        # Without this, a deployment whose quarantine is doing its job
        # reported "serving 1 rows against 3 fetched -- silver refused
        # to accept what bronze fetched" every time anyone looked:
        # the same false alarm as the gold one, wearing different
        # words.
        silver_rows += _quarantined_rows(catalog, identifier)

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

    _check_changelog_names_real_objects(catalog, silver, report)

    _check_the_lake_manifest(catalog, report)

    if warehouse_dir is not None:
        _check_for_orphaned_data_files(catalog, warehouse_dir,
                                        silver | bronze, report)

    if warehouse_dir is not None:
        # EVERYTHING THE CATALOG LISTS, not just the source layers.
        # Passing `silver | bronze` meant every gold table and every
        # changelog table on disk was reported as "data the catalog
        # does not know about" -- on a healthy deployment, every run.
        # They are listed; this check simply was not told about them.
        #
        # The third false alarm of this shape: PA001-I1 reported gold
        # as having no bronze counterpart, PA001-A18 checked the wrong
        # table for a declared column. A check that cries wolf on a
        # working mirror teaches operators to skip it, which is worse
        # than not having it.
        _check_catalog_covers_warehouse(
            catalog, warehouse_dir, _every_catalogued_table(catalog), report)

    return report


def _partition_tables(catalog) -> tuple[set[str], set[str]]:
    """Every table, split into silver and bronze by namespace."""
    silver: set[str] = set()
    bronze: set[str] = set()
    for namespace in catalog.list_namespaces():
        for identifier in catalog.list_tables(namespace):
            name = ".".join(identifier)
            if _not_a_source_layer(identifier[0]):
                continue
            (bronze if name.startswith("bronze_") else silver).add(name)
    return silver, bronze


# The namespaces the pipeline writes that are NOT a copy of a source
# table (PA001-I1, PA001-F6.4).
NON_SOURCE_NAMESPACES = ("changelog_", GOLD_NAMESPACE, GOLD_HISTORY_NAMESPACE,
                          QUARANTINE_PREFIX)


def _not_a_source_layer(namespace: str) -> bool:
    """Whether a namespace holds something other than a copy of a
    source table.

    WHY THIS EXISTS. `_split_tables` sorted every table that was not
    `bronze_*` or `changelog_*` into SILVER, and the check then
    reported each one as a silver table with no bronze twin. On a
    perfectly healthy deployment:

        gold.Thing: no bronze table, so its rows cannot be traced
        back to what the source said

    Gold is DERIVED from silver and has no bronze twin BY DESIGN, and
    neither does gold_history or a quarantine table.

    WHY IT MATTERS MORE THAN ITS SEVERITY SUGGESTS, in the audit's own
    words: "a check that always reports problems on a healthy
    deployment trains operators to ignore it, which is how F1 and F2
    go unnoticed". F1 and F2 were real, and that is exactly how they
    hid -- behind a check nobody believed.

    NAMED CONSTANTS, NOT LITERALS (PA001-F6.4). The layers were
    identified by hand-written prefixes in this file, so renaming a
    namespace anywhere else would silently re-sort its tables into
    silver and bring the false alarm straight back.
    """
    return namespace.startswith(NON_SOURCE_NAMESPACES)


def _quarantined_rows(catalog, silver_identifier: str) -> int:
    """How many of this table's rows were held back on purpose.

    Silver plus quarantine is what bronze fetched. Counting only
    silver makes every quarantined row look like a row silver refused
    to interpret -- which is what quarantine IS, except that it is the
    designed outcome rather than a fault, and the row is still in the
    lake for somebody to look at.
    """
    namespace, _, table = silver_identifier.partition(".")
    return _row_count(catalog, f"{QUARANTINE_PREFIX}{namespace}.{table}") or 0


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


def _check_the_lake_manifest(catalog, report) -> None:
    """What the lake says about itself, against what it holds.

    The lake-metadata design note answered this before there was a reader:
    "reads it and REPORTS, never loads it silently.
    `scripts/check_mirror` is the natural home: a lake whose manifest
    describes types the running ontology does not have is exactly the
    mismatch someone needs told about, and refusing to start over it
    would turn a stale copy into an outage."

    MANIFESTS HAVE BEEN WRITTEN SINCE PATCH 427 AND NOTHING READ ONE.
    The note named the reader, its home, and why it must report rather
    than refuse. Only the code was missing.

    QUIET WITH NO MANIFEST: a lake written before manifests existed,
    or one that has never synced, is not a fault.
    """
    try:
        manifest = latest_published(catalog)
    except Exception:  # noqa: BLE001 - an unreadable lake is reported above
        return
    if manifest is None:
        return
    # LISTED ONLY ONCE A MANIFEST EXISTS. Computing it up front ran
    # list_namespaces on every check, which broke three existing tests
    # whose stub catalog has no such method -- and did the work on
    # every lake that has no manifest at all.
    #
    # EVERYTHING THE CATALOG LISTS, not `silver | bronze`: that
    # reported both gold tables as missing on a healthy lake, the SAME
    # mistake patch 476 fixed in the warehouse check four patches ago.
    try:
        tables = _every_catalogued_table(catalog)
    except Exception:  # noqa: BLE001 - an unlistable catalog is reported above
        return
    mismatch = describes_a_different_deployment(manifest, tables)
    if mismatch is not None:
        report.note(mismatch)


def _check_for_orphaned_data_files(catalog, warehouse_dir: Path,
                                    tables: set[str], report) -> None:
    """Data files no live snapshot references.

    EXPIRY UNREFERENCES; IT DOES NOT DELETE. Bronze keeps two
    snapshots and that is enforced, but the files the expired ones
    pointed at stay on disk for ever: pyiceberg has no orphan sweep
    (apache/iceberg-python #3361).

    MEASURED on the dev deployment with the retention margin shortened
    so expiry actually ran: 92 KB and two parquet files after one
    sync, 512 KB and nine after eight. One file per sync, none ever
    reclaimed. the ELT roadmap called bronze "bounded at roughly 2x
    table size"; it is not.

    THIS ONLY REPORTS, and deliberately. Deleting a data file is a
    deletion against a lake -- it wants the same margin argument
    expiry has and a dry run before it ever writes, which is
    repair_catalog's shape rather than a cron job's. What was missing
    was anybody NOTICING, so that is what this adds.
    """
    for identifier in sorted(tables):
        namespace, table = identifier.split(".", 1)
        directory = warehouse_dir / namespace / table / "data"
        if not directory.is_dir():
            continue
        on_disk = list(directory.glob("*.parquet"))
        if len(on_disk) <= _ORPHAN_TOLERANCE:
            continue
        try:
            live = _files_a_snapshot_references(catalog, identifier)
        except Exception:  # noqa: BLE001 - covered by the checks above
            continue
        orphaned = [path for path in on_disk if path.name not in live]
        if len(orphaned) > _ORPHAN_TOLERANCE:
            total = sum(path.stat().st_size for path in orphaned)
            report.note(
                f"{identifier}: {len(orphaned)} data file(s) "
                f"({total // 1024} KB) that no live snapshot references. "
                f"Expiry unreferences; nothing reclaims. See "
                f"the ELT roadmap."
            )


#: HOW MANY UNREFERENCED FILES ARE ORDINARY. A write in flight and a
#: just-expired snapshot both leave one behind legitimately, so a
#: handful is noise; it is the unbounded GROWTH that is the finding.
_ORPHAN_TOLERANCE = 4


def _files_a_snapshot_references(catalog, identifier: str) -> set[str]:
    """The data files any snapshot still in the table's history uses."""
    table = catalog.load_table(identifier)
    referenced: set[str] = set()
    for snapshot in table.snapshots():
        for manifest in snapshot.manifests(table.io):
            for entry in manifest.fetch_manifest_entry(table.io):
                referenced.add(entry.data_file.file_path.rsplit("/", 1)[-1])
    return referenced


def _check_changelog_names_real_objects(catalog, silver: set[str],
                                         report) -> None:
    """Every changelog entry names an object the table held.

    BACKLOG.md left this explicitly unchecked: "whether every
    changelog entry names an object that existed. The changelog is
    append-only history whose row count deliberately matches nothing,
    so it needs its own reasoning rather than an extension of these
    rules."

    THE REASONING. An id in the changelog is accounted for if silver
    still holds it, OR if the changelog itself records a DELETE for
    it. Anything else is history describing an object that is not
    there and was never recorded as leaving -- which means either the
    changelog gained an entry for something that never existed, or a
    row vanished from silver without the deletion being written.

    A ROW COUNT PROVES NOTHING HERE, which is why this is its own
    function. The changelog grows forever while silver holds only the
    current rows; the two are SUPPOSED to disagree, and the existing
    bronze-versus-silver comparison would report every healthy
    deployment.

    QUIET WHEN THERE IS NO CHANGELOG. A deployment that has synced
    once has silver and no history yet, and that is not a fault.
    """
    from core.mirror.changelog import DELETE

    for identifier in sorted(silver):
        silo, table = identifier.split(".", 1)
        changelog_identifier = f"changelog_{silo}.{table}"
        try:
            entries = catalog.load_table(
                changelog_identifier).scan().to_arrow().to_pylist()
        except Exception:  # noqa: BLE001 - absent or unreadable, see below
            # NOT REPORTED. A changelog that cannot be read at all is
            # already covered by the catalog-versus-warehouse check,
            # and a changelog that does not exist yet is ordinary.
            continue
        if not entries:
            continue

        id_column = _changelog_id_column(entries[0])
        if id_column is None:
            report.note(
                f"{changelog_identifier}: no id column, so its entries "
                f"cannot be matched to any object"
            )
            continue

        try:
            live = {
                str(row[id_column])
                for row in catalog.load_table(
                    identifier).scan().to_arrow().to_pylist()
                if id_column in row
            }
        except Exception:  # noqa: BLE001 - reported by the checks above
            continue

        deleted = {str(e[id_column]) for e in entries
                   if e.get("_change") == DELETE}
        named = {str(e[id_column]) for e in entries}
        unaccounted = sorted(named - live - deleted)
        if unaccounted:
            shown = ", ".join(repr(value) for value in unaccounted[:5])
            report.note(
                f"{changelog_identifier}: {len(unaccounted)} id(s) in the "
                f"history are not in {identifier} and were never recorded "
                f"as deleted -- {shown}"
            )


def _changelog_id_column(entry: dict) -> "str | None":
    """The column a changelog entry identifies its object by.

    NAMED BY ELIMINATION rather than assumed: the changelog carries the
    source row's own columns plus `_change` and the lineage columns, so
    the id is whichever column the silver table uses as its key. The
    first non-system column ending in `id` is the convention this
    project already follows everywhere else.
    """
    for column in entry:
        if column.startswith("_"):
            continue
        if column == "id" or column.endswith("_id"):
            return column
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

        # BY SILO AND TABLE, not by table name alone (PA001-A18). The
        # old match compared `name.split(".", 1)[1] == table_name`, so
        # two silos with a table of the same name -- `customers` is
        # not an unusual name -- matched both, and `matching[0]` took
        # whichever sorted first. Measured: a type declaring silo `q`
        # was checked against `p.customers` and reported a column
        # missing from a table it does not use.
        storages = {None: storage, **(type_def.get("additional_storage") or {})}
        columns_by_storage: dict = {}
        for key, block in storages.items():
            silo = (block or {}).get("silo")
            bare = (block or {}).get("table")
            if silo is None:
                # NO SILO DECLARED. Real schemas always name one; some
                # test fixtures do not, and refusing them would break
                # callers to fix a fault they do not have. Fall back to
                # the bare name, which is what this check did for
                # everybody until now -- the AMBIGUITY is the bug, and
                # a schema with one silo has none.
                candidates = sorted(s for s in silver
                                     if s.split(".", 1)[1] == bare)
                identifier = candidates[0] if candidates else f"?.{bare}"
            else:
                identifier = f"{silo}.{bare}"
            if identifier not in silver:
                report.note(
                    f"{object_type}: declared table {identifier!r} is not in "
                    f"the mirror"
                )
                continue
            try:
                columns_by_storage[key] = set(
                    catalog.load_table(identifier).schema().column_names)
            except Exception:  # noqa: BLE001 - reported below as unreadable
                report.note(f"{identifier}: could not be read")

        for field_name, field_def in (type_def.get("fields") or {}).items():
            # LINKS HAVE NO COLUMN OF THEIR OWN when they are declared
            # on the far side, so their absence is not a fault.
            if field_def.get("type") == "link":
                continue
            # WHERE THE FIELD ACTUALLY LIVES. A fused type keeps some
            # fields in another silo entirely, and checking every field
            # against the PRIMARY table reported a perfectly healthy
            # deployment as broken -- the same fault as PA001-I1, one
            # function along.
            where = field_def.get("storage")
            if where not in columns_by_storage:
                continue
            column = field_def.get("column", field_name)
            if column not in columns_by_storage[where]:
                block = storages[where] or {}
                report.note(
                    f"{object_type}.{field_name}: declared but column {column!r} "
                    f"is missing from {block.get('silo')}.{block.get('table')}"
                )


def _every_catalogued_table(catalog) -> set[str]:
    """Every table the catalog lists, in every namespace.

    BY ASKING THE CATALOG rather than by listing the namespaces we
    expect. A namespace nobody thought of -- a new layer, a rename --
    would otherwise be reported as unknown data the moment it appears.
    """
    tables: set[str] = set()
    for namespace in catalog.list_namespaces():
        for identifier in catalog.list_tables(namespace):
            tables.add(".".join(identifier))
    return tables


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
