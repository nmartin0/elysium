"""
interface.py  (the data-silo contract -- generic, zero implementation knowledge)

DataSiloAdapter is what EVERY concrete adapter (adapters/sqlite_adapter.py,
and any future one) must implement. All fetch/write methods are purely
mechanical -- NO security logic, NO policy judgment. That's deliberate:
an adapter cannot leak data past a security check because core/ never
asks it for anything until the check has already passed. See
core/ontology/mediator.py's DataMediator for where the actual security
decisions live.

type_config / field_config are passed through OPAQUE to core/ -- each
adapter reads whichever keys it needs from them (SQLite reads table/
id_column; a future REST adapter might instead read an endpoint key from
the same dict). core/ never inspects these values, only forwards them.

CONCURRENCY DECLARATIONS -- every adapter declares three facts about
itself; core/ enforces based on what's declared, never assumes:
  max_concurrent_reads / max_concurrent_writes: int | None -- a real
    capacity limit for this specific backend, or None if the backend
    genuinely handles unlimited concurrent operations (the correct
    default for most real databases). SQLite declares
    max_concurrent_writes=1 specifically because SQLite's write lock is
    whole-FILE, coarser than the per-object correctness lock
    DataMediator already applies to every write regardless of this
    declaration -- most backends (Postgres, DynamoDB, etc.) don't have
    this extra constraint and should declare None here.
  supports_atomic_conditional_write: bool -- can write_fields() below
    genuinely guarantee atomicity via the backend itself (e.g. a SQL
    WHERE clause), or does it only get DataMediator's own per-object
    lock as protection (real, but weaker -- doesn't extend across
    separate OS processes the way a database-native guarantee does)?
    Declared honestly, not assumed uniform across all adapters.
"""

from typing import Any, Protocol


class DataSiloAdapter(Protocol):
    max_concurrent_reads: int | None
    max_concurrent_writes: int | None
    supports_atomic_conditional_write: bool

    def find_ids(self, object_type: str, criteria: dict, type_config: dict) -> list[Any]:
        """Matching IDs. NOT security-filtered -- DataMediator filters
        after calling this."""
        ...

    def get_raw_field(self, object_type: str, object_id: Any, field_name: str, type_config: dict) -> Any:
        """One field's raw value. No security check -- DataMediator only
        calls this after confirming access is already allowed."""
        ...

    def resolve_reverse_link(self, object_id: Any, field_config: dict, target_id_column: str) -> list[Any]:
        """IDs of objects referencing this one. target_id_column is
        pre-resolved by DataMediator (it requires cross-type schema
        knowledge the adapter must never need), not looked up here."""
        ...

    def write_fields(self, object_type: str, object_id: Any, changes: dict,
                      expected_current_values: dict, type_config: dict) -> bool:
        """Atomically writes ALL fields in `changes` in one operation --
        all-or-nothing, never partially applied. Returns False (writes
        NOTHING) if the object no longer matches expected_current_values
        -- the caller's signal that a lost-update race occurred, whether
        detected via a native atomic conditional write or (if
        supports_atomic_conditional_write is False) a plain read-then-
        write, relying on DataMediator's per-object lock for protection
        instead. No permission check -- only ever called by
        WriteMediator after both its checks (row-level + action-level)
        have already passed."""
        ...

    def create_object(self, object_type: str, fields: dict, type_config: dict) -> Any:
        """Creates a new object, returns its new ID. Same trust model as
        write_fields. No lost-update concern -- there's no existing
        object to conflict with yet."""
        ...
