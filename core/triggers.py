"""Triggers somebody made, rather than a deployment declared.

NOTIFY ONLY, AND NO COLUMN FOR ANYTHING ELSE. `propose_action_effect`
exists in the machinery and is deliberately not offered here: a
trigger that proposes writes unattended deserves its own
conversation.

A first version kept an `effect` column defaulting to 'notify', to
make the second effect a smaller migration. That is speculation with
a schema attached -- the column would have been stored, never read,
and its default relied on. Adding it when a second effect exists is
one migration either way.

OWNED BY THEIR CREATOR, AND RUN AS THEM. That is what makes a
UI-created trigger safe to offer without a new grant: its effects are
attenuated by construction. Alice's trigger proposes writes Alice
could already propose, and counts objects Alice could already count.

RECIPIENTS ARE THE OWNER, AND ONLY THE OWNER, for now. If somebody
could name another person, they would gain a capability they do not
otherwise have -- sending notifications somebody did not ask for. Not
a leak, since a notification carries only its recipient's own count,
but a capability, and one worth deciding separately from this.

Mirror health is the counter-example and stays as it is: a BUILT-IN
that notifies whoever holds `manage:deployment`, declared in code
rather than by a person.

NOT WHEN IT RUNS. A trigger says what to watch and what to do; the
sync decides when to look, because that is when the data changed.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.sqlite_connection import add_column_if_missing, connection_with_schema

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS triggers (
    trigger_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    view_id TEXT NOT NULL,
    above INTEGER,
    gained INTEGER,
    fell INTEGER,
    -- AN ACTION TO PROPOSE when the condition fires, or NULL for a
    -- trigger that only notifies.
    action_type TEXT,
    -- Which of that action's parameters receives the matched objects.
    action_parameter TEXT,
    -- The action's OTHER parameters, fixed when the trigger was made.
    action_values TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
-- Two reads: "mine, to manage" and "every enabled one, to evaluate".
CREATE INDEX IF NOT EXISTS triggers_owner ON triggers (owner_user_id);
CREATE INDEX IF NOT EXISTS triggers_enabled ON triggers (enabled);
"""


@dataclass(frozen=True)
class Trigger:
    trigger_id: str
    owner_user_id: str
    name: str
    view_id: str
    above: int | None
    gained: int | None
    fell: int | None
    enabled: bool
    created_at: str
    action_type: str | None = None
    action_parameter: str | None = None
    action_values: dict | None = None

    @property
    def condition_key(self) -> str:
        """What the notification state is keyed by.

        THE TRIGGER'S OWN ID, so editing a threshold does not inherit
        the old one's history -- a trigger that fired at 10 and now
        fires at 100 should take a fresh baseline rather than compare
        against counts measured under a different question.
        """
        # A SLASH, NOT A COLON. The grant-vocabulary test reads
        # `verb:subject` anywhere in the code as a permission being
        # asked for, and "trigger:" tripped it: "a deployment cannot
        # write them, so those checks can never pass".
        #
        # The test is right to be that blunt -- an invented verb is
        # a check that silently never passes -- so the key avoids the
        # shape rather than the test being loosened.
        return f"trigger/{self.trigger_id}"


