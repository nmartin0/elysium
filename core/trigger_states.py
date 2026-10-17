"""Combined triggers: conditions that are STATES (17 October).

A trigger so far has watched one count for one change -- above a line,
or gaining or losing so many since last time. The owner asked for
triggers that combine, and the precedent says how:

- ALL OR ANY OF SEVERAL CONDITIONS. Datadog's composite monitors join
  monitors with AND, OR and NOT, at most ten, and "can't include other
  composite monitors". Here a condition is one of the owner's saved
  views with "above N" or "at most N" -- at most ten, combined by all
  or any, never a trigger inside a trigger.
- TRUE FOR AT LEAST SO LONG. Prometheus' `for`: "Elements that are
  active, but not firing yet, are in the pending state." The hold
  starts when a person's combination becomes true and a TIMER fires at
  its end (core/timers.py), so it is on time even if no data arrives;
  it resets if the combination stops being true first.
- ON A SCHEDULE. Foundry Automate's "combination of time-based and
  object data conditions": checked only at the schedule's times
  (core/timer_rules.py), and told EVERY time it is true then -- a
  morning digest, not an alarm.

CONDITIONS ARE STATES, NOT CHANGES. "Gaining 3" and "losing 3" describe
what happened since the last check; ANDing two changes asks whether
both happened in the same instant, which has no answer anybody wants.
So they stay single, and a combined trigger takes `above` and
`at_most` -- refused otherwise, with that reason.

FIRES WHEN IT BECOMES TRUE, ONCE, until it stops being true -- the
rule the single trigger follows ("CROSSED, NOT MERELY ABOVE") and the
latch that makes "true once is enough" hold: a later check while still
true does not fire again, and one while false re-arms it. The first
evaluation is a BASELINE, with a "now watching" notice saying whether
it is currently met, never a flood.

EACH PERSON THEIR OWN STATE, counted with their own authority by the
same count_for_each every trigger uses: the owner and each member of a
named role may see different records, so each has their own
true-since and their own latch. No privileged count exists.

AND PROPOSE, like any trigger (decided 17 October, the owner: "isn't
that the main point of the triggers?"). Foundry's answer to "which
objects": an action parameter takes the objects a CONDITION exposes,
and "the type of the action parameter needs to align with the type of
the exposed condition effect input". So the maker names WHICH
condition's view supplies the objects -- the trigger's own by default --
and the parameter must take that view's type. Proposed AS THE OWNER,
when THE OWNER's state fires -- becoming true, a hold completing, or a
scheduled check finding it true -- never because a recipient's did.
What is proposed is what that view matches NOW, less anything this
automation already has waiting (R50), so a daily check proposes only
what is new.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.sqlite_connection import connection_with_schema

logger = logging.getLogger(__name__)

#: Datadog's limit on what one composite joins.
MAX_CONDITIONS = 10
#: The longest a condition may be required to hold: a week.
MAX_HOLD_MINUTES = 10_080
HOLD_KIND = "trigger.hold"
SCHEDULE_KIND = "trigger.schedule"
#: A scheduled check found more than this late was MISSED, and its
#: owner is told rather than shown a 09:00 digest at 11:00.
SCHEDULE_LATE_AFTER_SECONDS = 3600.0


def is_state_trigger(trigger: Any) -> bool:
    """Whether this trigger is evaluated as a state (this file) rather
    than as a change in one count (core/count_condition.py). getattr,
    so a declared trigger without these fields reads as single."""
    return bool(getattr(trigger, "at_most", None) is not None
                or getattr(trigger, "also", ())
                or getattr(trigger, "hold_minutes", None)
                or getattr(trigger, "schedule", None))


def conditions_of(trigger: Any) -> list[dict]:
    """Every condition, the trigger's own first: [{view_id, above |
    at_most}]."""
    first: dict = {"view_id": trigger.view_id}
    if trigger.above is not None:
        first["above"] = trigger.above
    elif getattr(trigger, "at_most", None) is not None:
        first["at_most"] = trigger.at_most
    return [first, *[dict(condition) for condition in getattr(trigger, "also", ())]]


def view_ids_of(trigger: Any) -> list[str]:
    return [condition["view_id"] for condition in conditions_of(trigger)]


def action_view_id(trigger: Any) -> str:
    """Whose objects the action receives: the chosen condition's view,
    or the trigger's own."""
    return getattr(trigger, "action_view_id", None) or trigger.view_id


