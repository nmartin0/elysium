"""
guard.py  (the memory security gate -- generic, org-agnostic)

MemoryGuard.get() is the ONLY sanctioned way to read anything back out
of a MemoryStore. It NEVER trusts MemoryEntry.captured_security_value --
that field is a snapshot from whenever the entry was written, and a
snapshot being trusted at read time is exactly the vulnerability this
class exists to prevent: if the underlying object's security value
changed, or a user's role/access was revoked, AFTER something was
cached, trusting the stale label would let a since-revoked user (or a
different user who happens to share a cache) see it anyway.

Instead, every read goes through check_access() -- the SAME canonical
MAC+RBAC+audit enforcement point core/ontology/mediator.py's reads and
core/ontology/write_mediator.py's writes use -- re-deriving the CURRENT
truth from DataMediator, live, every time. Matches Palantir's own
documented principle: markings are enforced "at the point of inference,"
not baked in once and trusted forever after.

Used by: core/agent/agentic_loop.py (optional -- a deployment with no
         MemoryStore configured simply never calls this)
"""

from typing import Any

from core.intermediate_layer.access_control import check_access
from core.memory.interface import MemoryEntry, MemoryStore
from core.ontology.mediator import DataMediator


class MemoryGuard:
    def __init__(self, store: MemoryStore, mediator: DataMediator, users: dict, roles: dict, security_attribute: str):
        self.store = store
        self.mediator = mediator
        self.users = users
        self.roles = roles
        self.security_attribute = security_attribute

    def put(self, key: str, object_type: str, object_id: Any, value: Any, user_id: str) -> None:
        # captured_security_value is stored for audit/debugging
        # visibility only -- get() below never reads it back as a trust
        # decision, only re-derives the current truth live.
        security_value = self.mediator._get_security_value(object_type, object_id)
        entry = MemoryEntry(object_type, object_id, value, security_value or "")
        self.store.put(key, entry)

    def get(self, key: str, user_id: str) -> Any | None:
        entry = self.store.get(key)
        if entry is None:
            return None

        action = f"read:{entry.object_type}"
        allowed = check_access(
            self.mediator, self.users, self.roles, self.security_attribute,
            user_id, entry.object_type, entry.object_id, action,
        )
        if not allowed:
            return None

        return entry.value
