"""Why something is deprecated, and what replaces it (28 October, owner-agreed).

A type, a field or a link type may carry `status: deprecated`. That said
nothing about WHY, or what to use instead, so nobody reading a schema could
tell a name to avoid from a name that is merely old. Foundry asks for the
same three things when a resource is deprecated -- a reason, a deadline,
and optionally a replacement ("object-link-types/metadata-statuses") --
and refuses to delete anything still active.

    status: deprecated
    deprecation:
      reason: Replaced by a single address field.     # required, in words
      replaced_by: address                            # optional, must exist
      remove_after: 2027-03-31                        # optional, a date

THE BLOCK IS OPTIONAL ON A FILE, REQUIRED BY THE SCREEN. A hand-written
`status: deprecated` with no block stays valid -- refusing it would break
every ontology already written (principle 8). The Deprecate dialog always
writes one, so a reason exists for everything deprecated from now on.

A BLOCK ON ANYTHING NOT DEPRECATED IS AN ERROR, because it would read as
a plan and mean nothing; and a replacement that does not exist, is the
thing itself, or is itself deprecated is an error, because it points a
reader at something that is going away.

THE DATE IS INFORMATION. Nothing happens to the data on that day. The
operator is told it has arrived and asked to approve the removal (the
removal step, a later piece), which is still a person's action.

A LINK TAKES THE MOST RESTRICTIVE STATUS of itself and the two types it
joins (Foundry's rule; the owner chose it on 28 October), so deprecating a
type deprecates its links for display, and its links can then be removed
first. Nothing else cascades: a type's fields carry their own.
"""

from collections.abc import Mapping
from datetime import date

STATUSES = ("active", "experimental", "deprecated")
KEYS = frozenset({"reason", "replaced_by", "remove_after"})
MAX_REASON = 300
DEPRECATION = "deprecation"


def validate_deprecation(owner: str, name: str, definition: Mapping, siblings: Mapping, kind: str) -> None:
    """Checks one thing's block. `owner` is how a message names it, `name`
    its own name. `siblings` is what a replacement may name:
    the other types for a type, the other fields of the type for a field,
    the other link types for a link; `kind` says which, for the message."""
    block = definition.get(DEPRECATION)
    if block is None:
        return
    if definition.get("status") != "deprecated":
        raise ValueError(f"{owner}: `deprecation` describes why something is deprecated, but its "
                         f"status is {definition.get('status', 'active')!r}. Set `status: deprecated` "
                         f"or take the block out.")
    if not isinstance(block, Mapping):
        raise ValueError(f"{owner}: `deprecation` must be a mapping with a reason.")
    unknown = sorted(set(block) - KEYS)
    if unknown:
        raise ValueError(f"{owner}: deprecation has unknown key(s) {unknown}; known: {sorted(KEYS)}.")
    reason = block.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError(f"{owner}: deprecation needs a `reason`, in words.")
    if len(reason) > MAX_REASON:
        raise ValueError(f"{owner}: deprecation reason is {len(reason)} characters; at most {MAX_REASON}.")
    _check_replacement(owner, name, block.get("replaced_by"), siblings, kind)
    _check_date(owner, block.get("remove_after"))


def _check_replacement(owner: str, name: str, replacement, siblings: Mapping, kind: str) -> None:
    if replacement is None:
        return
    if not isinstance(replacement, str) or replacement not in siblings:
        raise ValueError(f"{owner}: deprecation says it is replaced by {replacement!r}, which is "
                         f"not {_a(kind)} that exists.")
    if replacement == name:
        raise ValueError(f"{owner}: deprecation says it is replaced by itself.")
    if (siblings[replacement] or {}).get("status") == "deprecated":
        raise ValueError(f"{owner}: deprecation says it is replaced by {replacement!r}, which is "
                         f"itself deprecated.")


def _a(noun: str) -> str:
    return f"{'an' if noun[0] in 'aeiou' else 'a'} {noun}"


def _check_date(owner: str, when) -> None:
    """A date written as 2027-03-31. YAML reads an unquoted one as a date
    already, so both that and the quoted text are accepted."""
    if when is None or (isinstance(when, date) and not hasattr(when, "hour")):
        return
    try:
        date.fromisoformat(when)
    except (TypeError, ValueError):
        raise ValueError(f"{owner}: remove_after must be a date like 2027-03-31, got {when!r}.") from None


def most_restrictive(*statuses: "str | None") -> str:
    """The latest of active < experimental < deprecated."""
    return max((status or "active" for status in statuses), key=STATUSES.index)


def link_status(link: Mapping, source_type: Mapping, target_type: Mapping) -> "tuple[str, str | None]":
    """(effective status, the type it came from or None) for a link.

    The second part is the type that made it more restrictive than the
    link itself, so a screen can say "deprecated because Customer is"."""
    own = link.get("status") or "active"
    effective = most_restrictive(own, source_type.get("status"), target_type.get("status"))
    if effective == own:
        return effective, None
    for side, owner in (("source", source_type), ("target", target_type)):
        if (owner.get("status") or "active") == effective:
            return effective, link[side]["object_type"]
    return effective, None
