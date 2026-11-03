"""The timer service's handler for deprecation dates (core/ontology/deprecation_alerts.py).

Here rather than in core because it needs the running server's stores: the
accounts, and where notifications are kept. It runs on the timer service
(api/timer_service.py) once a day and at start-up if one is due -- no loop
of its own.
"""

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

KIND = "deprecation_dates"
KEY = "daily"
#: Daily is enough for a date measured in days; the dedupe key makes a
#: more frequent look harmless, not useful.
EVERY_MINUTES = 24 * 60


def arm(app) -> None:
    """Sets the daily check if it is not already set (a restart must not
    move it). Never raises: a check that could not be set costs the
    alert, logged, not the server."""
    try:
        from core.timers import TimerStore

        timers = TimerStore(Path(app.state.runtime_paths.data_dir))
        if timers.get(KIND, KEY) is None:
            timers.set(KIND, KEY, time.time(), repeat={"every_minutes": EVERY_MINUTES})
    except Exception:  # noqa: BLE001
        logger.warning("could not set the deprecation date check", exc_info=True)


def deprecation_timer(app, firing) -> None:
    from core.intermediate_layer.rbac import authorize
    from core.notifications import NotificationStore
    from core.ontology.deprecation_alerts import MANAGE_PERMISSION, findings, send
    from core.ontology.used_by import used_by_field, used_by_link, used_by_type
    from core.user_directory import UserDirectory

    data_dir = Path(app.state.runtime_paths.data_dir)
    config = app.state.generation.config
    today = datetime.fromtimestamp(firing.now, UTC).date()
    found = findings(config.schema, today, config.deprecation_lead_days)
    if not found:
        return
    for item in found:
        if item.stage == "problem":
            logger.warning("deprecation: %s has remove_after %r, which is not a date", item.label, item.raw)

    directory = UserDirectory(data_dir / "credentials.db", config.roles)
    recipients = []
    for account in directory.list_users():
        if account["disabled"]:
            continue
        try:
            if authorize(directory.get_user_record(account["username"]), config.roles, MANAGE_PERMISSION):
                recipients.append(account["username"])
        except Exception:  # noqa: BLE001 - an account that cannot be read is not told
            continue
    if not recipients:
        logger.warning("deprecation: %d item(s) need attention and nobody has %s", len(found),
                       MANAGE_PERMISSION)
        return

    shared = (config.schema, config.roles, config.action_types, config.declared_triggers)

    def referrers(item) -> "int | None":
        try:
            if item.kind == "type":
                return len(used_by_type(*shared, item.name))
            if item.kind == "link type":
                return len(used_by_link(*shared, item.name))
            owner, field = item.name.split(".", 1)
            return len(used_by_field(*shared, owner, field))
        except Exception:  # noqa: BLE001 - said as "could not be worked out", not guessed
            logger.warning("deprecation: could not count what names %s", item.label, exc_info=True)
            return None

    send(found, recipients, NotificationStore(data_dir / "notifications.db"), referrers)
