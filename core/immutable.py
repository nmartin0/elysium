"""
immutable.py  (deep-freezing configuration so it cannot be mutated)

WHY THIS EXISTS. DeploymentConfig holds dicts -- schema, users, roles,
silo_configs, action_types. `frozen=True` on the dataclass stops a
FIELD being rebound; it does nothing about mutating what is inside one.
So this is legal today and nothing notices:

    config.roles["analyst"]["allowed_actions"].add("execute:Transfer")
    config.schema["Account"]["storage"]["table"] = "somewhere_else"

The first invents a grant no policy.yaml contains, no reload produced
and no audit entry records. The second redirects writes to a table the
ontology does not describe, while the write log records the intended
one -- a confirmed write landing somewhere else, with nothing left
pending for recovery to notice.

Neither happens in production code today; verified by grep before this
was written. The point is that nothing PREVENTS them, and once a
configuration is shared across concurrent requests (see
HOT_RELOAD_PLAN.md), a mutation by one request is visible to every
other, mid-flight, with no error and no record.

ENFORCED RATHER THAN CONVENTIONAL, following what this project already
does everywhere else: import-linter enforces layering on every
./lint.sh rather than a document asking nicely, and
require_assertions_enabled() refuses to start rather than trusting an
inspection -- its own history records that the inspection HAD been
wrong once. PRINCIPLES.md section 10 states the rule directly:
"explicit layers, enforced, not aspirational".

It is also finishing a job already half done. _freeze_roles() in
deployment_loader.py already converts every role's allowed_actions to
a frozenset at load -- in the single most security-sensitive field the
config has. That was done for O(1) lookups on the authorize hot path
and immutability came free; this extends the same treatment to the
rest.

WHAT IT DOES NOT DO, stated so the guarantee is not overread.
MappingProxyType is a VIEW, not a copy: the underlying dict stays
mutable, and anyone still holding a reference to the ORIGINAL can
still change it, which the proxy will then reflect. That is acceptable
here because freezing happens at the end of load_deployment(), and the
raw dicts it wraps are local to that call -- nothing outside holds a
reference. It would NOT be acceptable if a caller passed its own dict
in and kept using it.
"""

from types import MappingProxyType
from typing import Any


def deep_freeze(value: Any) -> Any:
    """Returns value with every nested container made immutable.

    dict  -> MappingProxyType (mutation raises TypeError)
    list  -> tuple
    set   -> frozenset

    Everything else is returned unchanged: strings, numbers, booleans,
    None and frozensets are already immutable, and a value this does
    not recognise is left alone rather than guessed at.

    RECURSIVE, because the hazards are nested. The two examples in this
    module's docstring are three and four levels deep respectively --
    freezing only the top level would stop neither.
    """
    if isinstance(value, MappingProxyType):
        return value
    if isinstance(value, dict):
        return MappingProxyType({key: deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(deep_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(deep_freeze(item) for item in value)
    return value
