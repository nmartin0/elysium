"""What a role change would do, said in ACCESS terms (DEV_UI 13.5).

"Before saving, the diff stated in ACCESS TERMS rather than config
terms: this newly exposes ... to role analyst; this removes read of
Customer.email from 2 roles." DEV_UI calls it the highest-value screen:
Google's Policy Simulator, baseline against simulated. The roles editor
already shows the GRANTS added and removed; a reviewer approving
`read:Customer.email` still has to work out what that lets people do.

HOW, WITHOUT A SECOND OPINION. The permission code is asked twice --
as it stands, and as it would stand -- and the two answers compared.
The proposed grants go through the SAME compilation the running
mediators use (deployment_loader.access_roles: classification labels
into field grants, derived fields gated on their inputs), then a copy
of the mediator holding those roles is asked visible_schema for a
person in the role. So a grant that compiles to nothing shows as
nothing, and a label grant shows as the fields it opens.

PEOPLE, NOT OBJECTS. "412 objects" would be a count across every
compartment, and each person sees only their own; how many PEOPLE gain
or lose something is the number a reviewer can act on, and it is exact.
"""

import copy
import dataclasses
from typing import Any

from core.intermediate_layer.auth import UserRecord, authorize
from core.ontology.classifications import LABEL_GRANT_PREFIX


def _view(mediator: Any, roles: dict, role_name: str) -> dict:
    """What a person in `role_name` would be served, under `roles`."""
    probe = copy.copy(mediator)
    probe.roles = roles
    return probe.visible_schema(UserRecord("", None, role_name))


def _field_levels(view: dict) -> dict[tuple[str, str], str]:
    levels = {}
    for object_type, seen in view.items():
        for name, info in (seen.get("fields") or {}).items():
            levels[(object_type, name)] = "read" if info.get("readable") else "discover"
    return levels


def _type_levels(view: dict, roles: dict, role_name: str) -> dict[str, str]:
    person = UserRecord("", None, role_name)
    return {object_type: "read" if authorize(person, roles, f"read:{object_type}") else "discover"
            for object_type in view}


def _compare(before: dict, after: dict) -> tuple[list, list]:
    """Keys whose level rose (or appeared), and whose level fell (or went)."""
    rank = {None: 0, "discover": 1, "read": 2}
    gained, lost = [], []
    for key in sorted(set(before) | set(after), key=str):
        was, now = before.get(key), after.get(key)
        if rank[now] > rank[was]:
            gained.append((key, was, now))
        elif rank[now] < rank[was]:
            lost.append((key, was, now))
    return gained, lost


def role_change_impact(config: Any, mediator: Any, role_name: str,
                       after: "list | None", holders: int) -> dict:
    """What changing `role_name`'s grants to `after` (None: removing the
    role) would do to the `holders` people who hold it, in access terms.
    """
    from core.deployment_loader import _freeze_roles, access_roles, deep_freeze
    from core.role_changes import grants_of, resulting_roles

    declared = deep_freeze(_freeze_roles(resulting_roles(config.roles, role_name, after)))
    proposed = access_roles(dataclasses.replace(config, roles=declared))
    current = mediator.roles

    before_view = _view(mediator, current, role_name) if role_name in current else {}
    after_view = _view(mediator, proposed, role_name) if role_name in proposed else {}
    types_gained, types_lost = _compare(_type_levels(before_view, current, role_name),
                                        _type_levels(after_view, proposed, role_name))
    fields_gained, fields_lost = _compare(_field_levels(before_view), _field_levels(after_view))
    # A field of a type that appears or disappears entirely is said once,
    # on the type: "can now read Order" covers its fields.
    whole = {key for key, was, _ in types_gained if was is None} | {
        key for key, _, now in types_lost if now is None}

    def fields(changes):
        return [{"type": t, "field": f, "from": was, "to": now}
                for (t, f), was, now in changes if t not in whole]

    def types(changes):
        return [{"type": t, "from": was, "to": now} for t, was, now in changes]

    before_grants = set(grants_of(config.roles, role_name) or ())
    after_grants = set(after or ())
    actions = {name for name in config.action_types or {}}

    def runs(grants):
        return {g.removeprefix("execute:") for g in grants
                if g.startswith("execute:") and g.removeprefix("execute:") in actions}

    # EVERYTHING ELSE, said as the grant: administration (manage:*),
    # tools, labels. Labels are ALSO counted above through the fields
    # they open; listing the grant too says where that came from.
    def other(grant: str) -> bool:
        # A LABEL GRANT IS "read:label:pii" -- read:-shaped, and not a
        # read of any type. Filtered on the prefix alone it vanished from
        # the list it is supposed to be named in (found by its test).
        if grant.startswith(LABEL_GRANT_PREFIX):
            return True
        return not grant.startswith(("read:", "discover:", "execute:"))

    other_added = sorted(g for g in after_grants - before_grants if other(g))
    other_removed = sorted(g for g in before_grants - after_grants if other(g))
    return {
        "role": role_name,
        "holders": holders,
        "removes_role": after is None,
        "types_gained": types(types_gained),
        "types_lost": types(types_lost),
        "fields_gained": fields(fields_gained),
        "fields_lost": fields(fields_lost),
        "actions_gained": sorted(runs(after_grants) - runs(before_grants)),
        "actions_lost": sorted(runs(before_grants) - runs(after_grants)),
        "other_gained": other_added,
        "other_lost": other_removed,
    }
