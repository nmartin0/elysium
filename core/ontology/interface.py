"""
interface.py  (the data-silo contract -- generic, zero implementation knowledge)

DataSiloAdapter is what EVERY concrete adapter (adapters/sqlite_adapter.py,
and any future one) must implement. Three methods, all purely mechanical
fetch -- NO security logic, NO policy judgment. That's deliberate: an
adapter cannot leak data past a security check because core/ never asks
it for anything until the check has already passed. See
core/ontology/mediator.py's DataMediator for where the actual security
decisions live.

type_config / field_config are passed through OPAQUE to core/ -- each
adapter reads whichever keys it needs from them (SQLite reads table/
id_column; a future REST adapter might instead read an endpoint key from
the same dict). core/ never inspects these values, only forwards them.
"""

from typing import Any, Protocol


class DataSiloAdapter(Protocol):
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

    def write_field(self, object_type: str, object_id: Any, field_name: str,
                     value: Any, type_config: dict) -> None:
        """Mechanical write. No permission check -- only ever called by
        WriteMediator after both its checks (row-level + action-level)
        have already passed."""
        ...

    def create_object(self, object_type: str, fields: dict, type_config: dict) -> Any:
        """Creates a new object, returns its new ID. Same trust model as
        write_field."""
        ...
