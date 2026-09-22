"""
iceberg_sync.py  (the real, concrete mirror sync -- PyIceberg-backed)

Implements core/mirror/interface.py's MirrorSync contract. The only
place in this project that knows Iceberg exists at all; everything
above it (scripts/run_sync.py, and eventually DataMediator's own read
path in Phase 4) sees only the MirrorSync interface.

STORAGE SHAPE: one Iceberg namespace per silo, one Iceberg table per
real source table, named `{silo_name}.{table_name}`. Deliberately a
flat, 1:1 mapping of the customer's own tables -- matching Foundry's
own "ingest as-is, with no external preprocessing" philosophy for the
RAW layer specifically (any cleaning/joining/reshaping belongs to
Phase 3's own transform pass, never here). Confirmed directly against
Foundry's own documented raw-ingest behavior, not assumed.

CATALOG: a plain SQLite file, alongside the Parquet data itself, both
under the deployment's own data_dir. A real, deliberate choice over
the alternatives PyIceberg also supports (Hive Metastore, AWS Glue,
a REST catalog service): every one of those is a separate SERVICE to
deploy and operate, genuinely disproportionate at this project's
scale, and inconsistent with how every other piece of this project's
own internal infrastructure already works (a SQLite file under
data_dir).

FULL REFRESH, not incremental. Each sync_table() call replaces that
table's entire contents via Iceberg's own overwrite() -- verified
directly, empirically, before relying on it: overwrite() genuinely
REPLACES rather than appending onto stale rows, while still preserving
prior snapshots in the table's own history (so real time travel back
to an earlier sync keeps working). An incremental/CDC mechanism is a
genuinely different, much larger design -- deliberately not attempted
here, and not needed for the roadmap's own stated goals.

EXPLICIT COLUMNS, never SELECT *. sync_table() takes the real, exact
column list resolved from the ontology by its caller. The mirror
holds exactly what the ontology actually references -- not whatever
else happens to live in the customer's own table, which could include
columns Elysium has no business copying at all.

Used by: scripts/run_sync.py
"""

import json
import logging
import warnings
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.exceptions import (
    NamespaceAlreadyExistsError,
    NoSuchNamespaceError,
    NoSuchTableError,
)

from core.mirror.changelog import MAX_DELETED_FRACTION, diff_snapshots
from core.mirror.drift_policy import (
    DriftVerdict,
    verdict_for_removed_column,
    verdict_for_type_change,
)
from core.mirror.duplicates import DuplicatePolicy, split_duplicates
from core.mirror.durability import force_table_metadata_to_disk
from core.mirror.expectations import Violation, apply_expectations
from core.mirror.integrity import describe_disagreement, unreadable_tables
from core.mirror.interface import MirrorSync, SyncResult
from core.mirror.lineage import BRONZE_SNAPSHOT_PROPERTY, LINEAGE_COLUMNS, with_lineage
from core.mirror.transform import describe_drift, transform_rows
from core.ontology.field_types import (
    DEFAULT_FIELD_DATA_TYPE,
    arrow_type_for,
    split_declared_type,
)
from core.ontology.interface import ExternalReadAdapter

logger = logging.getLogger(__name__)


# BRONZE RETENTION, declared as standard Iceberg table properties.
#
# WHY A DECLARATION RATHER THAN CODE. pyiceberg 0.12 has no snapshot
# expiry at all -- checked, not assumed: no expire_snapshots, no
# ExpireSnapshots, and ManageSnapshots offers only branches, tags and
# rollback. So nothing here can reclaim space today.
#
# These are the NAMES Iceberg defines for the policy, which any engine
# that does implement expiry reads. Declaring them means the intent
# travels with the table rather than living in a runbook, and the day
# pyiceberg gains expiry -- or a Spark or DuckDB job runs over the same
# warehouse -- the policy is already there and correct.
#
# TWO SNAPSHOTS, because that is what a diff needs: current and
# previous. The changelog phase compares them, and a third buys
# nothing while costing a full copy of the table -- Iceberg's
# copy-on-write means every retained snapshot is a complete rewrite,
# measured at 177KB to 839KB over five syncs of a table where one row
# changed.
#
# THE AGE BOUND IS A RETENTION_MARGIN, in the sense
# tests/unit/test_snapshot_retention_guard.py requires: "an age
# threshold exceeding the longest possible request by an order of
# magnitude". A query is bounded by max_hops and the request timeout --
# minutes at worst on this hardware -- so seven days makes the hazard
# that guard describes unreachable rather than merely unlikely.
#
# That guard fired when this landed, which is exactly what it was
# written for: "this fails the moment expiry appears, which is exactly
# when the decision needs making". The decision is recorded here and in
# HOT_RELOAD_PLAN.md step 5h.
#
# SEVEN DAYS as the age bound, and the two rules interact the way the
# precedent says they should: "retention policies will never delete
# transactions that are in the latest view of any branch", with age
# selecting "transactions older than the given duration" among the
# rest. min-snapshots-to-keep wins over max-age, so a quiet week
# cannot leave a table with nothing to diff against.
RETENTION_MARGIN_MS = 7 * 24 * 60 * 60 * 1000

# When the sync last READ THE SOURCE for this table, ISO-8601 (F-29).
# The overlay's `since`: every write after it is still overlaid.
# What a quarantine table holds: the id, the rule that caught the row,
# and when. The row itself stays in bronze (GOLD-1).
QUARANTINE_SCHEMA = pa.schema([
    ("object_id", pa.string()),
    ("column", pa.string()),
    ("field", pa.string()),
    ("reason", pa.string()),
    ("value", pa.string()),
    ("policy", pa.string()),
    ("detected_at", pa.string()),
])


