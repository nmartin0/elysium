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

import base64
import datetime as _datetime
import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
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
SCHEMA_VERSION = 2

# THE MARKER A TAGGED VALUE CARRIES.
#
# Deliberately implausible as a real column or parameter name. A dict
# in the payload that already holds this key is REFUSED at store time
# rather than round-tripped wrongly -- see _encode().
_TAG = "__elysium_type__"


class UnstorablePendingWrite(ValueError):
    """A pending write holds a value this cannot round-trip."""


def _encode(value: Any) -> Any:
    """Plain JSON, with the types a source column actually produces.

    WHY THIS EXISTS (SEC-16). to_row() used plain json.dumps with no
    fallback, and `expected_current_values` is READ FROM THE SOURCE.
    `field_types.py` returns real `date` and `datetime` objects, and
    the shipped ontology declares `decimal` for money -- with a comment
    explaining why it is not `number` -- and `date` for
    transaction_date. Measured before fixing:

        to_row(... {'amount': Decimal('49.99')})
        -> TypeError: Object of type Decimal is not JSON serializable

    which fails the proposal with a 500 rather than a refusal. It did
    not fire only because the one shipped action writes a string field.

    WHY NOT default=str, WHICH IS THE OBVIOUS FIX AND IS WRONG.
    `expected_current_values` is compared against a freshly READ value
    at confirm -- the lost-update check. A stringified Decimal would
    never equal the live Decimal, so every such write would be refused
    as a conflict: a crash traded for a silently wrong answer, which
    is the worse failure and the harder one to notice.

    SO THE TYPE TRAVELS WITH THE VALUE. Decimal goes as its exact
    string, never through float, for the reason the ontology already
    gives for choosing `decimal` over `number`.

    A COLLIDING DICT IS REFUSED, NOT GUESSED AT. A payload dict that
    already holds the marker key cannot be distinguished from a tagged
    one on the way back, so storing it would corrupt it silently. That
    is the failure this project keeps finding in other forms, so it
    raises instead -- and the caller hears it, because store() is
    documented to raise rather than be best-effort.
    """
    if isinstance(value, bool) or value is None or isinstance(value, int | float | str):
        # bool BEFORE int: isinstance(True, int) is True.
        return value
    if isinstance(value, Decimal):
        return {_TAG: "decimal", "v": str(value)}
    if isinstance(value, _datetime.datetime):
        # datetime BEFORE date: datetime is a subclass of date.
        return {_TAG: "datetime", "v": value.isoformat()}
    if isinstance(value, _datetime.date):
        return {_TAG: "date", "v": value.isoformat()}
    if isinstance(value, bytes):
        return {_TAG: "bytes", "v": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        if _TAG in value:
            raise UnstorablePendingWrite(
                f"a value holds the reserved key {_TAG!r}, which cannot be told "
                f"apart from a tagged value when read back"
            )
        return {key: _encode(inner) for key, inner in value.items()}
    if isinstance(value, list | tuple):
        return [_encode(inner) for inner in value]
    raise UnstorablePendingWrite(
        f"cannot store a value of type {type(value).__name__!r}: {value!r}"
    )


def _decode(value: Any) -> Any:
    """The inverse of _encode(), restoring the original TYPE."""
    if isinstance(value, list):
        return [_decode(inner) for inner in value]
    if not isinstance(value, dict):
        return value
    kind = value.get(_TAG)
    if kind is None:
        return {key: _decode(inner) for key, inner in value.items()}
    raw = value["v"]
    if kind == "decimal":
        return Decimal(raw)
    if kind == "datetime":
        return _datetime.datetime.fromisoformat(raw)
    if kind == "date":
        return _datetime.date.fromisoformat(raw)
    if kind == "bytes":
        return base64.b64decode(raw)
    raise UnreadablePendingWrite(f"unknown tagged type {kind!r}")


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
        "sub_writes": [_encode(asdict(sub)) for sub in pending.sub_writes],
        "user_id": pending.user_id,
        "description": pending.description,
        "action_type_name": pending.action_type_name,
        "origin": pending.origin,
        "proposed_at": _serialise_datetime(pending.proposed_at),
        "proposed_under_generation": pending.proposed_under_generation,
        "parameters": _encode(pending.parameters),
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
            sub_writes=tuple(SubWrite(**_decode(sub)) for sub in payload["sub_writes"]),
            user_id=payload["user_id"],
            description=payload["description"],
            action_type_name=payload["action_type_name"],
            origin=payload["origin"],
            proposed_at=_parse_datetime(payload["proposed_at"]),
            proposed_under_generation=payload["proposed_under_generation"],
            parameters=_decode(payload["parameters"]),
            proposer=UserRecord(**payload["proposer"]),
        )
    except (KeyError, TypeError, ValueError) as e:
        # A FIELD ADDED TO THE DATACLASS LANDS HERE, which is the point
        # of catching TypeError: PendingWrite(**...) raises for a
        # missing argument, so the shape version and the constructor
        # agree or nothing is restored.
        raise UnreadablePendingWrite(f"does not fit this build's shape: {e}") from e
