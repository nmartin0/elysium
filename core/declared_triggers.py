"""Triggers a deployment declares in config.yaml.

NOT MORE POWERFUL THAN ONE A PERSON MAKES, and that is the precedent
followed. Foundry's analogue of "declared centrally" is an automation
owned by a SERVICE USER rather than a person -- for "team continuity:
automations continue running when team members leave" -- and it runs
with "the service user's permissions". Its own grants; nothing extra.

SO A DECLARED TRIGGER NAMES AN OWNER, exactly like a made one, and
runs as that owner through the same code path. The owner may be a
person or a service account created for the purpose -- but it is a
REAL account in credentials.db, never a synthesised one, which is what
keeps the grant algebra's "nothing synthesises a UserRecord" true.

THE QUERY IS WRITTEN INLINE. A made trigger references a saved view by
id, and ids are generated at runtime; configuration cannot know one.

ONE DIFFERENCE, AND IT IS ABOUT SEEING, NOT DOING. Anybody writing
config.yaml can read policy.yaml beside it, so a declared trigger may
name any EXISTING role as a recipient. A person making a trigger in the
product may name only roles they could already learn exist.

WHAT IS CHECKED WHERE. Everything about the trigger's own SHAPE is
checked at load, so a mistake stops the deployment starting rather
than surfacing at 3am. Whether the OWNER exists and may run the action
is checked when it fires, because accounts live in a database that
changes without the configuration changing.
"""

from dataclasses import dataclass, field

from core.saved_views import SavedView
from core.triggers import action_problem

# THE KEYS A DECLARED TRIGGER MAY CARRY. Anything else is refused: a
# misspelt `recipient_role` silently ignored would notify nobody and
# read as a quiet trigger.
_KEYS = frozenset({
    "name", "owner", "object_type", "query_text", "conditions",
    "above", "gained", "fell", "recipient_roles", "action",
})
_ACTION_KEYS = frozenset({"type", "parameter", "values"})
_THRESHOLDS = ("above", "gained", "fell")


@dataclass(frozen=True)
class DeclaredTrigger:
    """A trigger from config.yaml, shaped like a made one.

    THE SAME ATTRIBUTE NAMES as `core.triggers.Trigger`, so the shared
    evaluator takes either without knowing which it has.
    """

    name: str
    owner_user_id: str
    view: SavedView
    above: int | None = None
    gained: int | None = None
    fell: int | None = None
    action_type: str | None = None
    action_parameter: str | None = None
    action_values: dict = field(default_factory=dict)
    recipient_roles: tuple = ()
    enabled: bool = True

    @property
    def trigger_id(self) -> str:
        return f"declared/{self.name}"

    @property
    def view_id(self) -> str:
        return self.view.view_id

    @property
    def condition_key(self) -> str:
        """Keyed by NAME, because a declared trigger has no stored id.

        A SLASH, not a colon -- the grant-vocabulary test reads
        `verb:subject` anywhere in the code as a permission asked for.

        EDITING ONE IN config.yaml RESETS ITS BASELINE anyway, through
        the configuration digest: a count taken under an older
        definition answers a different question.
        """
        return f"declared/{self.name}"


def load_declared_triggers(raw, object_types, action_types,
                           roles) -> tuple[DeclaredTrigger, ...]:
    """Parses and validates config.yaml's `triggers:` block.

    RAISES ValueError naming the trigger and the problem, so a mistake
    stops the deployment starting -- where the person who made it is
    looking -- rather than surfacing when the trigger was meant to
    fire.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("config.yaml: `triggers` must be a list.")

    seen: set[str] = set()
    parsed = []
    for index, entry in enumerate(raw):
        where = f"config.yaml: triggers[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be a mapping.")

        unknown = sorted(set(entry) - _KEYS)
        if unknown:
            raise ValueError(f"{where} has unknown key(s) {unknown}.")

        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{where} needs a non-empty `name`.")
        where = f"config.yaml: trigger {name!r}"
        if name in seen:
            # THE NAME IS THE KEY for its notification state, so two
            # of one name would share -- and corrupt -- one baseline.
            raise ValueError(f"{where} is declared twice.")
        seen.add(name)

        owner = entry.get("owner")
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError(
                f"{where} needs an `owner` -- a real account, possibly a "
                f"service account created for it. It runs as that owner."
            )

        object_type = entry.get("object_type")
        if not isinstance(object_type, str) or object_type not in object_types:
            raise ValueError(f"{where}: no object type {object_type!r}.")

        given = [key for key in _THRESHOLDS if entry.get(key) is not None]
        if len(given) != 1:
            raise ValueError(
                f"{where} needs exactly one of above, gained or fell."
            )
        threshold = entry[given[0]]
        if not isinstance(threshold, int) or isinstance(threshold, bool) \
                or threshold < 0:
            raise ValueError(f"{where}: {given[0]} must be a whole number.")

        recipient_roles = entry.get("recipient_roles") or []
        for role in recipient_roles:
            if role not in roles:
                raise ValueError(f"{where}: no role {role!r}.")

        action = entry.get("action")
        action_type = action_parameter = None
        action_values: dict = {}
        if action is not None:
            unknown = sorted(set(action) - _ACTION_KEYS)
            if unknown:
                raise ValueError(f"{where}: action has unknown key(s) {unknown}.")
            action_type = action.get("type")
            action_parameter = action.get("parameter")
            action_values = action.get("values") or {}
            # THE OWNER'S GRANT IS CHECKED WHEN IT FIRES, not here:
            # accounts live in a database that changes without the
            # configuration changing. Everything about the ACTION's
            # own shape is checked now.
            problem = action_problem(
                action_types, object_type, action_type, action_parameter,
                action_values, owner_may_execute=True,
            )
            if problem is not None:
                raise ValueError(f"{where}: {problem}")

        parsed.append(DeclaredTrigger(
            name=name,
            owner_user_id=owner,
            view=SavedView(
                view_id=f"declared/{name}", name=name,
                object_type=object_type,
                query_text=entry.get("query_text") or "",
                conditions=list(entry.get("conditions") or []),
                presentation={}, created_at="",
            ),
            # EXPLICIT rather than **{given[0]: threshold}, which hid
            # which field was set from the type checker -- and from a
            # reader.
            above=threshold if given[0] == "above" else None,
            gained=threshold if given[0] == "gained" else None,
            fell=threshold if given[0] == "fell" else None,
            action_type=action_type,
            action_parameter=action_parameter,
            action_values=dict(action_values),
            recipient_roles=tuple(sorted(set(recipient_roles))),
        ))
    return tuple(parsed)
