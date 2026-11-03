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

from collections.abc import Iterable

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
