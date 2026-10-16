"""One evaluation of every trigger, each as its owner (moved here 16 October).

TWO CALLERS, ONE PATH. The sync runs it when the data changed
(scripts/run_sync.py), and the server's clock runs it between syncs
(api/trigger_clock.py) -- because a condition can change without a
sync: a change approved in Elysium is read at once, before the next
sync copies it from the source, and "in the last 30 days" moves at
midnight UTC on its own. Two copies of this would be two places for
owner resolution, recipients or the write side to drift, so it moved
out of the sync script rather than being copied.

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


def run_triggers(config: Any, data_dir: Path, mediator: Any,
                 write_side: "Callable[[], tuple[Any, Any, Any]]") -> int:
    """Evaluates every enabled trigger -- made in the product and
    declared in config.yaml -- and returns how many fired.

    `write_side()` returns (mediator, write mediator, pending-write
    store) and is called ONLY if some trigger can propose an action: a
    deployment whose triggers only notify builds no write path at all.
    The mediator it returns replaces `mediator`, so a proposal and the
    count it rests on are read the same way.
    """
    from core.count_condition import evaluate_one_trigger, evaluate_user_triggers
    from core.notifications import NotificationStore
    from core.saved_views import SavedViewStore
    from core.triggers import TriggerStore
    from core.user_directory import UserDirectory

    triggers = TriggerStore(data_dir / "triggers.db")
    # BOTH KINDS: made in the product, and declared in config.yaml.
    # They share owner resolution, the write mediator and the
    # evaluator -- a declared trigger is never a second code path.
    declared = list(config.declared_triggers)
    enabled = [*triggers.all_enabled(), *declared]
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
    fired = evaluate_user_triggers(
        mediator, triggers, SavedViewStore(data_dir / "saved_views.db"),
        notifications, owners, config.source_digest, write_mediator, pending_store,
    )
    # DECLARED TRIGGERS carry their view inline, so they skip the
    # saved-view lookup and go straight to the shared path.
    for trigger in declared:
        fired += evaluate_one_trigger(
            trigger, trigger.view, mediator, notifications, owners,
            config.source_digest, write_mediator, pending_store,
        )
    return fired
