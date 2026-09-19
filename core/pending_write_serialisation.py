"""Turning a pending write into rows and back.

WHY THIS IS A SEPARATE MODULE. `PendingWriteStore` holds writes in a
locked dict and knows nothing about storage; the ontology's
`PendingWrite` knows nothing about either. Putting the translation in
a third place keeps both of those true, and means a change to the
dataclass fails HERE -- loudly, at import or in a round-trip test --
rather than silently writing a row that cannot be read back.

EVERYTHING IS PLAIN DATA, which is why this is possible at all:
dataclasses, dicts, a datetime, and a UserRecord of three strings. No
adapter handles, no open connections, nothing that means anything only
inside one process.

WHAT A RESTORED WRITE IS: a PROPOSAL, not an approval. Every question
about whether it may now be executed is asked again at confirm time,
against the CURRENT configuration -- `confirm` authorises against the
current generation's roles, MAC and the submission criteria are
evaluated inside `confirm_and_execute()`, and
`_fields_no_longer_declared()` refuses one whose target fields the
ontology has since dropped. Nothing here grants anything.
"""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from core.intermediate_layer.auth import UserRecord
from core.ontology.write_mediator import PendingWrite, SubWrite

# THE SHAPE VERSION, stored beside every row.
#
# A restored write is REFUSED rather than guessed at when this does not
# match. The alternative -- reading an old row with new code and
# filling the gaps with defaults -- produces a write that looks
# complete and means something nobody wrote, which is the failure this
# project keeps finding in other forms.
SCHEMA_VERSION = 1


def _serialise_datetime(value: datetime) -> str:
    return value.isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    # TIMEZONE-AWARE ON THE WAY BACK, always. Everything in this
    # project stores UTC with an offset, and a naive datetime read back
    # would compare wrongly against an aware one -- silently, and only
    # under a TTL check.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def to_row(pending: PendingWrite) -> str:
    """One pending write, as JSON."""
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sub_writes": [asdict(sub) for sub in pending.sub_writes],
        "user_id": pending.user_id,
        "description": pending.description,
        "action_type_name": pending.action_type_name,
        "origin": pending.origin,
        "proposed_at": _serialise_datetime(pending.proposed_at),
        "proposed_under_generation": pending.proposed_under_generation,
        "parameters": pending.parameters,
        "proposer": asdict(pending.proposer),
    }
    return json.dumps(payload)


class UnreadablePendingWrite(ValueError):
    """A stored write cannot be turned back into one.

    ITS OWN TYPE so a caller can keep going past it. One unreadable row
    should cost its own write, not the whole queue -- a restart that
    dropped every pending approval because one was written by an older
    version would be worse than the problem being solved.
    """


def from_row(raw: str) -> PendingWrite:
    """JSON back into a pending write, or a refusal."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise UnreadablePendingWrite(f"not valid JSON: {e}") from e

    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise UnreadablePendingWrite(
            f"stored in shape version {version!r}, and this build reads "
            f"{SCHEMA_VERSION}. Refusing rather than guessing at the "
            f"difference."
        )

    try:
        return PendingWrite(
            sub_writes=tuple(SubWrite(**sub) for sub in payload["sub_writes"]),
            user_id=payload["user_id"],
            description=payload["description"],
            action_type_name=payload["action_type_name"],
            origin=payload["origin"],
            proposed_at=_parse_datetime(payload["proposed_at"]),
            proposed_under_generation=payload["proposed_under_generation"],
            parameters=payload["parameters"],
            proposer=UserRecord(**payload["proposer"]),
        )
    except (KeyError, TypeError, ValueError) as e:
        # A FIELD ADDED TO THE DATACLASS LANDS HERE, which is the point
        # of catching TypeError: PendingWrite(**...) raises for a
        # missing argument, so the shape version and the constructor
        # agree or nothing is restored.
        raise UnreadablePendingWrite(f"does not fit this build's shape: {e}") from e
