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
    # FIRES WHEN IT LOSES AT LEAST THIS MANY. None disables it.
    #
    # SEPARATE FROM `gained` RATHER THAN A SIGNED THRESHOLD, because
    # the two are different questions: "work is piling up" and "work
    # is being cleared" want different words and often different
    # recipients.
    fell: int | None = None


def _verdict(condition: CountCondition, previous: int | None,
             current: int) -> str | None:
    """What to say about this count, or nothing.

    THE FIRST EVALUATION IS A BASELINE AND SAYS NOTHING HERE -- the
    caller sends a separate "now watching" notice, because silence is
    indistinguishable from a condition that never ran.

    Treating a missing previous count as zero would report every
    existing match as a gain, which is the flood a monitoring tool
    that hit it warns about: "the first successful run creates a
    baseline, never a flood of fake new ads".
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

    if condition.fell is not None and previous - current >= condition.fell:
        # SAFE ONLY BECAUSE THE CONFIGURATION IS PINNED. An object
        # leaving a filtered set may mean it changed, was deleted, or
        # that the READER'S GRANTS changed -- and the caller refuses to
        # compare across a configuration change, so the third is ruled
        # out before this runs.
        #
        # IT STILL SAYS "3 FEWER", NEVER "THESE THREE". Knowing which
        # needs last time's result set, which is exactly what is not
        # stored. A monitoring tool puts the residue plainly: a row
        # "disappearing from a result list never becomes
        # AD_BECAME_INACTIVE".
        return (
            f"{condition.description}: {previous - current} fewer than "
            f"last time ({previous} to {current})."
        )

    return None


def count_for_each(mediator, view, user_records: list) -> dict:
    """Runs one saved view as each person. Returns {user_id: count}.

    THE SAME QUERY, DIFFERENT AUTHORITY. `search_object` already takes
    a user, so evaluating a view as Alice and then as Bob is one
    existing function called with a different first argument -- through
    `check_access`, MAC and the audit log unchanged.

    THERE IS NO SECOND PERMISSION PATH TO GET WRONG, which matters
    more here than anywhere: this is the one place a condition touches
    somebody else's data.

    AND NO PRIVILEGED COUNT EXISTS. Nobody evaluates the view as an
    owner and filters; each number comes from its own search. So a
    recipient who can see nothing counts zero, rather than being told
    a number and shown none of it.

    A FAILURE COSTS ITS OWN RECIPIENT. One person's search raising --
    a silo unreachable for their partition, a grant mid-change --
    should not stop the others being told.
    """
    counts: dict = {}

    # A VIEW WHOSE TYPE IS GONE CANNOT BE EVALUATED FOR ANYBODY, and
    # `search_object` returns an EMPTY LIST rather than raising for an
    # unknown type -- deliberately, so a caller cannot tell "does not
    # exist" from "not authorized to discover".
    #
    # That is right for a search and wrong here: zero for everyone
    # would report every existing match as removed on the next
    # evaluation. Checked once, against the schema, before asking
    # anybody.
    if view.object_type not in mediator.schema:
        logger.warning(
            "view %r names object type %r, which the ontology no longer "
            "declares -- not evaluated",
            view.name, view.object_type,
        )
        return {}

    for user_record in user_records:
        try:
            # ONE HELPER, SHARED WITH THE ACTION EFFECT. A second copy
            # of this translation would be two places for a filter
            # shape to drift.
            matched = _matches_for(mediator, view, user_record)
        except Exception as e:  # noqa: BLE001 - see the docstring
            logger.warning(
                "could not evaluate view %r as %s: %s",
                view.name, user_record.user_id, e,
            )
            continue
        counts[user_record.user_id] = len(matched)
    return counts


def propose_action_effect(write_mediator, mediator, view, owner_record,
                          action_type_name: str, parameter_name: str,
                          extra_parameters: dict | None = None):
    """Proposes an action on whatever the view matches NOW.

    AS THE OWNER, which is Foundry's split and the one this file
    already states: "action effects execute AS the owner. Submission
    criteria are evaluated against the owner; the audit log records
    the owner." A notification is evaluated per RECIPIENT; an action
    is not, because an action is a write and a write has one author.

    RE-RUN RATHER THAN REMEMBERED, and that is the resolution of a
    tension this design created. Conditions compare COUNTS -- no
    alerting system worth copying stores last time's result set -- so
    when one fires, nothing knows WHICH objects matched.

    So the effect asks again. The set may differ slightly from the one
    that tripped the count, and that is the RIGHT answer rather than a
    compromise: an action should operate on what matches when it runs,
    not on what matched when somebody noticed.

    IT PROPOSES, IT DOES NOT EXECUTE. The pending write lands in the
    approvals queue like any other, with `origin="automation"` so
    whoever reviews it can tell a condition proposed it. An action
    declaring `automatable: false` refuses here, before the queue.

    RETURNS THE PendingWrite, or None if nothing matched. An action
    proposed over an empty set is a decision somebody has to read and
    dismiss.
    """
    matched = _matches_for(mediator, view, owner_record)
    if not matched:
        return None

    parameters = {parameter_name: matched, **(extra_parameters or {})}
    return write_mediator.propose_action(
        owner_record, action_type_name, parameters, origin="automation",
    )


def _matches_for(mediator, view, user_record) -> list:
    """The ids one saved view matches, for one person."""
    from core.filters import FieldFilter

    conditions = [
        FieldFilter(
            field=condition["field"],
            operator=condition["operator"],
            value=condition.get("value"),
        )
        for condition in view.conditions
    ]
    if view.query_text:
        return mediator.search_object_free_text(
            user_record, view.object_type, view.query_text,
            conditions=conditions,
        )
    return mediator.search_object(user_record, view.object_type, conditions)


def evaluate_for_recipients(condition: CountCondition, counts: dict,
                            store, config_digest: str | None = None) -> int:
    """Tells each recipient what their own count did. Returns how many.

    `counts` IS {user_id: count}, already evaluated as each person.
    This function does not search -- it compares -- so the caller
    decides who is asked and with whose authority, which is where that
    decision belongs.

    `config_digest` PINS WHAT THE COUNT MEANS. A count is a fact about
    what ONE PERSON could see, and what a person can see is decided by
    policy.yaml, which the digest covers. Two counts taken under
    different configurations are not comparable: somebody granted a
    new region sees more without anything being added, and somebody
    who lost one sees fewer without anything being removed.
    """
    told = 0
    for user_id, current in counts.items():
        previous, previous_digest = store.last_measurement(
            condition.key, user_id,
        )

        # A CHANGED CONFIGURATION RESETS THE BASELINE. Not a special
        # case for falling counts -- a grant change moves a count in
        # EITHER direction, and comparing across one reports the
        # change in authority as a change in the data.
        configuration_changed = (
            previous_digest is not None
            and config_digest is not None
            and previous_digest != config_digest
        )

        summary = (
            None if configuration_changed
            else _verdict(condition, previous, current)
        )

        first_time = previous is None
        # RECORDED WHETHER OR NOT ANYTHING WAS SENT. A count that moved
        # without making news still moved, and the next evaluation
        # compares against where it actually is.
        store.record_count(condition.key, user_id, current, config_digest)

        if first_time:
            # SILENCE IS INDISTINGUISHABLE FROM A CONDITION THAT NEVER
            # RAN. Somebody who declares one and hears nothing cannot
            # tell "watching, nothing to report" from "broken".
            #
            # NOT AN ALERT, and not suppressed by the repeat check --
            # it happens once per person per condition by
            # construction, because there is no second first time.
            store.notify(
                user_id, "count_condition_watching",
                f"{condition.description}: now watching. Currently "
                f"{current}.",
            )
            continue

        if summary is None:
            continue
        if store.already_notified(condition.key, user_id, summary):
            continue
        if store.notify(user_id, "count_condition", summary):
            store.record_notified(condition.key, user_id, summary)
            told += 1
    return told
