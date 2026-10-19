"""Who can see a type and its fields, by role (DEV_UI 13.3).

"THE ADMINISTRATOR'S BURDEN IS NOT WRITING THE POLICY. IT IS NOT
KNOWING WHAT THE POLICY DOES." DEV_UI's finding, from Google's Policy
Troubleshooter and AWS's own advice to test policies in a simulator
rather than trust the editor. The roles screen shows what each role
HOLDS; this answers the question an administrator is actually asked --
who can see Customer.email, and why can Bob not see this order?

ASKED OF THE REAL PERMISSION CODE, NOT RE-DERIVED. For each role, the
mediator's own visible_schema answers as it would for a person holding
that role -- the same function every screen and the agent are served
by. Re-implementing the rules here would give a second opinion that
could drift from the first, which is the one thing a "who can see
this" screen must never do. visible_schema depends on the role alone,
never on the person's compartment, so one call per role is exact.

TWO LAYERS, AND THEY ARE ANSWERED SEPARATELY. A role decides WHICH
FIELDS of a type a person may read (RBAC). Their compartment decides
WHICH OBJECTS (MAC): a person sees an object only when their own value
-- their region, say -- equals the object's. The second is stated as a
rule, followed through any chain: a Transaction borrowing its
compartment from its Customer is secured by the Customer's field, and
a chain is where the surprises have been (F-19).
"""

from typing import Any

from core.intermediate_layer.auth import UserRecord, authorize
from core.ontology.unrestricted import is_unrestricted

READ = "read"
DISCOVER = "discover"


def _compartment(schema: dict, object_type: str, attribute: str) -> dict | None:
    """How a type's objects are compartmented, followed to its end:
    {"attribute", "path": [{"type", "field"}...], "field", "type"}, the
    last pair naming the field that is actually compared. None when the
    type declares no compartment, or the chain breaks or loops -- the
    loader refuses both, so this only guards a stale schema."""
    path: list[dict] = []
    seen: set[str] = set()
    current = object_type
    while current not in seen:
        seen.add(current)
        security = (schema.get(current) or {}).get("security") or {}
        if is_unrestricted(schema.get(current)):
            return {"attribute": attribute, "path": path, "type": current, "field": None,
                    "unrestricted": True}
        if "field" in security:
            return {"attribute": attribute, "path": path, "type": current,
                    "field": security["field"]}
        via = security.get("via_field")
        if not via:
            return None
        target = (((schema.get(current) or {}).get("fields") or {}).get(via) or {}).get("target")
        if not target:
            return None
        path.append({"type": current, "field": via})
        current = target
    return None


def who_can_see(mediator: Any, schema: dict, object_type: str, attribute: str,
                holders: "dict[str, int] | None" = None,
                action_types: "dict | None" = None) -> "dict | None":
    """Per role: whether it can see the type or read it, which fields it
    reads or only knows exist, and which of the actions that change this
    type it may run. None for an unknown type.

    CHANGE IS BY ACTION, NOT BY A "WRITE" BIT: a person changes a
    Customer by running UpdateCustomerName, which needs
    execute:UpdateCustomerName (an action spanning other types also
    needs write: on them -- policy_validation.py). So "who can change
    this" is the actions on it each role may run.

    `holders`, when given, is how many accounts hold each role -- an
    administrator deciding whether a grant is too wide wants to know
    whether it is one person or forty.
    """
    if object_type not in schema:
        return None
    fields = list(schema[object_type].get("fields") or {})
    changing = sorted(name for name, action in (action_types or {}).items()
                      if object_type in ((action or {}).get("affected_object_types") or ()))
    roles, unable = [], []
    for role_name in sorted(mediator.roles):
        person = UserRecord("", None, role_name)
        seen = mediator.visible_schema(person).get(object_type)
        if seen is None:
            unable.append(role_name)
            continue
        shown = seen.get("fields") or {}
        roles.append({
            "role": role_name,
            "holders": None if holders is None else holders.get(role_name, 0),
            "type": READ if authorize(person, mediator.roles, f"read:{object_type}") else DISCOVER,
            "actions": [name for name in changing
                        if authorize(person, mediator.roles, f"execute:{name}")],
            # EVERY FIELD, in declaration order: read, discover, or None
            # for one the role cannot even know exists.
            "fields": {name: (None if name not in shown
                              else READ if shown[name].get("readable") else DISCOVER)
                       for name in fields},
        })
    return {"object_type": object_type, "roles": roles, "no_access": unable,
            "compartment": _compartment(schema, object_type, attribute)}
