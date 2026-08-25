"""
interface.py  (the memory-store contract -- generic, zero implementation knowledge)

MemoryStore is what EVERY concrete memory backend (adapters/inmemory_adapter.py,
and any future one -- Redis, etc.) must implement. Deliberately minimal:
put/get only, no query capability, no partial updates -- a memory store
is a dumb key-value cache, not a second ontology.

MemoryEntry.captured_security_value exists for AUDIT/DEBUGGING VISIBILITY
ONLY -- it is never the actual trust mechanism. core/memory/guard.py's
MemoryGuard always re-derives the CURRENT security value live via
DataMediator and re-checks the CURRENT role, on every read, rather than
trusting this stored snapshot. See MemoryGuard's docstring for the full
reasoning (this was a deliberate decision made in the design
conversation, not an oversight).
"""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class MemoryEntry:
    object_type: str
    object_id: Any
    value: Any
    captured_security_value: str   # audit/debugging ONLY -- see module docstring


class MemoryStore(Protocol):
    def put(self, key: str, entry: MemoryEntry) -> None: ...
    def get(self, key: str) -> MemoryEntry | None: ...
