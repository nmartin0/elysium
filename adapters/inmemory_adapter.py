"""
inmemory_adapter.py  (the simplest MemoryStore backend -- a plain dict)

Implements core/memory/interface.py's MemoryStore contract. Not
shared/persistent across processes or restarts -- fine for a single
long-running process (e.g. one deployment run), not a real multi-user
production backend. A future Redis-backed adapter would implement the
exact same two-method contract.
"""

from core.memory.interface import MemoryEntry


class InMemoryAdapter:
    def __init__(self):
        self._data: dict[str, MemoryEntry] = {}

    def put(self, key: str, entry: MemoryEntry) -> None:
        self._data[key] = entry

    def get(self, key: str) -> MemoryEntry | None:
        return self._data.get(key)
