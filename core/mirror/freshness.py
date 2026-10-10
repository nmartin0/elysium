"""How current an object type should be, and whether it is.

THE RULE EVERY PRECEDENT CONVERGES ON, and DEV_UI.md 16.6 records the
reading: freshness is derived from the DECISION THE DATA FEEDS, not
from what the pipeline can manage -- "a freshness number without a
threshold is trivia". The published tiers are by consequence: hours
for things feeding live action, daily for reporting, weekly for
anything read monthly.

TWO WINDOWS, NOT ONE. Dagster declares a fail_window and a shorter
warn_window; dbt declares warn_after and error_after; Datadog's
example for a critical table is 6 hours to alert and 4 to warn. The
wider practice agrees that "it is more practical to set two tiers
rather than a single threshold" -- warn first, then block or
explicitly propagate the stale state.

AND ANCHOR TO THE CADENCE, not to a number from nowhere. The
deployment declares ONE number, its expected sync interval, and every
threshold is a multiple of it. An operator who moves from nightly to
hourly changes that number and every threshold follows.

  warn at 1.1 x interval   (26 hours on a nightly deployment)
  fail at 2.1 x interval   (50 hours)

WARN IS ONE LATE RUN; FAIL IS TWO CONSECUTIVE MISSES. A run that slips
by an hour is not an incident and a channel that says it is becomes a
channel nobody reads; two missed nights is. It also keeps the
deployment's existing 25-hour judgement almost exactly.

MEASURED FROM THE PUBLICATION, per object type. Silver records when
the source was READ and gold records when a publication was MADE, and
a source read hourly but published daily is a day stale to a reader.
No source-side number catches that.

WHAT THIS DELIBERATELY DOES NOT TOUCH. `health_condition.STALE_AFTER`
measures the SOURCE-READ clock per silo table and is left exactly as
it is. It answers a different question -- "did the sync run?" rather
than "is what I am reading current?" -- and the write overlay is
bounded by that same source-read time. Conflating the two would
silently widen or narrow that window, which is the bug patch 335
closed.

YOUR OWN WRITES ARE NEVER STALE, which narrows the question further
than it first looks. The overlay shows applied changes immediately
whatever the sync did, so this governs only changes made in the
SOURCE systems by other people or other software.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# ONE NUMBER THE DEPLOYMENT DECLARES, and everything derives from it.
#
# TWENTY-FOUR HOURS BY DEFAULT because INSTALL.md leaves scheduling to
# the operator and nightly is what an unattended on-prem deployment
# does. A deployment that syncs hourly says so once.
DEFAULT_SYNC_INTERVAL_HOURS = 24.0

# ONE LATE RUN, AND TWO CONSECUTIVE MISSES.
WARN_MULTIPLE = 1.1
FAIL_MULTIPLE = 2.1

# THE VERDICTS. Five, not three: "never published" and "exempt" are
# not points on the same scale as the other three, and collapsing
# either into them loses the thing a reader needs. A type that has
# never published is not stale, it is absent -- reads of it FAIL --
# and a type that is exempt is not fresh, it is not being judged.
FRESH = "fresh"
WARNING = "warn"
FAILING = "fail"
NEVER = "never"
EXEMPT = "exempt"

# THE KEYS A PER-TYPE FRESHNESS BLOCK MAY CARRY.
#
# REFUSED RATHER THAN IGNORED, following the declared-triggers
# precedent for the same reason it gives: a misspelt `warn_after_hour`
# silently ignored would leave a type judged by the deployment default
# while its author believed otherwise, and nothing would ever say so.
_KEYS = frozenset({"warn_after_hours", "fail_after_hours", "exempt"})


@dataclass(frozen=True)
class FreshnessTarget:
    """How current one object type is expected to be."""

    warn_after: timedelta
    fail_after: timedelta
    # REFERENCE DATA MAY DECLARE ITSELF EXEMPT. A type that genuinely
    # changes quarterly generates nothing but false alarms otherwise,
    # and a channel with false alarms in it is a channel nobody reads.
    exempt: bool = False


def sync_interval(config: dict) -> timedelta:
    """The deployment's declared expected sync interval."""
    declared = (config.get("freshness") or {}).get("sync_interval_hours")
    if declared is None:
        return timedelta(hours=DEFAULT_SYNC_INTERVAL_HOURS)
    return timedelta(hours=_hours("config.yaml freshness: sync_interval_hours",
                                   declared))


def default_target(interval: timedelta) -> FreshnessTarget:
    """What a type gets when it declares nothing of its own."""
    return FreshnessTarget(
        warn_after=interval * WARN_MULTIPLE,
        fail_after=interval * FAIL_MULTIPLE,
    )


