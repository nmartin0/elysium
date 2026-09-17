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
behind the ReadAdapter/WriteAdapter split
itself (confirmed against real, established precedent -- CQRS, and
Python's own typeshed SupportsRead/SupportsWrite -- before choosing
this shape).
"""

from abc import ABC


class ReadAdapter(ABC):  # noqa: B024 -- see below
    # NO SHARED ABSTRACT METHOD, deliberately: see
    # core/internal_storage.py's module docstring for why a common
    # signature genuinely does not exist across internal and external
    # readers. This is a taxonomic marker -- isinstance checks and type
    # annotations -- not a contract every subclass must fulfil.
    #
    # BUT ABC IS LOAD-BEARING AND THE SUPPRESSION IS NOT COSMETIC, which
    # an audit nearly got wrong: ABC supplies the ABCMeta metaclass, and
    # ExternalReadAdapter below declares TWELVE @abstractmethods that are
    # only ENFORCED because of it. Verified directly -- a plain base
    # class leaves them unenforced and an incomplete subclass
    # instantiates silently.
    #
    # So "an ABC with no abstract methods does nothing" is false here.
    # It does nothing IN THIS FILE and everything one layer down.
    """Marker base -- a real, structural fact about a class: its only
    real capability is reading, never writing."""


class WriteAdapter(ABC):  # noqa: B024 -- see ReadAdapter's own noqa
    """Marker base -- the write-capable counterpart to ReadAdapter,
    including update and delete, not just insert."""
