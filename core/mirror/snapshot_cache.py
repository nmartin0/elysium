"""Mirrored tables held in memory, by the snapshot they were read at (E-10).

WHY: every mirror read loaded the table from the catalog (0.75 ms),
planned a scan over its manifests (1.73 ms) and read its data (about
2 ms) -- measured, per scan -- and an operation makes several. The mirror
read path was 8-11x slower than live: search_object 11.61 ms against
1.04, get_field 4.87 against 0.63.

WHY BY SNAPSHOT: an Iceberg snapshot never changes once written. A table
cached by (table, snapshot id) can never be stale; a sync writes a new
snapshot, and so a new key. Nothing is ever invalidated.

BOUNDED: by bytes, least recently used first out; an entry larger than
the whole budget is refused rather than evicting everything for it.
"""

import threading
from collections import OrderedDict
from typing import Any

# Per mirror adapter -- one per silo, per generation.
DEFAULT_MAX_BYTES = 256 * 1024 * 1024


class SnapshotCache:
    def __init__(self, max_bytes: int = DEFAULT_MAX_BYTES):
        self._max_bytes = max_bytes
        self._entries: OrderedDict[Any, tuple[Any, int]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return entry[0]

    def put(self, key: Any, value: Any, size: int) -> bool:
        """Whether it was kept. False for one larger than the budget."""
        if size > self._max_bytes:
            return False
        with self._lock:
            if key in self._entries:
                return True
            while self._entries and self._bytes + size > self._max_bytes:
                _, (_, evicted) = self._entries.popitem(last=False)
                self._bytes -= evicted
            self._entries[key] = (value, size)
            self._bytes += size
            return True
