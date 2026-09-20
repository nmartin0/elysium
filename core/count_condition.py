"""A condition on how many objects match, per recipient.

WHAT THIS IS NOT: a diff. It does not say WHICH objects appeared,
because knowing that means storing last time's result set, and no
alerting system worth copying does.

Databricks stores state -- alerts "resolve to OK, TRIGGERED, or
ERROR". Google Cloud compares "the number of rows in the query result"
against a threshold over a lookback window. The canonical
change-detection pattern is a saved watermark. All of them keep a
number or a flag; none keeps the answer.

WHICH MAKES PER-RECIPIENT EVALUATION FREE. Storing each person's
previous result set would be tens of thousands of ids times however
many recipients. An integer each is nothing -- and it is the only
thing a "3 more than last time" notification needs.

EVALUATED ONCE PER RECIPIENT, AGAINST THEIR OWN HISTORY. There is no
owner evaluation and no filtering: `search_object(user_record, ...)`
already takes a user, so each person's count comes from their own
authority and is compared to their own last count. Nobody computes a
privileged number and redacts it, because no privileged number exists.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CountCondition:
    """When a count is worth telling somebody about."""

    key: str
    description: str
    # FIRES WHEN THE COUNT RISES ABOVE THIS. None disables it.
    above: int | None = None
    # FIRES WHEN IT GAINS AT LEAST THIS MANY since last time. None
    # disables it.
    gained: int | None = None


def _verdict(condition: CountCondition, previous: int | None,
             current: int) -> str | None:
    """What to say about this count, or nothing.

    THE FIRST EVALUATION IS A BASELINE AND SAYS NOTHING. A condition
    declared today has no previous count, and treating that as zero
    would report every existing match as a gain -- the flood a
    monitoring tool that hit it warns about: "the first successful run
    creates a baseline, never a flood of fake new ads".
    """
    if previous is None:
        return None

    if condition.above is not None and current > condition.above:
        # CROSSED, NOT MERELY ABOVE. A threshold that reports every
        # evaluation while the count stays high is a channel nobody
        # reads; `already_notified` suppresses the repeat, and this
        # still fires again if the number changes.
        if previous <= condition.above:
            return (
                f"{condition.description}: now {current}, above "
                f"{condition.above}."
            )
        if current != previous:
            return (
                f"{condition.description}: now {current}, still above "
                f"{condition.above}."
            )
        return None

    if condition.gained is not None and current - previous >= condition.gained:
        gain = current - previous
        return (
            f"{condition.description}: {gain} more than last time "
            f"({previous} to {current})."
        )

    # A COUNT THAT FELL IS NOT REPORTED, deliberately. An object
    # leaving a filtered set may mean it changed, was deleted, or that
    # the reader's grants changed -- and the third is indistinguishable
    # from the first two with what is stored here. A monitoring tool
    # puts the same caution plainly: a row "disappearing from a result
    # list never becomes AD_BECAME_INACTIVE".
    return None


def evaluate_for_recipients(condition: CountCondition, counts: dict,
                            store) -> int:
    """Tells each recipient what their own count did. Returns how many.

    `counts` IS {user_id: count}, already evaluated as each person.
    This function does not search -- it compares -- so the caller
    decides who is asked and with whose authority, which is where that
    decision belongs.
    """
    told = 0
    for user_id, current in counts.items():
        previous = store.last_count(condition.key, user_id)
        summary = _verdict(condition, previous, current)

        # RECORDED WHETHER OR NOT ANYTHING WAS SENT. A count that moved
        # without making news still moved, and the next evaluation
        # compares against where it actually is.
        store.record_count(condition.key, user_id, current)

        if summary is None:
            continue
        if store.already_notified(condition.key, user_id, summary):
            continue
        if store.notify(user_id, "count_condition", summary):
            store.record_notified(condition.key, user_id, summary)
            told += 1
    return told
