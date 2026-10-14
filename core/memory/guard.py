"""
guard.py  (the memory security gate)

MemoryGuard is the ONLY way memories are written, read or forgotten
(E-14, built 14 Oct to the owner's design -- see core/memory/store.py).
It decides every question about WHO, through the same RBAC and MAC
the mediator's reads use, re-derived live on every call. Nothing about authority is stored with a memory: a
grant withdrawn after a memory was written hides it the next time
anyone asks.

WHO MAY SEE A MEMORY: whoever may read its object AND every field it was
written from. The sentence may say something derived from any of them --
"disputed the March charges" read off a field the next reader may not
see -- so the narrowest reader of its sources is the widest it may go.

WHAT IS STALE: a memory whose source fields no longer hold the values
they held when it was written. Shown as stale where people look; never
given to the agent, which would otherwise repeat yesterday's fact as
today's.

WHO MAY FORGET ONE: its author, or anyone who may change the object
(`write:<Type>`), provided they may see it.
"""

from core.filters import FieldFilter
from core.intermediate_layer.auth import UserRecord, authorize
from core.memory.store import Memory, MemoryStore, fingerprint
from core.ontology.mediator import DataMediator


class MemoryGuard:
    def __init__(self, store: MemoryStore, mediator: DataMediator, roles: dict):
        self.store = store
        self.mediator = mediator
        self.roles = roles

    def _may_read_object(self, user: UserRecord, object_type: str, object_id) -> bool:
        """Whether the object EXISTS and this user may read it, as one
        answer -- the same question api/routes' notes ask, the same way.

        COUNTED, NOT CHECKED. check_access answers "may this user read
        this id" and is True for an id that names nothing on a type with
        no security field, so a memory could be pinned to an object that
        does not exist. count_objects applies the same RBAC and MAC the
        read path does, and a zero means absent OR denied -- uniformly.
        """
        type_config = (self.mediator.schema or {}).get(object_type)
        if type_config is None:
            return False
        try:
            return self.mediator.count_objects(
                user, object_type,
                [FieldFilter(field=type_config.get("id_field", "id"), operator="equals",
                             value=object_id)]) > 0
        except Exception:
            # An id of the wrong shape for its field: the same answer as
            # absent, as it is for notes.
            return False

    def _readable_fields(self, user: UserRecord, object_type: str) -> list[str]:
        fields = (self.mediator.schema.get(object_type) or {}).get("fields") or {}
        return sorted(name for name, config in fields.items()
                      if (config or {}).get("type", "data") == "data"
                      and authorize(user, self.roles, f"read:{object_type}.{name}"))

    def remember(self, user: UserRecord, object_type: str, object_id, text: str) -> "Memory | None":
        """A person asks for something to be remembered about an object.
        None when they may not read it -- uniform with every other read."""
        if not self._may_read_object(user, object_type, object_id):
            return None
        fields = self._readable_fields(user, object_type)
        values = self.mediator.get_object(user, object_type, object_id, fields) if fields else {}
        sources = {name: fingerprint(values.get(name)) for name in fields}
        return self.store.add(object_type, object_id, text, sources, user.user_id)

    def visible(self, user: UserRecord, object_type: str, object_id) -> list[tuple[Memory, bool]]:
        """(memory, stale) for every memory about the object this user may
        see, oldest first."""
        if not self._may_read_object(user, object_type, object_id):
            return []
        memories = self.store.about(object_type, object_id)
        if not memories:
            return []
        readable = set(self._readable_fields(user, object_type))
        seen = [memory for memory in memories if set(memory.sources) <= readable]
        wanted = sorted({name for memory in seen for name in memory.sources})
        current = self.mediator.get_object(user, object_type, object_id, wanted) if wanted else {}
        return [(memory, any(fingerprint(current.get(name)) != print_
                             for name, print_ in memory.sources.items()))
                for memory in seen]

    def fresh(self, user: UserRecord, object_type: str, object_id) -> list[Memory]:
        """What the agent may be given: visible and not stale."""
        return [memory for memory, stale in self.visible(user, object_type, object_id) if not stale]

    def forget(self, user: UserRecord, memory_id: str) -> bool:
        memory = self.store.get(memory_id)
        if memory is None:
            return False
        if not any(m.memory_id == memory_id
                   for m, _ in self.visible(user, memory.object_type, memory.object_id)):
            return False
        if not self.may_forget(user, memory):
            return False
        self.store.remove(memory_id)
        return True

    def may_forget(self, user: UserRecord, memory: Memory) -> bool:
        """Its author, or anyone who may change the object. Says nothing
        about whether they may SEE it -- forget() asks that first, and a
        caller listing memories has only been given visible ones."""
        return memory.author == user.user_id or authorize(
            user, self.roles, f"write:{memory.object_type}")
