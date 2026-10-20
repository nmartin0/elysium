"""A total per period projected to cross a line: a trigger's warning (R68).

    "Refunds per week projected above 50"

The trigger's saved view, counted per day, week or month of one of its
date fields (core/periods.py), and forecast (core/forecasts.py). It
fires when the forecast -- the line itself, not the edge of its range --
passes the threshold in any period ahead. The owner chose "totals per
period" over a history of a trigger's own counts, 18 October: the
history comes from the date field, so it warns from the first day.

THE FORECAST LINE, NOT THE TOP OF THE RANGE. Datadog's forecast monitors
alert when the forecast's bounds cross the threshold; but the top of an
80% range is passed one period in ten by chance alone, so a trigger on
it would warn about ordinary periods. Here the warning
means "this is where it is heading", and the range rides in the message
for the reader to weigh.

A STATE, TOLD WHEN IT BEGINS -- like "above", not "gained". Told once on
becoming projected; not again while it stays so; told again only after
the projection has gone back under the line and crossed once more.

A FORECAST THAT IS NOT TRUSTED SAYS NOTHING. When the forecast is
refused -- too little history, or no better than carrying the last
period on -- the trigger neither fires nor clears; its "now watching"
says why there is no projection yet.

AS EACH RECIPIENT. Every person's projection is made from their OWN
totals, under their own access, exactly as every count a trigger makes
is (count_condition.count_for_each): no privileged forecast exists to
leak from. Notify only: a projection is not something to act on
unattended.

WHEN IT IS CHECKED: when a trigger is checked -- after a sync, after a
change to its type, when it is made (core/trigger_runs.py). Not at the
turn of a period with no new data; the next sync sees it.
"""

import datetime
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Notification kinds.
KIND = "projected_condition"
WATCHING = "projected_condition_watching"


def is_projected(trigger: Any) -> bool:
    return getattr(trigger, "projected_field", None) is not None


def problem(view_object_type: str, schema: dict, field: "str | None", period: "str | None",
            above: "float | None", *, others: dict) -> "str | None":
    """Why this projected condition cannot be made, or None. Checked when
    the trigger is made, where its maker can fix it.

    `others` are the trigger's other settings; a projected condition
    stands alone, so any of them set is refused by name."""
    from core.periods import PERIODS, TEMPORAL

    if field is None and period is None and above is None:
        return None
    if field is None or period is None or above is None:
        return "A projected condition needs a date field, a period and a line to cross."
    if period not in PERIODS:
        return f"The period is one of {', '.join(PERIODS)}."
    declared = (((schema.get(view_object_type) or {}).get("fields") or {}).get(field) or {})
    if declared.get("data_type") not in TEMPORAL:
        return (f"{field!r} is not a date field of {view_object_type}; a projection counts "
                f"records per period of a date.")
    if not above > 0:
        return "The line to cross is a number above 0."
    named = sorted(name for name, value in others.items() if value not in (None, [], {}, ""))
    if named:
        return (f"A projected condition stands alone, so it cannot also have "
                f"{', '.join(named)}.")
    return None


def _conditions_of(view) -> list:
    from core.filters import FieldFilter

    return [FieldFilter(field=condition["field"], operator=condition["operator"],
                        value=condition.get("value")) for condition in view.conditions]


def projection_for(mediator, view, trigger, user_record, today: datetime.date) -> dict:
    """{state: projected | clear | untrusted, ...} for one person, from
    their own totals."""
    from core.forecasts import cached_forecast, finished_series
    from core.ontology.mediator import SearchOutcome

    outcome = SearchOutcome()
    totals = mediator.aggregate_by_field(
        user_record, view.object_type, _conditions_of(view),
        group_by=trigger.projected_field, aggregate="count",
        outcome=outcome, query_text=view.query_text or "", period=trigger.projected_period)
    if outcome.scan_truncated:
        return {"state": "untrusted",
                "reason": "only part of the set could be counted, so there is no forecast"}
    series = finished_series(totals, trigger.projected_period, today)
    starts, values = series.to_fit
    made = cached_forecast(values, starts, trigger.projected_period, True)
    if made.refusal:
        return {"state": "untrusted", "reason": made.refusal.rstrip(".")}
    crossing = next((point for point in made.points
                     if point["value"] > trigger.projected_above), None)
    if crossing is None:
        return {"state": "clear", "peak": max(point["value"] for point in made.points),
                "horizon": len(made.points)}
    return {"state": "projected", "point": crossing, "backtest": made.backtest}


def _sentence(trigger, projection: dict) -> str:
    from core.triggers import describe

    point = projection["point"]
    when = datetime.date.fromisoformat(point["start"])
    period = trigger.projected_period
    named = {"day": when.strftime("%d %b %Y"), "week": f"the week of {when:%d %b %Y}",
             "month": when.strftime("%B %Y")}[period]
    share = projection["backtest"].get("share")
    tested = "" if share is None else f"; tested, it was off by about {share:.0%} a {period}"
    return (f"{describe(trigger)}: forecast {point['value']:.0f} for {named} (80% range "
            f"{point['low']:.0f} to {point['high']:.0f}){tested}.")


def evaluate_projected(trigger, view, mediator, store, user_records: dict,
                       config_digest: "str | None", today: "datetime.date | None" = None) -> int:
    """One projected trigger, for its owner and its recipients. Returns
    how many were told it has become projected."""
    from core.count_condition import recipients_of
    from core.triggers import describe

    owner = user_records.get(trigger.owner_user_id)
    if owner is None:
        logger.warning("trigger %r names owner %r, who does not exist or is disabled",
                       trigger.name, trigger.owner_user_id)
        return 0
    if view.object_type not in mediator.schema:
        logger.warning("view %r names object type %r, which the ontology no longer declares",
                       view.name, view.object_type)
        return 0
    today = today or datetime.datetime.now(datetime.UTC).date()
    told = 0
    for person in recipients_of(trigger, owner, user_records):
        try:
            projection = projection_for(mediator, view, trigger, person, today)
        except Exception as e:  # noqa: BLE001 - one person's failure costs only them
            logger.warning("could not project trigger %r as %s: %s", trigger.name,
                           person.user_id, e)
            continue
        key = trigger.condition_key
        previous, previous_digest = store.last_measurement(key, person.user_id)
        if projection["state"] == "untrusted":
            if previous is None:
                store.record_count(key, person.user_id, 0, config_digest)
                store.notify(person.user_id, WATCHING,
                             f"{describe(trigger)}: now watching. No projection yet: "
                             f"{projection['reason']}.")
            continue
        current = 1 if projection["state"] == "projected" else 0
        store.record_count(key, person.user_id, current, config_digest)
        if previous is None:
            now = ("currently projected to pass it" if current
                   else f"currently projected at most {projection['peak']:.0f} in the next "
                        f"{projection['horizon']} {trigger.projected_period}s")
            store.notify(person.user_id, WATCHING, f"{describe(trigger)}: now watching, "
                         f"{now}.")
            continue
        # A CHANGED CONFIGURATION IS A NEW BASELINE, as for counts: a
        # grant change moves what a person can see, not what is happening.
        changed = previous_digest is not None and config_digest is not None \
            and previous_digest != config_digest
        if current and not previous and not changed:
            summary = _sentence(trigger, projection)
            if store.notify(person.user_id, KIND, summary):
                store.record_notified(key, person.user_id, summary)
                told += 1
    return told