class TriggerStore:
    """Triggers people made, with their owners."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        # MIGRATED, so a triggers.db made before action effects keeps
        # its triggers rather than losing every one to "no such column"
        # -- the saved-views bug this helper was written after.
        return connection_with_schema(
            self._db_path, SCHEMA,
            migrations=(
                add_column_if_missing("triggers", "action_type", "TEXT"),
                add_column_if_missing("triggers", "action_parameter", "TEXT"),
                add_column_if_missing(
                    "triggers", "action_values", "TEXT NOT NULL DEFAULT '{}'",
                ),
            ),
        )

    def create(self, owner_user_id: str, name: str, view_id: str,
               above: int | None = None, gained: int | None = None,
               fell: int | None = None, action_type: str | None = None,
               action_parameter: str | None = None,
               action_values: dict | None = None) -> str | None:
        """Makes one. Returns its id, or None if it could not be made."""
        trigger_id = str(uuid.uuid4())
        try:
            with self._connection() as conn:
                conn.execute(
                    "INSERT INTO triggers (trigger_id, owner_user_id, name, "
                    "view_id, above, gained, fell, action_type, "
                    "action_parameter, action_values, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (trigger_id, owner_user_id, name, view_id, above, gained,
                     fell, action_type, action_parameter,
                     json.dumps(action_values or {}),
                     datetime.now(UTC).isoformat()),
                )
                conn.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("could not create a trigger for %s: %s",
                           owner_user_id, e)
            return None
        return trigger_id

    def for_owner(self, owner_user_id: str) -> list[Trigger]:
        """One person's triggers. Scoped in the query."""
        return self._query(
            "SELECT * FROM triggers WHERE owner_user_id = ? "
            "ORDER BY created_at DESC",
            (owner_user_id,),
        )

    def all_enabled(self) -> list[Trigger]:
        """Every enabled trigger, for the evaluator.

        FOR THE SCHEDULER, which has no user. Each trigger carries its
        OWNER, and the evaluator runs it as them -- so authority comes
        from the row rather than from whoever happens to be calling.

        NEVER CALL THIS TO SERVE A REQUEST. `for_owner` is the
        request-side call, and it scopes in SQL.
        """
        return self._query("SELECT * FROM triggers WHERE enabled = 1", ())

    def set_enabled(self, owner_user_id: str, trigger_id: str,
                    enabled: bool) -> bool:
        """Turns one on or off, if it belongs to this person.

        ENABLED RATHER THAN DELETED is the common case: somebody
        silencing a noisy trigger usually wants it back.
        """
        return self._write(
            "UPDATE triggers SET enabled = ? WHERE trigger_id = ? "
            "AND owner_user_id = ?",
            (1 if enabled else 0, trigger_id, owner_user_id),
        )

    def delete(self, owner_user_id: str, trigger_id: str) -> bool:
        """THE OWNER IS IN THE WHERE CLAUSE, so deleting somebody
        else's matches no row -- the same answer as "no such
        trigger"."""
        return self._write(
            "DELETE FROM triggers WHERE trigger_id = ? AND owner_user_id = ?",
            (trigger_id, owner_user_id),
        )

    def _query(self, sql: str, params: tuple) -> list[Trigger]:
        try:
            with self._connection() as conn:
                rows = conn.execute(sql, params).fetchall()
        except Exception as e:  # noqa: BLE001
            logger.warning("could not read triggers: %s", e)
            return []
        triggers = []
        for row in rows:
            try:
                values = json.loads(row["action_values"] or "{}")
            except (TypeError, json.JSONDecodeError):
                values = {}
            triggers.append(Trigger(
                row["trigger_id"], row["owner_user_id"], row["name"],
                row["view_id"], row["above"], row["gained"],
                row["fell"], bool(row["enabled"]), row["created_at"],
                row["action_type"], row["action_parameter"], values,
            ))
        return triggers

    def _write(self, sql: str, params: tuple) -> bool:
        try:
            with self._connection() as conn:
                cursor = conn.execute(sql, params)
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:  # noqa: BLE001
            logger.warning("could not write a trigger: %s", e)
            return False


def describe(trigger: Trigger) -> str:
    """What a trigger watches for, in a person's words.

    THIS BECOMES THE NOTIFICATION'S TEXT, so it must read as a
    sentence somebody wrote rather than as a row -- and it is the only
    thing a recipient sees besides their own count.
    """
    if trigger.above is not None:
        return f"{trigger.name} above {trigger.above}"
    if trigger.gained is not None:
        return f"{trigger.name} gaining {trigger.gained} or more"
    if trigger.fell is not None:
        return f"{trigger.name} losing {trigger.fell} or more"
    return trigger.name


# PARAMETER TYPES THAT CAN RECEIVE THE OBJECTS A VIEW MATCHED.
_OBJECT_PARAMETERS = frozenset({"object_reference", "object_reference_list"})


def action_problem(action_types, view_object_type: str, action_type: str,
                   action_parameter: str | None, action_values: dict | None,
                   owner_may_execute: bool) -> str | None:
    """Why this action cannot be attached to this trigger, or None.

    CHECKED WHEN THE TRIGGER IS MADE, not when it fires. A trigger
    that could never propose would sit silently failing at 3am, with
    its creator long gone; refusing now puts the reason in front of the
    one person who can fix it.

    THE SAME GATES A PROPOSAL MEETS LATER, checked early rather than
    replaced: `propose_action` still runs every one of them at fire
    time, because the owner's grants and the action's definition can
    change after the trigger is made.

    Foundry's rule is the model: "the owner configuring an action must
    pass the submission criteria for that action". So the owner must
    hold `execute:` for it -- a trigger grants nothing its owner lacks.
    """
    definition = action_types.get(action_type)
    if definition is None:
        return f"No action type {action_type!r}."
    if not owner_may_execute:
        # THE SAME WORDS AS AN UNKNOWN ACTION would leak less, but the
        # owner can already see which actions exist in the Actions
        # menu, so naming the grant costs nothing and helps.
        return f"You cannot run {action_type!r} yourself, so a trigger cannot run it for you."
    if definition.get("automatable") is False:
        return f"{action_type!r} declares automatable: false, so a trigger may not propose it."

    parameters = definition.get("parameters") or {}
    target = parameters.get(action_parameter or "")
    if target is None:
        return f"{action_type!r} has no parameter {action_parameter!r}."
    if target.get("type") not in _OBJECT_PARAMETERS:
        return (
            f"{action_parameter!r} does not take objects, so it cannot receive "
            f"what this view matches."
        )
    if target.get("object_type") != view_object_type:
        return (
            f"{action_parameter!r} takes {target.get('object_type')} objects, "
            f"and this view matches {view_object_type}."
        )

    unknown = sorted(set(action_values or {}) - set(parameters))
    if unknown:
        return f"{action_type!r} has no parameter(s) {unknown}."
    if action_parameter in (action_values or {}):
        # THE MATCHED OBJECTS FILL THIS ONE. A fixed value as well
        # would be silently overwritten at fire time.
        return f"{action_parameter!r} is filled by the view's matches; do not also give it a value."
    return None