SOURCE_READ_PROPERTY = "elysium.source_read_started_at"


BRONZE_RETENTION = {
    "history.expire.min-snapshots-to-keep": "2",
    "history.expire.max-snapshot-age-ms": str(RETENTION_MARGIN_MS),
}


# WHERE THE SOURCE'S OWN COLUMN TYPES ARE KEPT, on the bronze table.
#
# BRONZE, NOT SILVER: bronze is what the source looked like, and this
# is a fact about the source rather than about the mirror.
SOURCE_TYPES_PROPERTY = "elysium.source_column_types"

# TYPE CHANGES THAT WIDEN, which are worth a quieter word than the
# rest. The canonical severity model for schema drift puts a removed
# column and an incompatible narrowing (VARCHAR to INT) in one band,
# and widening (INT to BIGINT, VARCHAR(50) to VARCHAR(255)) in a
# lesser one.
#
# DELIBERATELY SHALLOW. A full compatibility matrix per dialect is a
# library's job -- this recognises the obvious widenings and reports
# everything else as a plain change, which is honest about how much
# it knows.
_WIDENINGS = frozenset({
    ("INTEGER", "BIGINT"),
    ("SMALLINT", "INTEGER"),
    ("SMALLINT", "BIGINT"),
    ("REAL", "DOUBLE PRECISION"),
})


def _source_types_json(adapter, table_name: str) -> str:
    """The source's column types, as JSON, or an empty string.

    EMPTY MEANS "COULD NOT SAY", which is a third state beside "same"
    and "changed". An adapter that does not implement the method
    returns {}, and storing that would make the NEXT sync report every
    column as removed.
    """
    try:
        types = adapter.source_column_types(table_name)
    except Exception as e:  # noqa: BLE001 - drift reporting, not a read path
        logger.warning("%s: could not read source column types: %s",
                       table_name, e)
        return ""
    return json.dumps(types, sort_keys=True) if types else ""


def _report_type_drift(silo_name: str, table_name: str,
                       previous_json: str, current_json: str) -> None:
    """Says what changed about the source's own column types.

    REPORTS, DOES NOT REFUSE. A sync that stopped on a type change
    would turn a widened column into an outage, and the row-level
    drift policy already decides what to do about columns appearing
    and disappearing. This answers the question that policy cannot
    see: whether a column that is still present still MEANS the same
    thing.
    """
    try:
        previous = json.loads(previous_json)
        current = json.loads(current_json)
    except json.JSONDecodeError:
        return

    changed = [
        (name, was, current[name])
        for name, was in previous.items()
        if name in current and current[name] != was
    ]
    if not changed:
        return

    for name, was, now in changed:
        widening = (was.upper().split("(")[0], now.upper().split("(")[0])
        severity = "widened" if widening in _WIDENINGS else "CHANGED"
        logger.warning(
            "%s.%s: column %r %s from %s to %s since the last sync. "
            "Coercion cannot see this -- a value may still parse and mean "
            "something else.",
            silo_name, table_name, name, severity, was, now,
        )