def targets_for(config: dict, object_types: dict) -> dict[str, FreshnessTarget]:
    """Every declared type's target, defaulted and validated.

    RAISES ON A CONTRADICTORY DECLARATION rather than resolving it,
    which is this deployment's standing bargain: a configuration error
    is refused at load instead of discovered in production.
    """
    interval = sync_interval(config)
    fallback = default_target(interval)
    targets: dict[str, FreshnessTarget] = {}
    for object_type, type_def in (object_types or {}).items():
        declared = (type_def or {}).get("freshness")
        if declared is None:
            targets[object_type] = fallback
            continue
        targets[object_type] = _declared_target(object_type, declared, interval)
    return targets


def verdict(published_at: str | None, target: FreshnessTarget,
            now: datetime | None = None) -> str:
    """What to say about one type, given when it last published.

    NEVER-PUBLISHED IS NOT STALE. A type with no publication is one
    whose reads fail outright -- the server says so at startup and
    raises on read -- and calling that "very stale" would put it on a
    scale it is not on.
    """
    if target.exempt:
        return EXEMPT
    if not published_at:
        return NEVER
    try:
        when = datetime.fromisoformat(published_at)
    except ValueError:
        # UNREADABLE IS NOT A VERDICT. A timestamp this cannot parse is
        # a fact about the record rather than about the data's age, and
        # guessing either way would be worse than saying nothing.
        return NEVER
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    age = (now or datetime.now(UTC)) - when
    if age >= target.fail_after:
        return FAILING
    if age >= target.warn_after:
        return WARNING
    return FRESH


def _declared_target(object_type: str, declared,
                     interval: timedelta) -> FreshnessTarget:
    where = f"Object type {object_type!r}: freshness"
    if not isinstance(declared, dict):
        raise ValueError(f"{where} must be a block of settings, not {declared!r}.")

    unknown = sorted(set(declared) - _KEYS)
    if unknown:
        raise ValueError(f"{where} has unknown key(s) {unknown}; "
                         f"known: {sorted(_KEYS)}.")

    exempt = declared.get("exempt", False)
    if not isinstance(exempt, bool):
        raise ValueError(f"{where}: exempt must be true or false, got {exempt!r}.")

    warn_declared = declared.get("warn_after_hours")
    fail_declared = declared.get("fail_after_hours")

    if exempt:
        # EXEMPT AND A TARGET TOGETHER IS A CONTRADICTION, not a
        # precedence question. Somebody wrote both because they meant
        # one of them, and picking for them would mean a type is
        # judged, or not, by a rule nobody stated.
        if warn_declared is not None or fail_declared is not None:
            raise ValueError(
                f"{where} declares exempt AND a threshold. A type is either "
                f"judged on its age or it is not -- remove one.")
        return FreshnessTarget(warn_after=interval * WARN_MULTIPLE,
                               fail_after=interval * FAIL_MULTIPLE, exempt=True)

    # BOTH OR NEITHER. One half declared would leave the other derived
    # from the deployment default, so `fail_after_hours: 6` on a nightly
    # deployment would silently pair with a warn of 26 -- a window that
    # warns eleven hours after it has already failed.
    if (warn_declared is None) != (fail_declared is None):
        raise ValueError(
            f"{where} declares only one of warn_after_hours and "
            f"fail_after_hours. Declare both, so the pair is a window "
            f"somebody chose rather than half a window and a default.")

    warn_after = timedelta(hours=_hours(f"{where}: warn_after_hours", warn_declared))
    fail_after = timedelta(hours=_hours(f"{where}: fail_after_hours", fail_declared))

    if fail_after <= warn_after:
        raise ValueError(
            f"{where}: fail_after_hours ({_as_hours(fail_after)}) must be "
            f"later than warn_after_hours ({_as_hours(warn_after)}). Warning "
            f"after failing is a warning nobody sees.")

    # A TARGET TIGHTER THAN THE SYNC INTERVAL IS REFUSED, NAMING BOTH
    # NUMBERS. A type declaring two hours on a nightly deployment is
    # not ambitious, it is guaranteed to alert forever -- which is a
    # configuration error, and this deployment refuses configuration
    # errors at load rather than discovering them in production.
    if warn_after < interval:
        raise ValueError(
            f"{where}: warn_after_hours is {_as_hours(warn_after)}, but this "
            f"deployment syncs every {_as_hours(interval)}. A target tighter "
            f"than the sync interval can never be met. Either raise the "
            f"target, or lower freshness.sync_interval_hours in config.yaml "
            f"to match how often the sync actually runs.")

    return FreshnessTarget(warn_after=warn_after, fail_after=fail_after)


def _hours(where: str, declared) -> float:
    # bool IS AN int IN PYTHON, and `warn_after_hours: true` is a typo
    # that would otherwise mean one hour.
    if isinstance(declared, bool) or not isinstance(declared, int | float):
        raise ValueError(f"{where} must be a number of hours, got {declared!r}.")
    if declared <= 0:
        raise ValueError(f"{where} must be more than zero hours, got {declared!r}.")
    return float(declared)


def _as_hours(span: timedelta) -> str:
    hours = span.total_seconds() / 3600
    whole = int(hours)
    return f"{whole} hours" if hours == whole else f"{hours:.1f} hours"
