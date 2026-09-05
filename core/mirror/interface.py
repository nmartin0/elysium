"""
interface.py  (the mirror-sync contract -- generic, zero storage-format
knowledge)

MirrorSync is what every concrete sync implementation (core/mirror/
iceberg_sync.py today, any future one) must extend. Phase 2 of the
read-only mirror architecture -- see ROADMAP.md's own "Read-only data
mirror architecture" section for the full design, and core/ontology/
interface.py for the same interface-then-implementation convention
this file deliberately mirrors.

WHAT A SYNC ACTUALLY IS, stated plainly because the name alone
undersells it: one run copies the customer's own external business
data into Elysium's OWN local storage. For each silo declared in
data_silos.yaml, for each real table the ontology actually
references, it reads every row (through the Phase 1 read-only
connection -- see adapters/sqlite_adapter.py's own SQLiteReadAdapter)
and writes it into a corresponding local table as one atomic
snapshot. That is the whole job. It is a batch copy, not a streaming
or incremental mechanism, and deliberately so at this stage.

RUNS AS A SEPARATE PROCESS, never a background thread inside the web
app -- a real, settled decision (see ROADMAP.md's own Phase 2 entry
for the full reasoning and its honest cost). scripts/run_sync.py is
the real entry point; scheduling is external (cron, systemd timer).
Nothing in this package starts a thread, owns a timer, or knows what
time it is beyond recording when a sync finished.

DELIBERATELY NOT AN ADAPTER, despite the surface resemblance to
core/ontology/interface.py's own ExternalReadAdapter: a sync is not a
per-request data-access path with its own read/write split. It is a
whole-job orchestrator that USES those adapters (a real
ExternalReadAdapter to read the source) and writes to its own local
storage. Giving it a Reader/Writer split of its own would be
importing a distinction it doesn't have -- there is exactly one
direction of flow here, always.

Used by: scripts/run_sync.py (the real, only entry point)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SyncResult:
    """What one real sync run actually did -- returned rather than
    logged-and-discarded so a caller (scripts/run_sync.py, and any real
    test) can assert on genuine outcomes, not scrape log output."""

    silo_name: str
    table_name: str
    row_count: int
    synced_at: datetime


class MirrorSync(ABC):
    @abstractmethod
    def sync_table(self, silo_name: str, table_name: str, id_column: str,
                    columns: list[str]) -> SyncResult:
        """Copies ONE source table into the local mirror, as one atomic
        snapshot, replacing whatever that table's previous contents
        were -- a full refresh, never an append onto stale rows.

        columns is the real, explicit list of columns to copy, resolved
        from the ontology by the caller -- never `SELECT *`. Deliberate:
        the mirror should hold exactly what the ontology actually
        references, not whatever else happens to live in the customer's
        own table (which could include columns Elysium has no business
        copying at all).
        """

    @abstractmethod
    def last_synced_at(self, silo_name: str, table_name: str) -> datetime | None:
        """When this table was last successfully synced, or None if it
        never has been. The real mechanism behind the user-visible data
        freshness the roadmap calls for -- see ROADMAP.md's own "Real,
        visible data freshness" point."""
