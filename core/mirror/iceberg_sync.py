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

import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.exceptions import NoSuchNamespaceError, NoSuchTableError

from core.mirror.interface import MirrorSync, SyncResult
from core.ontology.interface import ExternalReadAdapter


class IcebergMirrorSync(MirrorSync):
    def __init__(self, mirror_dir: Path, adapters: dict[str, ExternalReadAdapter]):
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
        mirror_dir.mkdir(parents=True, exist_ok=True)
        (mirror_dir / "warehouse").mkdir(exist_ok=True)
        self._catalog = SqlCatalog(
            "elysium_mirror",
            uri=f"sqlite:///{mirror_dir / 'catalog.db'}",
            warehouse=f"file://{mirror_dir / 'warehouse'}",
        )

    def sync_table(self, silo_name: str, table_name: str, id_column: str,
                    columns: list[str]) -> SyncResult:
        adapter = self.adapters.get(silo_name)
        if adapter is None:
            raise ValueError(
                f"No adapter for silo {silo_name!r} -- "
                f"known silos: {sorted(self.adapters.keys())}"
            )

        rows = self._read_source_rows(adapter, table_name, id_column, columns)
        arrow_table = self._to_arrow(rows, columns)

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
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Delete operation did not match any records")
            table.overwrite(arrow_table)

        return SyncResult(
            silo_name=silo_name,
            table_name=table_name,
            row_count=arrow_table.num_rows,
            synced_at=datetime.now(UTC),
        )

    def last_synced_at(self, silo_name: str, table_name: str) -> datetime | None:
        try:
            table = self._catalog.load_table(f"{silo_name}.{table_name}")
        except (NoSuchTableError, NoSuchNamespaceError):
            return None

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
        except Exception:
            # Already exists -- the only expected case. PyIceberg raises
            # a catalog-specific error type here rather than a single
            # documented one, so this stays broad deliberately; a real,
            # different failure surfaces immediately below anyway, when
            # the table operation itself fails.
            pass

    def _read_source_rows(self, adapter: ExternalReadAdapter, table_name: str,
                           id_column: str, columns: list[str]) -> list[dict]:
        # Reads through the adapter's own public, read-only interface --
        # find_ids() for the real id list, then get_raw_field() per
        # column. Deliberately NOT a raw "SELECT * FROM table" through
        # the adapter's private connection: going through the real
        # interface keeps this sync engine-agnostic (a future Postgres
        # or REST adapter works here unchanged), which is the entire
        # reason ExternalReadAdapter exists.
        #
        # A real, honest cost of that choice, named rather than hidden:
        # this is one query per field per row, not one bulk scan. Fine
        # at this project's current scale and for a job that runs on a
        # schedule rather than per request -- but the first thing to
        # revisit if sync duration ever becomes a real problem, most
        # likely by adding a real bulk-read method to
        # ExternalReadAdapter itself rather than by reaching around it
        # here.
        type_config = {"storage": {"table": table_name, "id_column": id_column}}
        ids = adapter.find_ids(table_name, {}, type_config)

        rows = []
        for object_id in ids:
            row: dict[str, Any] = {}
            for column in columns:
                row[column] = adapter.get_raw_field(table_name, object_id, column, type_config)
            rows.append(row)
        return rows

    def _to_arrow(self, rows: list[dict], columns: list[str]) -> pa.Table:
        # An explicitly string-typed schema for every column, built from
        # the ontology's own column list rather than inferred from the
        # data. A real, deliberate simplification for this first
        # version, stated plainly rather than left as a silent
        # assumption: inferring types per-sync would let a table's own
        # mirror schema CHANGE between runs purely because its data
        # changed (e.g. a nullable numeric column that happens to be all
        # NULL one day), which is exactly the silent, drifting behavior
        # this project's "fail loudly, never silently substitute"
        # discipline rejects. Real type fidelity belongs with the
        # ontology-driven schema work the roadmap already plans, not
        # guessed at here.
        data = {
            column: [None if row[column] is None else str(row[column]) for row in rows]
            for column in columns
        }
        schema = pa.schema([(column, pa.string()) for column in columns])
        return pa.table(data, schema=schema)
