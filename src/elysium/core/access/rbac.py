"""
rbac.py  (the low-level role-grant check -- generic mechanism, no org data)

authorize() is RBAC -- role-based, not per-user. A user with no role,
or a role not present in `roles`, is denied by default. RBAC and MAC
are DELIBERATELY separate checks, never merged into one function here
-- core/access/access_control.py's check_access() is the
one place that combines both for an object that exists.

This is the LOW-LEVEL half of the one authorization decision point
(invariant I2). It is its own module so that an import-linter contract
(pyproject.toml, "authorization has one decision point") can name who
may import it. The modules that still do are listed there, each with
the reason; nothing new should be added to that list.
"""

from elysium.core.access.auth import UserRecord

DISCOVER_PREFIX = "discover:"
READ_PREFIX = "read:"


def authorize(user_record: UserRecord, roles: dict, action_id: str) -> bool:
    if user_record.role_name is None:
        return False
    role = roles.get(user_record.role_name)
    if role is None:
        return False
    granted = role.get("allowed_actions", frozenset())
    if action_id in granted:
        return True

    # READ IMPLIES DISCOVER, and that implication is what makes the
    # ladder a ladder rather than three independent bits.
    #
    # Grants were independent strings, so `read:Customer.email` could
    # be held WITHOUT `read:Customer` -- a role authorised to read a
    # field of a type it cannot discover. Nonsense that nothing
    # prevented, and the reason an rwx-style model is the wrong shape
    # here: rwx bits are INDEPENDENT by design, and `-w-` is a drop box
    # for a file but incoherent for a field.
    #
    # What we want is monotonic: discover <= read. Someone permitted
    # the value is necessarily permitted to know the field exists, so
    # asking for discover when read is held must answer yes -- and a
    # deployment never writes both.
    #
    # ONE DIRECTION ONLY. `discover:` does NOT imply `read:`; that is
    # the entire point of having the state.
    if action_id.startswith(DISCOVER_PREFIX):
        return READ_PREFIX + action_id[len(DISCOVER_PREFIX):] in granted

    return False