def problem(*, above, gained, fell, at_most, also, combine, hold_minutes, schedule,
            action_type, owned_view_ids: set, view_id: "str | None" = None,
            action_view: "str | None" = None) -> "str | None":
    """Why this combination cannot be made, or None. Checked when the
    trigger is made, where its maker can fix it."""
    main = [value for value in (above, gained, fell, at_most) if value is not None]
    if len(main) != 1:
        return "A trigger watches one of above, at most, gaining or losing, not several."
    # CHECKED BEFORE ANYTHING ELSE RETURNS, single triggers included: an
    # action naming a view outside the trigger would act on something it
    # does not watch.
    if action_type is None and action_view is not None:
        return "Objects for an action were chosen, but no action."
    if action_view is not None and action_view not in {
            view_id, *(condition.get("view_id") for condition in also or []
                       if isinstance(condition, dict))}:
        # ONE OF ITS OWN CONDITIONS, never some other view: the action
        # acts on what this trigger watches.
        return "An action takes its objects from one of this trigger's own conditions."
    combined = bool(also) or hold_minutes is not None or schedule is not None
    if not combined and at_most is None:
        return None
    if gained is not None or fell is not None:
        return ("Gaining and losing describe a change since the last check, not a "
                "state, so they cannot be combined, held or scheduled. Use above or "
                "at most.")
    if combine not in ("all", "any"):
        return "Combine conditions with all or any."
    if len(also or []) + 1 > MAX_CONDITIONS:
        return f"At most {MAX_CONDITIONS} conditions in one trigger."
    for condition in also or []:
        if not isinstance(condition, dict) or condition.get("view_id") not in owned_view_ids:
            # THE SAME WORDS whether the view is someone else's or does
            # not exist -- uniform denial, as the trigger's own view.
            return "Each condition watches one of your own saved views."
        values = [condition.get(key) for key in ("above", "at_most") if condition.get(key) is not None]
        extra = set(condition) - {"view_id", "above", "at_most"}
        if len(values) != 1 or extra or not all(
                isinstance(value, int) and not isinstance(value, bool) and value >= 0
                for value in values):
            return "Each condition is above or at most a whole number, and nothing else."
    if hold_minutes is not None:
        if (not isinstance(hold_minutes, int) or isinstance(hold_minutes, bool)
                or not 1 <= hold_minutes <= MAX_HOLD_MINUTES):
            return f"Hold for 1 minute to {MAX_HOLD_MINUTES} minutes (a week)."
        if schedule is not None:
            return ("A scheduled trigger is checked at its times, so it cannot also "
                    "require being true for a while in between.")
    if schedule is not None:
        from core.timer_rules import RuleError, validate

        try:
            validate(schedule)
        except RuleError as e:
            return str(e)
    return None


def describe(trigger: Any, view_names: dict) -> str:
    """What a combined trigger watches, as a sentence -- its notices'
    text and the Watching list's."""
    from core.reminders import describe_repeat

    parts = []
    for condition in conditions_of(trigger):
        name = view_names.get(condition["view_id"], "a view")
        if "above" in condition:
            parts.append(f"{name} above {condition['above']}")
        else:
            parts.append(f"{name} at most {condition['at_most']}")
    joined = f" {'and' if trigger.combine == 'all' else 'or'} ".join(parts)
    hold = getattr(trigger, "hold_minutes", None)
    if hold:
        joined += f", for {_duration(hold)}"
    schedule = getattr(trigger, "schedule", None)
    if schedule:
        joined += f", checked {describe_repeat(schedule)}"
    return joined


