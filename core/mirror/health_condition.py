"""The mirror's own health, as a condition somebody is told about.

WHY THIS CONDITION FIRST. The facts were already recorded and nothing
watched them: `sync_attempts` knows every refusal, and the admin panel
shows staleness to whoever happens to open it. An administrator who
does not open it learns nothing, which is the wrong way round for the
one thing that makes every read stale.

AND IT ADMITS NO ACTION EFFECT, which is the real reason it goes
first. You cannot auto-fix a refused sync. So this exercises the whole
path -- condition, effect, recipient -- with a notification, and needs
neither the approvals queue nor saved views server-side.

EVALUATED PER RECIPIENT, like everything else here. The mirror's
health is not per-user data, so every recipient sees the same summary
-- but the RECIPIENT LIST is derived from a grant, and that is the
part that must not be a hardcoded list of names.
"""

import logging
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

# HOW LONG A TABLE MAY GO WITHOUT CHANGING before it is worth saying
# so.
#
# A JUDGEMENT, NOT A MEASUREMENT, and a deliberately loose one. A
# table whose source genuinely changes once a week is not broken, and
# a threshold tight enough to catch a stuck sync on an hourly table
# would cry wolf on that one. Twenty-five hours catches "the nightly
# sync did not run" without firing on a daily one that ran late.
STALE_AFTER = timedelta(hours=25)

# THE GRANT THAT MAKES SOMEBODY A RECIPIENT. The same one that can
# start a sync -- if you can fix it, you should hear that it needs
# fixing.
RECIPIENT_GRANT = "manage:deployment"

_CONDITION_KEY = "mirror_health"


def _stale_tables(states: list[dict], now: datetime) -> list[str]:
    """Tables whose data has not changed recently enough.

    NEVER-SYNCED IS NOT STALE. A table with no snapshot at all is a
    deployment that has not synced yet, which the panel already says
    plainly -- telling somebody it is "stale" would describe a fresh
    install as a fault.
    """
    stale = []
    for state in states:
        last = state.get("last_synced_at")
        if not last:
            continue
        try:
            when = datetime.fromisoformat(last)
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if now - when > STALE_AFTER:
            stale.append(f"{state['silo']}.{state['table']}")
    return stale


def _refused_tables(states: list[dict]) -> list[str]:
    """Tables whose last sync attempt was refused.

    THE LAST ATTEMPT, not any attempt. A refusal that has since been
    followed by a successful sync is history, and the panel's
    attempt column already shows it.
    """
    return [
        f"{state['silo']}.{state['table']}"
        for state in states
        if state.get("last_attempt_outcome") == "refused"
    ]


def summarise_mirror_health(states: list[dict],
                            now: datetime | None = None) -> str | None:
    """What is wrong with the mirror, in one line, or None.

    ONE NOTIFICATION FOR THE WHOLE MIRROR, not one per table. Five
    stale tables are usually one stuck sync, and five notices about it
    teach less than one.
    """
    now = now or datetime.now(UTC)
    refused = _refused_tables(states)
    stale = _stale_tables(states, now)
    if not refused and not stale:
        return None

    parts = []
    if refused:
        parts.append(
            f"{len(refused)} table(s) refused their last sync: "
            f"{', '.join(sorted(refused)[:3])}"
            + (" and others" if len(refused) > 3 else "")
        )
    if stale:
        parts.append(
            f"{len(stale)} table(s) have not changed in over "
            f"{int(STALE_AFTER.total_seconds() // 3600)} hours: "
            f"{', '.join(sorted(stale)[:3])}"
            + (" and others" if len(stale) > 3 else "")
        )
    return ". ".join(parts) + "."


def notify_mirror_health(states: list[dict], recipients: list[str],
                         store, now: datetime | None = None) -> int:
    """Tells whoever can fix it. Returns how many were told.

    RETURNS A COUNT because "nobody was told" and "nobody needed
    telling" are different outcomes, and a caller that cannot tell them
    apart cannot report either.

    REPEATS ARE SUPPRESSED PER RECIPIENT. A standing condition is true
    until somebody fixes it, and a notification per sync is a channel
    nobody reads by the time it matters. A CHANGED summary is news and
    goes through.
    """
    summary = summarise_mirror_health(states, now)
    if summary is None:
        return 0

    told = 0
    for user_id in recipients:
        if store.already_notified(_CONDITION_KEY, user_id, summary):
            continue
        if store.notify(
            user_id, "mirror_health", summary,
            detail=(
                "Reads are served from the mirror, so this affects what "
                "everybody sees. Admin -> Mirror shows each table, and "
                "Sync now starts one."
            ),
        ):
            store.record_notified(_CONDITION_KEY, user_id, summary)
            told += 1
    return told