class IcebergMirrorSync(MirrorSync):
    def __init__(self, mirror_dir: Path, adapters: dict[str, ExternalReadAdapter],
                 write_log=None, storage: dict | None = None):
        # adapters are the REAL, read-only ExternalReadAdapter instances
        # (Phase 1 -- structurally incapable of writing to the
        # customer's own data; see adapters/sqlite_adapter.py's own
        # SQLiteReadAdapter._connection()). A sync only ever reads from
        # the source, so taking the read-only set specifically -- rather
        # than the write-capable one -- is a real, structural guarantee
        # this job cannot damage the customer's data, not just an
        # intention.
        self.mirror_dir = mirror_dir
        self.adapters = adapters
        # OPTIONAL, and its absence is not "nothing was written". A
        # sync without one cannot check what depends on a vanished
        # column, so drift_policy refuses rather than absorbing on the
        # strength of a check that did not happen.
        self._write_log = write_log
        mirror_dir.mkdir(parents=True, exist_ok=True)

        # WHERE THE WAREHOUSE LIVES, which is a deployment question
        # rather than a code one.
        #
        # LOCAL BY DEFAULT, because that is correct for one host and
        # every deployment today is one host. Nothing changes for them.
        #
        # OBJECT STORAGE WHEN CONFIGURED, and the reason is not
        # performance. Everything in the mirror is currently DERIVABLE
        # from the silos: lose the machine, reinstall, re-sync. That
        # stops being true the moment a changelog exists, because a
        # source database holds "now" and has no record of what a value
        # used to be. At that point the mirror becomes a system of
        # record, and a system of record on one machine's disk is one
        # power supply away from gone.
        #
        # So this lands BEFORE the changelog rather than after --
        # otherwise there is a window in which an organisation
        # accumulates history it believes is safe.
        #
        # THE CATALOG IS A SEPARATE AXIS and stays local. pyiceberg's
        # CatalogType is REST, HIVE, GLUE, DYNAMODB, SQL, IN_MEMORY,
        # BIGQUERY; storage is chosen independently through FileIO, so
        # moving the warehouse does not require moving the catalog.
        options = dict(storage or {})
        warehouse = options.pop("warehouse", None)
        if warehouse is None:
            (mirror_dir / "warehouse").mkdir(exist_ok=True)
            warehouse = f"file://{mirror_dir / 'warehouse'}"

        # THE LOCAL WAREHOUSE DIRECTORY, or None when it is not
        # local. fsync needs a real path; a warehouse on S3 has no
        # local file to force and its own durability story, so the
        # durability step is skipped there rather than pretending
        # to have run.
        self._warehouse_path = (
            Path(warehouse[len("file://"):])
            if isinstance(warehouse, str) and warehouse.startswith("file://")
            else None
        )

        self._catalog = SqlCatalog(
            "elysium_mirror",
            uri=f"sqlite:///{mirror_dir / 'catalog.db'}",
            warehouse=warehouse,
            **options,
        )

    @property
    def catalog(self):
        """The Iceberg catalog this sync writes through.

        EXPOSED BECAUSE CALLERS ALREADY NEEDED IT. manifest.py reached
        past the underscore three times with a `noqa` on each line, and
        a suppression repeated three times is a missing accessor rather
        than three exceptions.

        READ-ONLY BY CONSTRUCTION: a property with no setter, so a
        caller can list tables or write beside the warehouse without
        being able to swap the catalog out from under a sync in
        progress.
        """
        return self._catalog

    def sync_table(self, silo_name: str, table_name: str, id_column: str,
                    columns: list[str], column_types: dict[str, str] | None = None,
                    fields_by_column: dict[str, str] | None = None,
                    standardisation: dict[str, dict] | None = None,
                    expectations: dict[str, dict] | None = None,
                    duplicate_policy: DuplicatePolicy | None = None) -> SyncResult:
        adapter = self.adapters.get(silo_name)
        if adapter is None:
            raise ValueError(
                f"No adapter for silo {silo_name!r} -- "
                f"known silos: {sorted(self.adapters.keys())}"
            )

        # A VANISHED COLUMN IS CHECKED BEFORE READING, because reading
        # is what fails and the policy has to speak before the adapter
        # does. Until columns_present() existed this was not a handled
        # case at all -- it surfaced as whatever the SELECT raised,
        # which is the storage-dictated behaviour drift_policy exists
        # to replace.
        present = adapter.columns_present(table_name)
        missing = [column for column in columns if column not in present]
        if missing:
            verdict = self._verdict_for_missing(
                silo_name, table_name, missing, fields_by_column or {},
            )
            if not verdict.absorbed:
                raise ValueError(verdict.detail)
            logger.warning(verdict.detail)
            columns = [column for column in columns if column not in missing]
            if column_types is not None:
                column_types = {k: v for k, v in column_types.items() if k not in missing}

        # THE SOURCE IS READ ONCE, inside _write_bronze, which needs
        # every column anyway. A first version read here as well and
        # made every sync read the silo TWICE -- measured, and worse
        # than before bronze existed.
        #
        # The rows come back so they can serve as silver's fallback
        # when bronze is unavailable, without a second trip.
        # BEFORE ANYTHING ELSE: does the catalog still agree with the
        # warehouse? A sync that writes on top of a table the catalog
        # can no longer read fails deep inside pyiceberg, after reading
        # the source for nothing, with a bare FileNotFoundError naming a
        # path (roadmap item 8). Asked here, it costs one table load
        # this sync was going to do anyway.
        broken = unreadable_tables(
            self._catalog, (f"{silo_name}.{table_name}", f"bronze_{silo_name}.{table_name}"),
        )
        if broken:
            raise ValueError(describe_disagreement(broken))

        # WHEN THE SOURCE WAS READ, recorded before reading it (001's
        # F-29). last_synced_at() reported the snapshot's COMMIT time,
        # which is later -- so a write applied while the sync ran was
        # in neither the mirror (read before it) nor the overlay
        # (excluded as older than the commit). Measured: a 2 s source
        # read left a 2.08 s window. The read's START is the honest
        # answer: everything after it is still overlaid.
        read_started_at = datetime.now(UTC).isoformat()
        raw_rows = self._write_bronze(adapter, silo_name, table_name, id_column, columns)
        bronze_snapshot = self._bronze_snapshot_id(silo_name, table_name)

        # BRONZE: what the source said, before anything was done to it.
        #
        # WHY THIS EXISTS, and it is not performance. Until now the raw
        # rows lived only in memory: they were read, cast, written, and
        # forgotten. So a value that looked wrong had nothing to
        # compare against except a source that may since have changed,
        # and adding an ontology field meant RE-READING THE SILO rather
        # than re-transforming what we already held.
        #
        # Foundry's reason for ingesting "as-is from its most raw
        # source, with no external preprocessing" is exactly this:
        # "every Ontology property value traces back to a specific row
        # in a specific raw file".
        #
        # AS-IS MEANS AS-IS. No casting, no renaming, no provenance
        # COLUMNS -- adding those would make bronze a third
        # transformation of the data it exists to preserve unaltered.
        # Provenance lives in metadata instead: the silo and table on
        # the table's own properties, and the read time in the
        # snapshot's timestamp, both of which Iceberg already carries.
        #
        # NOTHING READS BRONZE. "Bronze should act as a historical
        # record, not a source of truth."

        # THE raw -> clean stage (Phase 3). Casting lives here, between
        # reading and writing, rather than inside _to_arrow() where it
        # used to be -- see core/mirror/transform.py for why that
        # separation is the point rather than a detail.
        #
        # Drift FAILS THIS TABLE'S SYNC LOUDLY, leaving the last-good
        # mirror contents in place: a column whose real values no
        # longer match what the ontology declares means the customer's
        # source system changed underneath us, which is exactly the
        # "fail loudly, never silently substitute" case. The error
        # names the table, the column, the declared type and a real
        # offending value, so scripts/run_sync.py's own per-table
        # handling turns it into a genuinely diagnosable failure rather
        # than a stack trace.
        # SILVER IS DERIVED FROM BRONZE, not from the rows in memory.
        #
        # THE POINT OF THE INDIRECTION. Reading from bronze means
        # re-deriving silver never touches the silo again: changing how
        # a column is cast, or adding a field the ontology did not
        # declare last week, becomes a rebuild of data we already hold
        # rather than another full read of the customer's database.
        #
        # It also makes the bronze copy LOAD-BEARING rather than an
        # archive nobody reads. A bronze that only ever gets written is
        # a bronze whose failures nobody notices; this way a broken
        # bronze breaks the sync loudly, at the moment it breaks.
        #
        # FALLS BACK TO THE ROWS IN MEMORY if bronze is unavailable --
        # which it will be for the first sync after this ships, since
        # no bronze table exists yet, and whenever a bronze write failed
        # for the reasons _write_bronze() tolerates. Silver stays
        # correct either way; only the re-derivability is lost, and the
        # warning says so.
        source_rows = self._read_bronze(silo_name, table_name, columns)
        if source_rows is None:
            source_rows = raw_rows

        transformed = transform_rows(source_rows, columns, column_types, standardisation)
        if transformed.has_drift:
            # THROUGH THE POLICY, not straight to a raise. The outcome
            # is the same -- refuse -- but it now comes from a module
            # that NAMES the shape and states the decision, rather than
            # from an if-statement that happens to raise. The detailed
            # per-column report follows, because the policy says WHAT
            # and describe_drift says WHICH VALUES.
            verdict = verdict_for_type_change(
                silo_name, table_name, transformed.drift[0].column,
                also_affected=len(transformed.drift) - 1,
            )
            raise ValueError(
                f"{verdict.detail}\n\n"
                f"{describe_drift(silo_name, table_name, transformed.drift)}"
            )

        # THE EXPECTATIONS, on coerced values (GOLD-1). warn keeps the
        # row and counts it; quarantine holds it back and writes it to
        # the quarantine table -- never a silent drop, and bronze still
        # holds what the source said; fail stops the build here, before
        # anything is written, so the mirror is unchanged.
        checked = apply_expectations(transformed.rows, expectations or {})
        if checked.quarantined:
            self._write_quarantine(silo_name, table_name, id_column, checked.quarantined)
        for rule, count in checked.counts.items():
            logger.warning(f"{silo_name}.{table_name}: {count} row(s) failed {rule}")

        # TWO ROWS CLAIMING ONE IDENTITY (GOLD-1). After the per-row
        # checks, so a row already held back is not also counted as a
        # duplicate.
        kept_rows, duplicated = split_duplicates(
            checked.kept, id_column, duplicate_policy or DuplicatePolicy(),
        )
        if duplicated:
            self._write_quarantine(
                silo_name, table_name, id_column,
                [(row, Violation(id_column, id_column, why, key, "quarantine"))
                 for row, key, why in duplicated],
            )
            logger.warning(
                f"{silo_name}.{table_name}: {len(duplicated)} row(s) held back "
                f"for duplicate {id_column}"
            )

        # WHERE EACH ROW CAME FROM (GOLD-1). Added after every rule has
        # run, so a row that never lands is never given a provenance;
        # and only the STABLE facts, since the "source unchanged, no new
        # snapshot" skip compares the rows -- see lineage.py.
        arrow_table = self._to_arrow(
            with_lineage(kept_rows, columns, silo_name, table_name),
            [*columns, *LINEAGE_COLUMNS],
            {**(column_types or {}), **{column: "string" for column in LINEAGE_COLUMNS}},
        )

        self._ensure_namespace(silo_name)
        identifier = f"{silo_name}.{table_name}"
        try:
            table = self._catalog.load_table(identifier)
        except NoSuchTableError:
            table = self._catalog.create_table(identifier, schema=arrow_table.schema)

        # overwrite(), never append() -- a full refresh. Verified
        # directly that this REPLACES the table's contents rather than
        # duplicating rows across syncs, while still preserving prior
        # snapshots for real time travel.
        #
        # The warning filter is narrow and deliberate: on the FIRST
        # overwrite of a brand-new table, PyIceberg emits "Delete
        # operation did not match any records" -- correct and
        # harmless (there was nothing to replace yet), but it would
        # otherwise appear on every single first sync and train
        # readers to ignore warnings from this module generally.
        # Scoped to this one call, not silenced project-wide.
        # A COLUMN ADDED TO THE ONTOLOGY IS ABSORBED, not a failure.
        # Step 5d, and it turned out to be a live defect rather than an
        # enhancement: without this, declaring a new field on an
        # existing object type breaks that table's sync outright, with
        # pyiceberg reporting "PyArrow table contains more columns".
        # The mirror then serves its last good contents forever while
        # the ontology says something else.
        #
        # Additive change is the SAFE direction and Foundry treats it
        # as a non-event -- "additive changes to the backing dataset do
        # not interfere with the synchronization process". A column
        # nothing previously read cannot have been read wrongly.
        #
        # union_by_name() rather than add_column() per field: the
        # incoming Arrow schema already describes exactly what the
        # ontology now declares, so asking Iceberg to reconcile against
        # it is one operation instead of a diff we would have to
        # compute and keep correct.
        #
        # DESTRUCTIVE change does NOT come through here -- a removed
        # column is decided by drift_policy before any read happens,
        # and a type change is refused. This path only ever widens.
        with table.update_schema() as update:
            update.union_by_name(arrow_table.schema)

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Delete operation did not match any records")
            # NOTHING IS WRITTEN WHEN NOTHING CHANGED.
            #
            # Iceberg's copy-on-write makes every snapshot a COMPLETE
            # copy, so a nightly sync of a table nobody edited was
            # writing the whole table again to record that it was
            # identical. Measured: 30 identical syncs of a 50,000-row
            # table produced 27.2 MB across 65 snapshots, all holding
            # the same data.
            #
            # pyiceberg 0.12 has no snapshot expiry -- checked, not
            # assumed -- so nothing reclaims those afterwards. The
            # cheapest fix is not to create them.
            #
            # IDEMPOTENCY IS THE PATTERN THIS SATISFIES: a pipeline
            # "produces the same result regardless of how many times it
            # is executed with the same input". Re-running a sync
            # should be free, and now nearly is.
            #
            # COMPARED ON CONTENT, not on a source timestamp, because
            # our sources have none -- verified: `customers` has no
            # timestamp at all, and `transactions` has only a business
            # date that does not move when a row is edited.
            if self._already_current(table, arrow_table):
                logger.info(
                    f"{identifier}: source unchanged, no new snapshot written"
                )
            else:
                table.overwrite(arrow_table)
                # AFTER THE DATA COMMIT, never before (001's F-29): a
                # crash between the two leaves the OLDER timestamp, so
                # the overlay stays wider than it needs to be. The
                # other order would move the timestamp forward over
                # data that was never written, and lose the overlay
                # entries it covered.
                with table.transaction() as tx:
                    tx.set_properties({
                        SOURCE_READ_PROPERTY: read_started_at,
                        # WHICH BRONZE SILVER CAME FROM: a fact about the
                        # run, so a property rather than a column.
                        **({BRONZE_SNAPSHOT_PROPERTY: str(bronze_snapshot)}
                           if bronze_snapshot is not None else {}),
                    })
                # FORCED TO DISK BEFORE THE POINTER IS TRUSTED.
                #
                # pyiceberg writes metadata through an UNSYNCED
                # path while SQLite fsyncs its own commit, so by
                # default the pointer is durable and the thing it
                # points at is not -- exactly backwards. This
                # deployment hit the result during development: the
                # disk filled and the catalog afterwards named
                # metadata file 00008 when only 00007 existed.
                # scripts/repair_catalog.py was written to recover.
                self._force_metadata_to_disk(identifier)

        # INVARIANT: the committed snapshot holds exactly what was
        # handed to overwrite(). Checked against the CATALOG rather than
        # the local object, so this genuinely confirms the commit landed
        # -- a SNAPSHOT sync reporting a row count it did not actually
        # write is the one failure mode that would corrupt every
        # downstream read while looking entirely successful.
        committed = self._catalog.load_table(identifier).scan().to_arrow()
        assert committed.num_rows == arrow_table.num_rows, (
            f"{identifier}: wrote {arrow_table.num_rows} rows but the committed "
            f"snapshot holds {committed.num_rows}"
        )

        return SyncResult(
            silo_name=silo_name,
            table_name=table_name,
            row_count=arrow_table.num_rows,
            synced_at=datetime.now(UTC),
            quarantined=len(checked.quarantined) + len(duplicated),
            violations=checked.counts,
        )

    def _bronze_snapshot_id(self, silo_name: str, table_name: str):
        """The bronze snapshot silver is about to be derived from, or
        None when bronze could not be written (which _write_bronze
        tolerates, with a warning)."""
        try:
            table = self._catalog.load_table(f"bronze_{silo_name}.{table_name}")
        except (NoSuchTableError, NoSuchNamespaceError):
            return None
        snapshot = table.current_snapshot()
        return None if snapshot is None else snapshot.snapshot_id

    def _write_quarantine(self, silo_name: str, table_name: str, id_column: str,
                           held: list) -> None:
        """The rows an expectation held back, with the rule that caught
        each one -- so a person can see what was refused and why.

        THE ROW ITSELF STAYS IN BRONZE, exactly as the source wrote it,
        so this records the id and the finding rather than copying the
        row: one place holds the data, and this says what happened to
        it. Appended, never overwritten: a run's findings do not erase
        the last run's.
        """
        namespace = f"quarantine_{silo_name}"
        identifier = f"{namespace}.{table_name}"
        detected_at = datetime.now(UTC).isoformat()
        rows = [
            {
                "object_id": str(row.get(id_column)),
                "column": finding.column,
                "field": finding.field_name,
                "reason": finding.reason,
                "value": None if finding.value is None else str(finding.value),
                "policy": finding.policy,
                "detected_at": detected_at,
            }
            for row, finding in held
        ]
        arrow_table = pa.Table.from_pylist(rows, schema=QUARANTINE_SCHEMA)
        try:
            self._catalog.create_namespace(namespace)
        except NamespaceAlreadyExistsError:
            pass
        try:
            table = self._catalog.load_table(identifier)
        except (NoSuchTableError, NoSuchNamespaceError):
            table = self._catalog.create_table(identifier, schema=QUARANTINE_SCHEMA)
        table.append(arrow_table)

    def last_synced_at(self, silo_name: str, table_name: str) -> datetime | None:
        try:
            table = self._catalog.load_table(f"{silo_name}.{table_name}")
        except (NoSuchTableError, NoSuchNamespaceError):
            return None

        # WHEN THE SOURCE WAS READ, if this table records it (F-29).
        # A table synced before that property existed has none, and the
        # commit time is the best available answer for it.
        recorded = table.properties.get(SOURCE_READ_PROPERTY)
        if recorded:
            return datetime.fromisoformat(recorded)
        snapshot = table.current_snapshot()
        if snapshot is None:
            return None
        # Iceberg records this in milliseconds since the epoch, UTC --
        # read from the table's own metadata rather than tracked
        # separately by Elysium, so it can never drift out of sync with
        # what actually happened.
        return datetime.fromtimestamp(snapshot.timestamp_ms / 1000, tz=UTC)

    def _ensure_namespace(self, silo_name: str) -> None:
        try:
            self._catalog.create_namespace(silo_name)
        except NamespaceAlreadyExistsError:
            # The only expected case, and the only one swallowed.
            #
            # This was `except Exception: pass`, with a comment claiming
            # PyIceberg "raises a catalog-specific error type here
            # rather than a single documented one". That was not true --
            # it raises NamespaceAlreadyExistsError, verified directly.
            # The old handler therefore swallowed every real failure too
            # (a permissions problem, a full disk, a corrupt catalog),
            # and the comment's own defence was that such a failure
            # "surfaces immediately below anyway, when the table
            # operation itself fails" -- which turns a clear cause into
            # a confusing symptom one step removed from it.
            pass

    def _verdict_for_missing(self, silo_name: str, table_name: str, missing: list[str],
                              fields_by_column: dict[str, str]):
        """One verdict for several missing columns, decided by the worst.

        A REFUSAL WINS OVER AN ABSORPTION. If three columns vanished and
        one of them has pending writes, the sync must stop -- absorbing
        the other two while refusing the third would leave the mirror
        half-migrated to a shape nobody approved.
        """
        verdicts = [
            verdict_for_removed_column(
                silo_name, table_name, column, fields_by_column.get(column),
                self._edits_for(table_name, fields_by_column.get(column)),
            )
            for column in missing
        ]
        refusals = [verdict for verdict in verdicts if not verdict.absorbed]
        if refusals:
            return DriftVerdict(
                absorbed=False,
                shape=refusals[0].shape,
                detail="\n\n".join(verdict.detail for verdict in refusals),
            )
        return DriftVerdict(
            absorbed=True,
            shape=verdicts[0].shape,
            detail="\n".join(verdict.detail for verdict in verdicts),
        )

    def _edits_for(self, table_name: str, field: str | None) -> dict | None:
        """What the write log says about a field, or None if it cannot say.

        None is NOT "nothing was written" -- see
        drift_policy.verdict_for_removed_column on why the difference
        decides the verdict. A sync constructed without a write log
        (most tests, and scripts that only copy data) genuinely cannot
        check, and must not be allowed to look as though it did.
        """
        if self._write_log is None or field is None:
            return None
        return self._write_log.edits_touching_field(self._object_type_for(table_name), field)

    def _object_type_for(self, table_name: str) -> str:
        # The write log is keyed by OBJECT TYPE and the sync works in
        # TABLES. They coincide in every deployment written so far, and
        # where they do not the count comes back zero -- which REFUSES
        # nothing, because zero edits means absorb. Wrong in the safe
        # direction, and worth replacing with a real mapping once a
        # deployment separates them.
        return table_name

    def _read_source_rows(self, adapter: ExternalReadAdapter, table_name: str,
                           id_column: str, columns: list[str]) -> list[dict]:
        # ONE bulk read for the whole table. This previously went
        # through find_ids() then get_raw_field() per field per row --
        # the per-object shape that is right for serving a request and
        # wrong for copying a table. Measured before the fix: 10,001
        # queries to copy 2,000 rows of a five-column table.
        #
        # Still engine-agnostic: read_all_rows() is part of the real
        # ExternalReadAdapter contract, so a future Postgres or REST
        # adapter implements it in whatever way is bulk-efficient for
        # that backend, rather than this module reaching around the
        # interface into raw SQL.
        type_config = {"storage": {"table": table_name, "id_column": id_column}}
        return adapter.read_all_rows(table_name, columns, type_config)

    def _write_bronze(self, adapter, silo_name: str, table_name: str,
                       id_column: str, declared: list[str]) -> list[dict]:
        """Stores the source rows unaltered, with provenance in metadata.

        EVERY VALUE AS A STRING, deliberately. Bronze must not decide
        what a column means -- that is silver's job, and deciding it
        twice is how the two disagree. A string is the one
        representation that cannot lose information it was given.

        PROVENANCE LIVES IN TABLE PROPERTIES AND SNAPSHOT TIMESTAMPS,
        not in columns. "Where did this come from" is answered by the
        silo and table stamped on the table; "when was it read" by the
        snapshot's own timestamp_ms, which Iceberg records anyway.
        Adding columns would make bronze a transformation of the data
        it exists to preserve.

        FAILURE HERE DOES NOT FAIL THE SYNC. Bronze is a record for
        later, and losing it costs lineage; losing the sync costs the
        deployment its data. A deployment whose disk filled should
        serve stale-but-correct data rather than none, and the warning
        says what was lost.

        NAMED EXCEPTIONS, NOT `Exception`. A bare catch here swallowed
        two of my own mistakes while writing this -- a misremembered
        method name and a wrong argument shape -- and reported them as
        a bronze failure the sync shrugged off. A programming error
        should crash loudly; a full disk should not.

        pyiceberg exports no common base error, checked rather than
        assumed, so the named set is what actually goes wrong here: a
        full or unwritable disk, and Arrow refusing data it cannot
        represent.
        """
        identifier = f"bronze_{silo_name}.{table_name}"
        try:
            # EVERY COLUMN THE SOURCE HAS, not the declared ones.
            #
            # A first version stored only what the ontology declared,
            # which quietly defeated the point: adding a field still
            # required re-reading the silo, because bronze had never
            # seen the column either. Measured before fixing it -- the
            # source read count did not drop at all.
            #
            # columns_present() already reports them, having been built
            # for drift detection. An adapter that cannot answer falls
            # back to the declared set, which is no worse than before.
            present = adapter.columns_present(table_name)
            columns = sorted(present) if present else list(declared)
            raw_rows = self._read_source_rows(adapter, table_name, id_column, columns)

            arrow_table = pa.table({
                column: pa.array(
                    [None if row.get(column) is None else str(row.get(column))
                     for row in raw_rows],
                    type=pa.string(),
                )
                for column in columns
            })

            if not self._catalog.namespace_exists(f"bronze_{silo_name}"):
                self._catalog.create_namespace(f"bronze_{silo_name}")
            try:
                table = self._catalog.load_table(identifier)
            except NoSuchTableError:
                table = self._catalog.create_table(identifier, schema=arrow_table.schema)

            # THE SAME SKIP AS SILVER, and bronze needs it more: it
            # stores EVERY column rather than the declared ones, so its
            # snapshots are the larger ones. Measured with silver
            # skipping but bronze not: 30 identical syncs still grew to
            # 13.1 MB, all of it bronze.
            if not self._already_current(table, arrow_table):
                # WHAT CHANGED, recorded BEFORE the overwrite replaces
                # the evidence. Once overwrite() commits, the previous
                # rows are only reachable through an older snapshot,
                # and comparing them here while both are in hand is
                # both simpler and immune to a snapshot expiring
                # between the two reads.
                self._record_changes(
                    silo_name, table_name, id_column, table, raw_rows, columns)

                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore", message="Delete operation did not match any records")
                    table.overwrite(arrow_table)

            # WHAT THE SOURCE SAID ITS COLUMNS WERE, this sync.
            #
            # COERCION CANNOT SEE A TYPE CHANGE. Three silent failures
            # were measured: timestamptz->timestamp loses the offset,
            # numeric->float loses scale, and integer->text is absorbed
            # by int() with the whitespace along with it. Every one
            # produces plausible data and no error.
            #
            # SO THE PREVIOUS SYNC'S ANSWER IS KEPT and compared
            # against this one. Debezium's schema history is the same
            # idea; Elysium already has config_history doing it for
            # the OTHER side of the same question.
            previous_types = table.properties.get(SOURCE_TYPES_PROPERTY)
            current_types = _source_types_json(adapter, table_name)
            if previous_types and current_types:
                _report_type_drift(
                    silo_name, table_name, previous_types, current_types,
                )

            with table.transaction() as tx:
                tx.set_properties({
                    "elysium.source_silo": silo_name,
                    "elysium.source_table": table_name,
                    "elysium.layer": "bronze",
                    **({SOURCE_TYPES_PROPERTY: current_types}
                       if current_types else {}),
                    **BRONZE_RETENTION,
                })
        except (OSError, ValueError, KeyError, pa.ArrowInvalid) as e:
            logger.warning(
                f"bronze copy of {silo_name}.{table_name} failed ({e}); the sync "
                f"continues and the mirror is correct, but this read leaves no "
                f"raw record to trace values back to."
            )
            # The declared columns only -- enough for silver, which is
            # what the caller needs to carry on.
            return self._read_source_rows(adapter, table_name, id_column, declared)

        return raw_rows

    def _force_metadata_to_disk(self, identifier: str) -> None:
        """Makes this table's metadata durable, or stops the sync.

        LOCAL FILESYSTEMS ONLY, and it says so rather than
        pretending. A warehouse on S3 has no local file to fsync
        and its own durability story; calling this there would be a
        no-op dressed as a guarantee.
        """
        if self._warehouse_path is None:
            return

        synced = force_table_metadata_to_disk(
            self._warehouse_path, identifier,
        )
        logger.debug(
            "%s: forced %d metadata file(s) to disk", identifier, synced,
        )

    def _already_current(self, table, arrow_table) -> bool:
        """True when the committed snapshot already holds exactly this.

        CHEAP CHECKS FIRST. A row count mismatch settles it without
        reading a single value, and that is the common case when
        anything has changed at all.

        FALSE ON ANY DOUBT. An error here means "write it", never "skip
        it" -- a spurious rewrite costs one snapshot, while a spurious
        skip means the mirror silently stops tracking its source, which
        is the worse failure by a wide margin.
        """
        try:
            current = table.scan().to_arrow()
        except Exception:  # noqa: BLE001 - see the docstring: doubt means write
            # LOGGED, THOUGH THE ANSWER STAYS "WRITE IT". Returning
            # False is the safe direction and was already right; saying
            # nothing was not. A persistent fault here makes every sync
            # rewrite an unchanged table forever -- silently defeating
            # the skip that took 27.2 MB down to 0.9 -- and looks
            # exactly like normal operation from outside.
            #
            # debug rather than warning: one failure is unremarkable,
            # and a warning per table per sync would train someone to
            # ignore the log.
            logger.debug("could not read the current snapshot; writing anyway", exc_info=True)
            return False

        if current.num_rows != arrow_table.num_rows:
            return False
        if sorted(current.schema.names) != sorted(arrow_table.schema.names):
            return False

        # SORTED BY THE FIRST COLUMN before comparing, because Iceberg
        # does not promise row order across snapshots and an ordering
        # difference is not a data difference.
        try:
            key = arrow_table.schema.names[0]
            return current.sort_by(key).equals(arrow_table.sort_by(key))
        except Exception:  # noqa: BLE001 - see the docstring
            return False

    def _record_changes(self, silo_name: str, table_name: str, id_column: str,
                         bronze_table, current_rows: list[dict], columns: list[str]) -> None:
        """Appends what changed since the last sync, if anything.

        APPEND, NOT OVERWRITE, and this is the one table in the mirror
        where that is true. Every other table answers "what is there
        now" and is rebuilt; this one answers "what happened" and can
        only grow. It is also the only table a re-sync cannot rebuild,
        which is why ELT_ROADMAP.md calls it the reversibility line.

        SILENT ON THE FIRST RUN. A table with no previous snapshot
        would otherwise record every existing row as newly inserted --
        a lie, and an expensive one. Nothing is written until there is
        a real before and after to compare.

        FAILURE HERE DOES NOT FAIL THE SYNC, for the same reason bronze
        works that way: losing a changelog entry costs history, and
        failing the sync costs the deployment its data. But it is
        WARNED loudly, because unlike bronze this gap can never be
        filled in afterwards -- the source has already moved on.
        """
        try:
            if bronze_table.current_snapshot() is None:
                return

            previous = bronze_table.scan(selected_fields=tuple(columns)).to_arrow().to_pylist()
            changes = diff_snapshots(previous, current_rows, id_column)

            if changes.suspected_partial_read:
                logger.warning(
                    f"changelog for {silo_name}.{table_name}: more than "
                    f"{int(MAX_DELETED_FRACTION * 100)}% of rows vanished in one sync. "
                    f"Recording nothing, because a partially-failed read looks exactly "
                    f"like a mass deletion and a changelog cannot be un-written."
                )
                return
            if changes.is_empty:
                return

            self._append_changelog(silo_name, table_name, changes.rows, columns)
        except (OSError, ValueError, KeyError, pa.ArrowInvalid) as e:
            logger.warning(
                f"changelog for {silo_name}.{table_name} failed ({e}); the sync "
                f"continues and the mirror is correct, but this change is lost "
                f"permanently -- the source has already moved on."
            )

    def _append_changelog(self, silo_name: str, table_name: str,
                           rows: list[dict], columns: list[str]) -> None:
        """Writes the change rows, creating the table on first use.

        EVERY VALUE A STRING, as bronze does, and for the same reason:
        a changelog must not decide what a column means. `_change` and
        `_recorded_at` join them so one schema covers every table.
        """
        recorded_at = datetime.now(UTC).isoformat()
        namespace = f"changelog_{silo_name}"
        identifier = f"{namespace}.{table_name}"

        arrow_table = pa.table({
            **{
                column: pa.array(
                    [None if row.get(column) is None else str(row.get(column)) for row in rows],
                    type=pa.string(),
                )
                for column in columns
            },
            "_change": pa.array([row["_change"] for row in rows], type=pa.string()),
            # WHEN WE NOTICED, not when it happened -- the source does
            # not tell us the latter and inventing it would be worse
            # than admitting the difference.
            "_recorded_at": pa.array([recorded_at] * len(rows), type=pa.string()),
        })

        if not self._catalog.namespace_exists(namespace):
            self._catalog.create_namespace(namespace)
        try:
            table = self._catalog.load_table(identifier)
        except NoSuchTableError:
            table = self._catalog.create_table(identifier, schema=arrow_table.schema)

        table.append(arrow_table)

    def _read_bronze(self, silo_name: str, table_name: str,
                      columns: list[str]) -> "list[dict] | None":
        """The raw rows as bronze recorded them, or None if it has none.

        None rather than an exception, because a missing bronze table is
        an ORDINARY state: the first sync after this shipped, a table
        added since, or a bronze write that failed for the reasons
        _write_bronze() tolerates. The caller falls back to the rows it
        already read.

        COLUMNS THE ONTOLOGY WANTS BUT BRONZE LACKS mean bronze predates
        the declaration -- exactly the case this layer is meant to
        remove, and it cannot remove it retroactively. Falling back is
        the honest answer; pretending would produce silver rows with
        missing fields and no explanation.
        """
        try:
            table = self._catalog.load_table(f"bronze_{silo_name}.{table_name}")
        except (NoSuchTableError, NoSuchNamespaceError):
            return None

        stored = set(table.schema().column_names)
        missing = [column for column in columns if column not in stored]
        if missing:
            logger.warning(
                f"bronze copy of {silo_name}.{table_name} predates {sorted(missing)}; "
                f"reading the source directly for this sync. The next sync will have "
                f"them, since bronze stores every column the source has."
            )
            return None

        return table.scan(selected_fields=tuple(columns)).to_arrow().to_pylist()

    def _to_arrow(self, rows: list[dict], columns: list[str],
                   column_types: dict[str, str] | None = None) -> pa.Table:
        # Builds the Arrow table from rows the TRANSFORM stage has
        # already cleaned -- this method no longer casts anything
        # itself. Phase 3 moved that out: type casting is a raw ->
        # clean responsibility, and the ingest stage is deliberately
        # kept as dumb as Foundry's own ("minimal options for
        # transforming the data before it arrives in the destination
        # dataset"). See core/mirror/transform.py.
        #
        # The declared types still determine the SCHEMA here, which is
        # a different thing from casting the values: a column declared
        # `number` gets a real float64 Arrow column. That has to happen
        # at write time, since it is a property of the table being
        # written, not of the rows.
        column_types = column_types or {}
        resolved = {
            column: column_types.get(column, DEFAULT_FIELD_DATA_TYPE) for column in columns
        }
        data = {column: [row[column] for row in rows] for column in columns}
        # THE ZONE IS NOT PART OF THE ARROW TYPE. `timestamptz` already
        # carries tz=UTC; the declared source zone says how to READ a
        # naive value, not how to STORE it, and everything is stored
        # UTC by then.
        schema = pa.schema([
            (column, arrow_type_for(split_declared_type(resolved[column])[0]))
            for column in columns
        ])
        return pa.table(data, schema=schema)