def _duration(minutes: int) -> str:
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"{days} {'day' if days == 1 else 'days'}"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} {'hour' if hours == 1 else 'hours'}"
    return f"{minutes} {'minute' if minutes == 1 else 'minutes'}"


# --- What each person's combination last was --------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS trigger_state (
    trigger_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    -- Whether the combination held at the last evaluation.
    holds INTEGER NOT NULL,
    -- Since when it has held, seconds since the epoch; NULL if not.
    since REAL,
    -- Whether it has fired since it last became true: the latch.
    fired INTEGER NOT NULL,
    -- The configuration it was measured under. A different one is a
    -- new baseline, as for single triggers: somebody granted a region
    -- sees more without anything being added.
    digest TEXT,
    PRIMARY KEY (trigger_id, user_id)
);
"""


@dataclass(frozen=True)
class State:
    holds: bool
    since: "float | None"
    fired: bool
    digest: "str | None"


class TriggerStateStore:
    def __init__(self, data_dir: Path):
        self._db_path = Path(data_dir) / "triggers.db"

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def get(self, trigger_id: str, user_id: str) -> "State | None":
        with self._connection() as conn:
            row = conn.execute(
                "SELECT holds, since, fired, digest FROM trigger_state "
                "WHERE trigger_id = ? AND user_id = ?", (trigger_id, user_id)).fetchone()
        return None if row is None else State(bool(row[0]), row[1], bool(row[2]), row[3])

    def put(self, trigger_id: str, user_id: str, state: State) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO trigger_state (trigger_id, user_id, holds, since, fired, digest) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (trigger_id, user_id) DO UPDATE SET "
                "holds = excluded.holds, since = excluded.since, fired = excluded.fired, "
                "digest = excluded.digest",
                (trigger_id, user_id, int(state.holds), state.since, int(state.fired), state.digest))
            conn.commit()

    def pending_until(self, trigger_id: str, hold_seconds: float) -> "float | None":
        """When the earliest person still waiting out the hold reaches
        its end, or None if nobody is."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT MIN(since) FROM trigger_state WHERE trigger_id = ? "
                "AND holds = 1 AND fired = 0 AND since IS NOT NULL", (trigger_id,)).fetchone()
        return None if row is None or row[0] is None else float(row[0]) + hold_seconds

    def forget(self, trigger_id: str) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM trigger_state WHERE trigger_id = ?", (trigger_id,))
            conn.commit()


# --- Evaluation ----------------------------------------------------------


@dataclass(frozen=True)
class Evaluated:
    #: How many people were told.
    told: int
    #: Whether THE OWNER's state fired -- what an action waits on.
    owner_fired: bool


