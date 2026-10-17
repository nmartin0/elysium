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

COMBINED, HELD AND SCHEDULED, LIKE A MADE ONE (17 October): "at most",
more conditions under `also:` (each its own inline query, optionally
named), `combine: all | any`, `hold_minutes:`, and `schedule:` with a
`timezone:`. And the action may take its objects from one of those
conditions, named in `action: objects_from:`. Checked at load by the
same rules the Watch dialog's requests meet (core/trigger_states.py),
so neither can say what the other cannot.

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
    "at_most", "also", "combine", "hold_minutes", "schedule", "timezone",
})
_ACTION_KEYS = frozenset({"type", "parameter", "values", "objects_from"})
# A CONDITION UNDER `also:` -- its own inline query, and one threshold.
_CONDITION_KEYS = frozenset({"name", "object_type", "query_text", "conditions", "above", "at_most"})
_THRESHOLDS = ("above", "gained", "fell", "at_most")


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
    # COMBINED, HELD OR SCHEDULED (17 October): the same attribute names
    # as a made Trigger, so the state evaluator takes either.
    at_most: int | None = None
    also: tuple = ()
    combine: str = "all"
    hold_minutes: int | None = None
    schedule: dict | None = None
    action_view_id: str | None = None
    # THE INLINE VIEWS OF `also`, in order, beside `view`. A made
    # trigger's views are in the saved-view store; a declared one's are
    # here, and `views_by_id` serves them the same way.
    more_views: tuple = ()

    @property
    def views_by_id(self) -> dict:
        return {view.view_id: view for view in (self.view, *self.more_views)}

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
                f"{where} needs exactly one of above, at_most, gained or fell."
            )
        threshold = entry[given[0]]
        if not isinstance(threshold, int) or isinstance(threshold, bool) \
                or threshold < 0:
            raise ValueError(f"{where}: {given[0]} must be a whole number.")

        recipient_roles = entry.get("recipient_roles") or []
        for role in recipient_roles:
            if role not in roles:
                raise ValueError(f"{where}: no role {role!r}.")

        own_view = SavedView(
            view_id=f"declared/{name}", name=name,
            object_type=object_type,
            query_text=entry.get("query_text") or "",
            conditions=list(entry.get("conditions") or []),
            presentation={},
            # NO TRAIL: a declared trigger's view is written in
            # YAML, so nobody followed a link to reach it.
            origin={}, created_at="",
        )
        more_views, also = _more_conditions(where, name, entry.get("also"), object_types)
        # A CONDITION IS NAMED for the sentence its notices use and for
        # `objects_from`; the trigger's own is named after the trigger.
        names = {name: own_view.view_id, **{view.name: view.view_id for view in more_views}}

        action = entry.get("action")
        action_type = action_parameter = action_view_id = None
        action_values: dict = {}
        if action is not None:
            unknown = sorted(set(action) - _ACTION_KEYS)
            if unknown:
                raise ValueError(f"{where}: action has unknown key(s) {unknown}.")
            action_type = action.get("type")
            action_parameter = action.get("parameter")
            action_values = action.get("values") or {}
            objects_from = action.get("objects_from")
            if objects_from is not None:
                if objects_from not in names:
                    raise ValueError(
                        f"{where}: action objects_from {objects_from!r} is not one of its "
                        f"conditions -- {sorted(names)}.")
                action_view_id = names[objects_from]
            source = next(view for view in (own_view, *more_views)
                          if view.view_id == (action_view_id or own_view.view_id))
            # THE OWNER'S GRANT IS CHECKED WHEN IT FIRES, not here:
            # accounts live in a database that changes without the
            # configuration changing. Everything about the ACTION's
            # own shape is checked now -- against the objects of the
            # condition it takes them from.
            problem = action_problem(
                action_types, source.object_type, action_type, action_parameter,
                action_values, owner_may_execute=True,
            )
            if problem is not None:
                raise ValueError(f"{where}: {problem}")

        # COMBINED, HELD OR SCHEDULED: the rules a made trigger meets.
        schedule = None
        if entry.get("schedule") is not None:
            from core.timer_rules import RuleError, rule_from

            try:
                schedule = rule_from(entry["schedule"], entry.get("timezone") or "UTC")
            except RuleError as e:
                raise ValueError(f"{where}: {e}") from e
        elif entry.get("timezone") is not None:
            raise ValueError(f"{where}: a timezone is for a schedule, and there is none.")
        from core.trigger_states import problem as combined_problem

        combined = combined_problem(
            above=entry.get("above"), gained=entry.get("gained"), fell=entry.get("fell"),
            at_most=entry.get("at_most"), also=list(also), combine=entry.get("combine", "all"),
            hold_minutes=entry.get("hold_minutes"), schedule=schedule, action_type=action_type,
            owned_view_ids={own_view.view_id, *(view.view_id for view in more_views)},
            view_id=own_view.view_id, action_view=action_view_id)
        if combined is not None:
            raise ValueError(f"{where}: {combined}")

        parsed.append(DeclaredTrigger(
            name=name,
            owner_user_id=owner,
            view=own_view,
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
            at_most=threshold if given[0] == "at_most" else None,
            also=also,
            combine=entry.get("combine", "all"),
            hold_minutes=entry.get("hold_minutes"),
            schedule=schedule,
            action_view_id=action_view_id,
            more_views=more_views,
        ))
    return tuple(parsed)


def _more_conditions(where: str, name: str, raw, object_types) -> "tuple[tuple, tuple]":
    """`also:` -- each condition its own inline view and one threshold.
    Returns (views, conditions) in order, the conditions in the shape a
    made trigger stores: {view_id, above | at_most}."""
    if raw is None:
        return (), ()
    if not isinstance(raw, list):
        raise ValueError(f"{where}: `also` is a list of conditions.")
    views, conditions, seen = [], [], {name}
    for index, condition in enumerate(raw):
        here = f"{where}, also[{index}]"
        if not isinstance(condition, dict):
            raise ValueError(f"{here} must be a mapping.")
        unknown = sorted(set(condition) - _CONDITION_KEYS)
        if unknown:
            raise ValueError(f"{here} has unknown key(s) {unknown}.")
        object_type = condition.get("object_type")
        if not isinstance(object_type, str) or object_type not in object_types:
            raise ValueError(f"{here}: no object type {object_type!r}.")
        label = condition.get("name") or f"{object_type} ({index + 2})"
        if not isinstance(label, str) or label in seen:
            # NAMES ARE HOW objects_from POINTS, so two alike would be a
            # pointer to either.
            raise ValueError(f"{here}: the name {label!r} is used twice in this trigger.")
        seen.add(label)
        view = SavedView(view_id=f"declared/{name}/{index + 1}", name=label,
                         object_type=object_type, query_text=condition.get("query_text") or "",
                         conditions=list(condition.get("conditions") or []), presentation={},
                         origin={}, created_at="")
        views.append(view)
        conditions.append({"view_id": view.view_id,
                           **{key: condition[key] for key in ("above", "at_most") if key in condition}})
    return tuple(views), tuple(conditions)
