"""
guard.py  (the memory security gate -- generic, org-agnostic)

MemoryGuard.get() is the ONLY sanctioned way to read anything back out
of a MemoryStore. It NEVER trusts MemoryEntry.captured_security_value --
that field is a snapshot from whenever the entry was written, and a
snapshot being trusted at read time is exactly the vulnerability this
class exists to prevent.

Instead, every read goes through check_access() -- the SAME canonical
MAC+RBAC+audit enforcement point core/ontology/mediator.py's reads and
core/ontology/write_mediator.py's writes use -- re-deriving the CURRENT
truth from DataMediator, live, every time, using a pre-resolved
UserRecord (see core/intermediate_layer/auth.py) rather than a raw
user_id re-looked-up here.

put() only takes a plain user_id string, not a full UserRecord -- it
doesn't perform any permission check of its own (it just stores
whatever it's given, with the OBJECT's own security value captured for
audit/debugging visibility only), so there's nothing here that actually
needs the resolved record.

Used by: core/agent/agentic_loop.py (optional -- a deployment with no
         MemoryStore configured simply never calls this)
"""

from typing import Any

from core.intermediate_layer.access_control import check_access
from core.intermediate_layer.auth import UserRecord
from core.memory.interface import MemoryEntry, MemoryStore
from core.ontology.mediator import DataMediator


class MemoryGuard:
    def __init__(self, store: MemoryStore, mediator: DataMediator, roles: dict):
        self.store = store
        self.mediator = mediator
        self.roles = roles

    def put(self, key: str, object_type: str, object_id: Any, value: Any, user_id: str) -> None:
        security_value = self.mediator._get_security_value(object_type, object_id)
        entry = MemoryEntry(object_type, object_id, value, security_value or "")
        self.store.put(key, entry)

    def get(self, key: str, user_record: UserRecord) -> Any | None:
        entry = self.store.get(key)
        if entry is None:
            return None

        action = f"read:{entry.object_type}"
        allowed = check_access(self.mediator, user_record, self.roles, entry.object_type, entry.object_id, action)
        if not allowed:
            return None

        return entry.value