def evaluate(trigger: Any, owner: Any, views: list, mediator: Any, notifications: Any,
             user_records: dict, digest: "str | None", states: TriggerStateStore,
             now: datetime, on_schedule: "str | None" = None) -> Evaluated:
    """One combined trigger, for each of its recipients. Says how many
    were told, and whether the owner's state fired.

    `views` are the SavedViews of conditions_of(trigger), in order.
    `on_schedule` is the schedule occurrence's key when the schedule
    timer called this, and None otherwise.
    """
    from core.count_condition import count_for_each, recipients_of

    conditions = conditions_of(trigger)
    recipients = recipients_of(trigger, owner, user_records)
    counts = [count_for_each(mediator, view, recipients) for view in views]
    view_names = {view.view_id: view.name for view in views}
    sentence = describe(trigger, view_names)
    stamp = now.timestamp()
    scheduled = bool(getattr(trigger, "schedule", None))
    hold = (getattr(trigger, "hold_minutes", None) or 0) * 60.0
    told = 0
    owner_fired = False

    for recipient in recipients:
        user_id = recipient.user_id
        if any(user_id not in by_user for by_user in counts):
            # A COUNT THAT COULD NOT BE TAKEN is unknown, not zero: the
            # state is left as it was rather than flipped by a failure.
            continue
        met_each = [_meets(condition, by_user[user_id])
                    for condition, by_user in zip(conditions, counts, strict=True)]
        met = all(met_each) if trigger.combine == "all" else any(met_each)
        previous = states.get(trigger.trigger_id, user_id)

        if previous is None or previous.digest != digest:
            # THE BASELINE. Recorded, latched if already true, and said
            # once -- a trigger made while its condition holds does not
            # fire for a crossing that happened before it existed.
            states.put(trigger.trigger_id, user_id,
                       State(met, stamp if met else None, met, digest))
            if previous is None:
                notifications.notify(
                    user_id, "trigger",
                    f"{trigger.name}: now watching -- {sentence}. Currently "
                    f"{'met' if met else 'not met'}.")
                told += 1
            continue

        if scheduled:
            states.put(trigger.trigger_id, user_id,
                       State(met, stamp if met else None, met, digest))
            if on_schedule is not None and met:
                # EVERY SCHEDULED TIME IT IS TRUE, once per occurrence
                # per person -- the occurrence's key makes a second
                # delivery a no-op.
                notifications.notify(user_id, "trigger", f"{trigger.name}: {sentence} -- met.",
                                     dedupe_key=f"{on_schedule}/{user_id}")
                told += 1
                owner_fired = owner_fired or user_id == owner.user_id
            continue

        if not met:
            states.put(trigger.trigger_id, user_id, State(False, None, False, digest))
            continue
        since = previous.since if previous.holds and previous.since is not None else stamp
        fired = previous.fired if previous.holds else False
        if not fired and stamp - since >= hold:
            notifications.notify(user_id, "trigger", f"{trigger.name}: {sentence} -- met.")
            fired = True
            told += 1
            owner_fired = owner_fired or user_id == owner.user_id
        states.put(trigger.trigger_id, user_id, State(True, since, fired, digest))
    return Evaluated(told, owner_fired)


def _meets(condition: dict, count: int) -> bool:
    if "above" in condition:
        return count > condition["above"]
    return count <= condition["at_most"]


def schedule_hold(timers: Any, states: TriggerStateStore, trigger: Any) -> None:
    """Sets the timer for the earliest person still waiting out the
    hold, or clears it if nobody is."""
    hold = getattr(trigger, "hold_minutes", None)
    if not hold:
        return
    until = states.pending_until(trigger.trigger_id, hold * 60.0)
    if until is None:
        timers.cancel(HOLD_KIND, trigger.trigger_id)
    else:
        timers.set(HOLD_KIND, trigger.trigger_id, until)


def first_check(trigger: Any, now: datetime) -> "float | None":
    """When a scheduled trigger's schedule first fires."""
    from core.timer_rules import first_occurrence

    following = first_occurrence(trigger.schedule, now)
    return None if following is None else following.timestamp()


def arm_schedule(timers: Any, trigger: Any, now: "datetime | None" = None) -> None:
    """Sets a scheduled trigger's repeating check (on making it, or
    turning it back on)."""
    if not getattr(trigger, "schedule", None):
        return
    due = first_check(trigger, now or datetime.now(UTC))
    if due is None:
        return
    timers.set(SCHEDULE_KIND, trigger.trigger_id, due, owner_user_id=trigger.owner_user_id,
               late_after=SCHEDULE_LATE_AFTER_SECONDS, repeat=trigger.schedule)


def disarm(timers: Any, states: TriggerStateStore, trigger_id: str) -> None:
    """Everything a trigger set for itself, gone: turned off or deleted."""
    from core.trigger_windows import KIND as WINDOW_KIND

    for kind in (SCHEDULE_KIND, HOLD_KIND, WINDOW_KIND):
        timers.cancel(kind, trigger_id)
    states.forget(trigger_id)
