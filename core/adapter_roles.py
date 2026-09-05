"""
adapter_roles.py  (the three, shared, top-level marker classes every
real adapter in this project -- internal or external -- ultimately
descends from)

Deliberately its own, small, neutral module -- not defined inside
core/internal_storage.py or core/ontology/interface.py, even though
those are this file's only two real users today. Both
ExternalReadAdapter/ExternalWriteAdapter (core/ontology/interface.py,
the customer's own third-party data) and InternalReadAdapter/
InternalWriteAdapter (core/internal_storage.py, Elysium's own storage)
descend from the SAME three roots here -- putting them inside either
of those two files would have made the other one import from a module
named after a concern it isn't ("external adapters extending
internal_storage.ReadAdapter" reads backwards). See core/
internal_storage.py's own module docstring for the fuller reasoning
behind the three-way ReadAdapter/WriteAdapter/AppendOnlyAdapter split
itself (confirmed against real, established precedent -- CQRS, and
Python's own typeshed SupportsRead/SupportsWrite -- before choosing
this shape).
"""

from abc import ABC


class ReadAdapter(ABC):  # noqa: B024 -- deliberately no shared abstract
    # method; see core/internal_storage.py's own module docstring for
    # why a real, common method signature genuinely doesn't exist
    # across internal and external readers. A pure, real taxonomic
    # marker (isinstance checks, type annotations), not a contract
    # every subclass must fulfill.
    """Marker base -- a real, structural fact about a class: its only
    real capability is reading, never writing."""


class WriteAdapter(ABC):  # noqa: B024 -- see ReadAdapter's own noqa
    """Marker base -- the write-capable counterpart to ReadAdapter,
    including update and delete, not just insert."""


class AppendOnlyAdapter(ABC):  # noqa: B024 -- see ReadAdapter's own noqa
    """Marker base -- deliberately NOT a subtype of WriteAdapter. A
    genuinely narrower real capability: can only ever ADD a new entry,
    structurally never update or delete an existing one. See core/
    internal_storage.py's own module docstring for the real,
    established precedent (the append-only log / event-sourcing
    pattern) and the real, motivating example (AuditLog)."""
