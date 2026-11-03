"""Telling the people who manage the deployment that a `remove_after` date is near.

core/ontology/deprecation.py lets a deprecated type, field or link type
carry `remove_after: 2027-03-31` and promises that "the operator is told it
has arrived". Until this file nothing told anyone. This is that telling,
and nothing more.

THE ALERT ONLY INFORMS. Nothing is removed, hidden or changed on that day
or any other: removal stays a person's action on the Schema screen
(core/ontology/removal.py), which is still refused while anything names
the thing.

TWO STAGES, ONE NOTICE EACH, PER PERSON:

  lead     the date is within `deprecation_lead_days` (config.yaml, default
           DEFAULT_LEAD_DAYS) and has not arrived;
  overdue  the date is today or past and the item is still in the
           configuration. "Still exists" is simply that it is evaluated
           from the loaded configuration: a removed item is not there.

A third line, `problem`, is a `remove_after` that is not a date. The loader
refuses one (deprecation._check_date), so this is for a configuration that
reached here some other way; it is still said, to the same people, rather
than skipped -- an alert that quietly ignores what it cannot read is the
failure this exists to prevent.

NOT ONCE PER LOOK. Every notice is written with a dedupe key naming the
item, the stage, the date and the person (core/notifications.py: a second
write with a key is a no-op), so the daily evaluation, a restart, a second
worker and a reload all leave one notice. Moving the date gives a new key
and so a new notice, which is right: the plan changed. An item already
overdue when first seen gets the overdue notice only, not a lead one as
well.

WHO: everyone with manage:deployment, the permission that gates editing
the ontology and the configuration (api/routes.py), evaluated for each
active account when the check runs.

WHAT IT SAYS ABOUT USE is the number of places in the CONFIGURATION that
still name the thing (core/ontology/used_by.py) and that this count leaves
out saved views, frozen sets, recipes, proposals and notes -- the same
limit the Used by panel states. It lists no names: a name in a notice
would reach people who may not be allowed to discover it, and the panel
already shows each person only what they may see.

ACTIONS are not covered: action types have no status or deprecation block
(core/ontology/action_types.py), so there is no date to alert on.

Dates are compared as UTC calendar days.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from elysium.core.ontology.deprecation import DEPRECATION

#: How many days before `remove_after` the first notice is sent, when
#: config.yaml does not say (`deprecation_lead_days`). A month is long
#: enough to plan a removal around and short enough to be remembered.
DEFAULT_LEAD_DAYS = 30
MAX_LEAD_DAYS = 365

NOTICE_KIND = "deprecation"
LEAD, OVERDUE, PROBLEM = "lead", "overdue", "problem"
MANAGE_PERMISSION = "manage:deployment"


def lead_days_from(declared) -> int:
    """config.yaml's `deprecation_lead_days`: a whole number of days from 0
    (no early notice, only the overdue one) to MAX_LEAD_DAYS; absent means
    DEFAULT_LEAD_DAYS."""
    if declared is None:
        return DEFAULT_LEAD_DAYS
    if isinstance(declared, bool) or not isinstance(declared, int) or not 0 <= declared <= MAX_LEAD_DAYS:
        raise ValueError(f"config.yaml deprecation_lead_days must be a whole number of days from 0 to "
                         f"{MAX_LEAD_DAYS}, got {declared!r}.")
    return declared


@dataclass(frozen=True)
class Finding:
    """One thing to say about one deprecated item."""

    stage: str            # LEAD, OVERDUE or PROBLEM
    kind: str             # "type", "field" or "link type"
    name: str             # "Customer", "Customer.email", "CustomerTags"
    when: "date | None"   # None for PROBLEM
    raw: object           # remove_after exactly as written
    days: int             # days until (LEAD) or since (OVERDUE) the date; 0 for PROBLEM
    reason: "str | None"
    replaced_by: "str | None"

    @property
    def label(self) -> str:
        return f"{self.kind} {self.name}"

    @property
    def key(self) -> str:
        return f"deprecation/{self.stage}/{self.kind}:{self.name}/{self.when or repr(self.raw)}"


def _items(schema: Mapping):
    """(kind, name, deprecation block) for every type, stored field and
    link type that carries a block with a `remove_after`. A link is on both
    of its end fields; it is yielded once."""
    seen_links: set = set()
    for type_name, type_def in sorted(schema.items()):
        yield "type", type_name, type_def.get(DEPRECATION)
        for field_name, field in sorted((type_def.get("fields") or {}).items()):
            if field.get("type") == "link":
                link = field.get("link_type")
                if link not in seen_links:
                    seen_links.add(link)
                    yield "link type", link, field.get(DEPRECATION)
            else:
                yield "field", f"{type_name}.{field_name}", field.get(DEPRECATION)


def findings(schema: Mapping, today: date, lead_days: int) -> list[Finding]:
    """What there is to say today, for every item that has a date."""
    found: list[Finding] = []
    for kind, name, block in _items(schema):
        if not isinstance(block, Mapping) or block.get("remove_after") is None:
            continue
        raw = block["remove_after"]
        reason, replaced_by = block.get("reason"), block.get("replaced_by")
        when = _as_date(raw)
        if when is None:
            found.append(Finding(PROBLEM, kind, name, None, raw, 0, reason, replaced_by))
        elif when <= today:
            found.append(Finding(OVERDUE, kind, name, when, raw, (today - when).days, reason, replaced_by))
        elif when - today <= timedelta(days=lead_days):
            found.append(Finding(LEAD, kind, name, when, raw, (when - today).days, reason, replaced_by))
    return found


def _as_date(raw) -> "date | None":
    """YAML reads an unquoted 2027-03-31 as a date; a quoted one is text. A
    datetime is not accepted (the loader refuses it too)."""
    if isinstance(raw, date) and not hasattr(raw, "hour"):
        return raw
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def _days(count: int) -> str:
    return "1 day" if count == 1 else f"{count} days"


def words(finding: Finding, referrers: "int | None") -> tuple[str, str]:
    """(summary, detail) of the notice. `referrers` is how many places in
    the configuration still name the item, or None when that could not be
    worked out -- said, not guessed."""
    label = finding.label
    if finding.stage == PROBLEM:
        return (f"The removal date of {label} is not a date",
                f"{label} is deprecated with remove_after {finding.raw!r}, which cannot be read as a "
                f"date like 2027-03-31, so no alert can be made for it. Correct it in Schema "
                f"(deprecate the item again with a valid date).")
    if finding.stage == LEAD:
        summary = (f"{label} is due for removal on {finding.when} "
                   f"({'today' if finding.days == 0 else 'in ' + _days(finding.days)})")
        timing = f"Its remove_after date is {finding.when}, {_days(finding.days)} from now."
    else:
        summary = f"{label} was due for removal on {finding.when} and is still there"
        timing = (f"Its remove_after date, {finding.when}, "
                  f"{'is today' if finding.days == 0 else 'passed ' + _days(finding.days) + ' ago'}, "
                  f"and it is still in the configuration.")
    parts = [f"{label[0].upper()}{label[1:]} is deprecated"
             + (f" ({finding.reason})" if finding.reason else "") + ". " + timing]
    if finding.replaced_by:
        parts.append(f"Its replacement is {finding.replaced_by}.")
    if referrers is None:
        parts.append("Whether anything still names it could not be worked out.")
    elif referrers == 0:
        parts.append("Nothing in the configuration names it, so it can be removed.")
    else:
        parts.append(f"{referrers} place{'s' if referrers != 1 else ''} in the configuration still name it "
                     f"(saved views, frozen sets, recipes, proposals and notes are not counted).")
    parts.append("Nothing is removed automatically. To act, open Schema, find the item and use "
                 "Used by, then Remove when it is ready; to change the date, deprecate it again "
                 "with a new one.")
    return summary, " ".join(parts)


def send(found: list[Finding], recipients: list[str], store, referrers: Callable[[Finding], "int | None"]) -> None:
    """Writes each finding's notice to each recipient. The dedupe key makes
    a repeat a no-op (NotificationStore.notify), so this may run as often
    as it likes."""
    for finding in found:
        summary, detail = words(finding, None if finding.stage == PROBLEM else referrers(finding))
        for user_id in recipients:
            store.notify(user_id, NOTICE_KIND, summary, detail, dedupe_key=f"{finding.key}/{user_id}")
