"""The state of an object type's data while a retype rebuilds silver (R2).

BLOCKING.md, "RETYPE, CHECKED AND SLICED": an object is LIVE, REBUILDING
or UNAVAILABLE. Nothing here is stored. A marker saying "a rebuild is owed"
goes stale the day someone fixes the type back by hand, so each answer is
worked out again from what the lake says now:

  rebuild owed   the table's silver differs from the declared type
                 (core/ontology/retype.tables_needing_rebuild). This is
                 NOT a state of the object: until a person presses
                 "Rebuild now" the old silver serves unchanged.
  rebuilding     the table's last recorded attempt is "rebuilding" (the
                 sync records it just before it drops and rebuilds that
                 silver) AND a sync holds the lock right now. The lock is
                 what stops a rebuild that died from reading "rebuilding"
                 for ever: without it the table is live, and owed again.
  unavailable    it cannot be told: the lake could not be read, or the
                 lock could not be tried. Never guessed as live.
  live           anything else. Old silver keeps serving until the swap.

A type's state is the worst of its tables': unavailable, then rebuilding,
then live.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

LIVE = "live"
REBUILDING = "rebuilding"
UNAVAILABLE = "unavailable"

#: The outcome run_sync records (core/mirror/sync_attempts) when it starts
#: rebuilding a table's silver.
REBUILDING_OUTCOME = "rebuilding"

_WORST_FIRST = (UNAVAILABLE, REBUILDING, LIVE)


def table_state(*, owed_known: bool, last_outcome: str | None, sync_running: bool | None) -> str:
    """live / rebuilding / unavailable for one silver table.

    owed_known: the lake could be read to find the tables owed a rebuild.
    last_outcome: the table's last recorded sync attempt, if any.
    sync_running: a sync holds the lock now; None when that could not be tried."""
    if not owed_known:
        return UNAVAILABLE
    if last_outcome == REBUILDING_OUTCOME:
        if sync_running is None:
            return UNAVAILABLE
        return REBUILDING if sync_running else LIVE
    return LIVE


def type_state(states: Iterable[str]) -> str:
    """The worst of the tables an object type reads (live when it reads none)."""
    found = set(states)
    for state in _WORST_FIRST:
        if state in found:
            return state
    return LIVE


def hold_reason(states: Mapping[str, str], object_types: Iterable[str]) -> str | None:
    """Why a write to these object types is held, or None when it may go on (R4).

    `states` is {object type: state}, from the SAME derivation the Mirror
    panel shows (api/routes._mirror_states): this module is the only place
    that decides what "rebuilding" means, and a write asks it rather than
    deciding again. A type with no entry reads no silver table, so there is
    nothing to rebuild and it is not held.

    A WRITE IS HELD, NOT REFUSED: the proposal stays in the queue and the
    same approval goes through once the state is live again, judged then
    against the schema as it is by then (confirm_and_execute re-runs every
    check at the point of use). REBUILDING is held because the plan says so
    (BLOCKING.md, "RETYPE, CHECKED AND SLICED": writes proposed meanwhile
    are held), so that a write does not race the rebuild. UNAVAILABLE is
    held too: a state that cannot be told is never guessed live."""
    rebuilding = sorted({name for name in object_types if states.get(name) == REBUILDING})
    unknown = sorted({name for name in object_types if states.get(name) == UNAVAILABLE})
    if unknown:
        return (f"Whether {', '.join(unknown)} is being rebuilt cannot be told just now (the mirror or the "
                f"sync could not be read), so this change is held rather than guessed safe. It stays in the "
                f"queue: try again shortly.")
    if rebuilding:
        return (f"{', '.join(rebuilding)} {'is' if len(rebuilding) == 1 else 'are'} being rebuilt after a "
                f"change of data type, so this change is held until the rebuild has finished. It stays in the "
                f"queue, and when it goes ahead it is checked again against the type as it is by then.")
    return None
