"""Evaluating triggers, and WHEN (revised 16 October, twice: checked when
data arrives, and at the moment a date window next changes).

A CONDITION CAN ONLY CHANGE IN TWO WAYS: the data under it changes, or
the clock moves under a date filter. So each is checked when it
happens, and nothing else is checked at all:

- A SYNC copies new data in from the sources: every trigger, at the
  end of it (scripts/run_sync.py).
- A CHANGE SAVED IN ELYSIUM is read at once through the read-your-
  writes overlay, before any sync: the triggers watching the object
  types it touched, straight after it is written
  (api/trigger_checks.py). Foundry the same -- live monitoring
  "within minutes of an object change appearing in the Ontology",
  and its user edits "process faster" than dataset updates.
- A NEW TRIGGER is checked the moment it is made, so its "now watching"
  arrives then rather than at the next sync.
- A TIMER, for a trigger whose view has a `relative_date` filter --
  the one filter that reads the time (core/filters.py). Such a count
  also changes as records cross the edge of the window, which is
  predictable: each evaluation sets a timer for the next crossing
  (core/trigger_windows.py, core/timers.py), and the timer evaluates
  it again. Foundry cannot monitor "relative time conditions" live and
  falls back to "scheduled monitoring" for them; a timer at the
  crossing is sooner than any schedule and does nothing in between.

Polling, as the first two versions did -- every trigger, then every
date-filtered one, every fifteen minutes -- was work that mostly found
nothing: between crossings and without new data, the count is the
count it was.

ONE PATH for all four. Owners, recipients, the write side built only
when some trigger proposes, declared and made triggers alike.

EVERYTHING SAID ABOUT TRIGGERS STILL HOLDS: each runs as its owner, a
disabled or missing owner is skipped, a recipient is counted with their
own authority, and a proposal goes to the approvals queue, never to the
source.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def watching(object_types) -> "Callable[[Any, Any], bool]":
    """The triggers a change to these object types could have moved.

    A view counts ONE object type (SavedView.object_type), filtered on
    that type's own fields, so a write to another type cannot change
    its count."""
    types = frozenset(object_types)
    return lambda trigger, view: view.object_type in types


def reads_the_clock(trigger: Any, view: Any) -> bool:
    """Whether this trigger's count can change with no new data: its
    view filters on a date relative to now."""
    return any(_operator(condition) == "relative_date"
               for condition in (view.conditions or []))


def _operator(condition: Any) -> "str | None":
    # STORED AS DICTS in a saved view, as FieldFilters in a declared
    # one -- read either rather than assume.
    if isinstance(condition, dict):
        return condition.get("operator")
    return getattr(condition, "operator", None)


def only(trigger_id: str) -> "Callable[[Any, Any], bool]":
    """One trigger, by id -- the one just made."""
    return lambda trigger, view: getattr(trigger, "trigger_id", None) == trigger_id


def run_triggers(config: Any, data_dir: Path, mediator: Any,
                 write_side: "Callable[[], tuple[Any, Any, Any]]",
                 include: "Callable[[Any, Any], bool] | None" = None,
                 on_schedule: "str | None" = None) -> int:
    """Evaluates every enabled trigger -- made in the product and
    declared in config.yaml -- and returns how many fired.

    `write_side()` returns (mediator, write mediator, pending-write
    store) and is called ONLY if some trigger can propose an action: a
    deployment whose triggers only notify builds no write path at all.
    The mediator it returns replaces `mediator`, so a proposal and the
    count it rests on are read the same way.

    `include(trigger, view)` picks which to run (watching, reads_the_
    clock, only); None runs them all, as the sync does.
    """
    # ONE EVALUATION AT A TIME, ACROSS PROCESSES. A sync, a saved
    # change and the clock can now all start one, in different
    # processes; two counting one trigger at once would both read the
    # same previous count and both say "crossed". Blocking, not
    # skipping: a check that waits still runs, and none is lost.
    import fcntl

    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / "trigger_runs.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _run_triggers_locked(config, data_dir, mediator, write_side, include, on_schedule)


def _run_triggers_locked(config, data_dir, mediator, write_side, include, on_schedule=None) -> int:
    from core.count_condition import evaluate_one_trigger, evaluate_user_triggers
    from core.notifications import NotificationStore
    from core.saved_views import SavedViewStore
    from core.timers import TimerStore
    from core.trigger_states import TriggerStateStore, schedule_hold
    from core.triggers import TriggerStore
    from core.user_directory import UserDirectory

    triggers = TriggerStore(data_dir / "triggers.db")
    # BOTH KINDS: made in the product, and declared in config.yaml.
    # They share owner resolution, the write mediator and the
    # evaluator -- a declared trigger is never a second code path.
    declared = list(config.declared_triggers)
    views = SavedViewStore(data_dir / "saved_views.db")
    made = triggers.all_enabled()
    if include is not None:
        # CHOSEN BEFORE ANYBODY IS LOOKED UP, so a change saved to one
        # type resolves the owners of the triggers watching it and no
        # others. A view that no longer exists is left to the full run
        # to report.
        #
        # A COMBINED TRIGGER IS CHOSEN IF ANY OF ITS VIEWS IS: a change
        # to either side of "A and B" can change the answer.
        made = [trigger for trigger in made
                if any(view is not None and include(trigger, view)
                       for view in _views_of(trigger, views))]
        declared = [trigger for trigger in declared if include(trigger, trigger.view)]
    enabled = [*made, *declared]
    if not enabled:
        return 0

    # ONLY THE OWNERS THAT ACTUALLY HAVE A TRIGGER. Resolving every
    # user would cost a lookup per account on a deployment where
    # nobody uses triggers at all.
    directory = UserDirectory(data_dir / "credentials.db", config.roles)
    # OWNERS, PLUS EVERY ACTIVE MEMBER OF A NAMED ROLE. Resolved
    # only for roles some trigger actually names, so a deployment
    # where nobody notifies a role pays for owners and no more.
    # A DISABLED ACCOUNT IS LEFT OUT, and so is never notified.
    named_roles = {role for trigger in enabled for role in trigger.recipient_roles}
    wanted = {trigger.owner_user_id for trigger in enabled}
    if named_roles:
        wanted |= {
            row["username"] for row in directory.list_users()
            # `role_name`, NOT `role` -- read from list_users()
            # rather than guessed. The guess matched nobody, and
            # would have notified no role member, silently.
            if row["role_name"] in named_roles and not row["disabled"]
        }
    owners = {}
    for user_id in wanted:
        try:
            if directory.is_user_disabled(user_id):
                continue
            owners[user_id] = directory.get_user_record(user_id)
        except Exception:  # noqa: BLE001 - a removed account is skipped
            continue

    write_mediator = pending_store = None
    if any(trigger.action_type for trigger in enabled):
        mediator, write_mediator, pending_store = write_side()

    notifications = NotificationStore(data_dir / "notifications.db")
    chosen = {trigger.trigger_id for trigger in made}
    states = TriggerStateStore(data_dir)
    fired = evaluate_user_triggers(
        mediator, triggers, views,
        notifications, owners, config.source_digest, write_mediator, pending_store,
        include=None if include is None else (
            lambda trigger, view: trigger.trigger_id in chosen),
        states=states, on_schedule=on_schedule,
    )
    # DECLARED TRIGGERS carry their view inline, so they skip the
    # saved-view lookup and go straight to the shared path.
    for trigger in declared:
        fired += evaluate_one_trigger(
            trigger, trigger.view, mediator, notifications, owners,
            config.source_digest, write_mediator, pending_store,
        )
    # AND EACH DATE-FILTERED ONE SETS ITS NEXT WAKE, whichever of the
    # four paths evaluated it: the moment a record next crosses its
    # window (core/trigger_windows.py). After a sync or a saved change
    # too, because a new record may cross sooner than any old one.
    _schedule_windows(data_dir, mediator, views, made, declared, owners)
    # AND A HELD ONE, the moment its earliest waiting person's hold ends.
    timers = TimerStore(data_dir)
    for trigger in made:
        if getattr(trigger, "hold_minutes", None):
            try:
                schedule_hold(timers, states, trigger)
            except Exception:  # noqa: BLE001 - one trigger's timer costs only itself
                logger.warning("could not schedule the hold of %r", trigger.name, exc_info=True)
    return fired


def _views_of(trigger, views) -> list:
    """Every view a trigger watches -- its own, and a combined one's
    others -- looked up; a missing one is None."""
    from core.trigger_states import view_ids_of

    return [views.get(view_id) for view_id in view_ids_of(trigger)]


def _schedule_windows(data_dir, mediator, views, made, declared, owners) -> None:
    from core import trigger_windows
    from core.count_condition import recipients_of
    from core.timers import TimerStore
    from core.trigger_windows import KIND, schedule

    timers = TimerStore(data_dir)
    now = trigger_windows.now()
    pairs = [(trigger, _views_of(trigger, views)) for trigger in made]
    pairs += [(trigger, [trigger.view]) for trigger in declared]
    for trigger, watched in pairs:
        if any(view is None for view in watched) or not any(
                reads_the_clock(trigger, view) for view in watched):
            continue
        owner = owners.get(trigger.owner_user_id)
        try:
            if owner is None:
                # Not evaluated, so not woken: an owner who is back
                # is evaluated by the next sync, which schedules again.
                timers.cancel(KIND, trigger.trigger_id)
                continue
            schedule(timers, trigger, mediator, watched[0],
                     recipients_of(trigger, owner, owners), now, more_views=watched[1:])
        except Exception:  # noqa: BLE001 - one trigger's wake costs only itself
            logger.warning("could not schedule trigger %r", trigger.name, exc_info=True)
