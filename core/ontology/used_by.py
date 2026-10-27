"""What names a type, a field or a link: the "used by" report (27 October).

WHY IT EXISTS. Removing or retyping anything (designed and agreed 27
October, see BLOCKING.md's "Editing the ontology's shape") has one rule
that makes it safe: it is refused while anything still names the thing,
and the refusal lists every place so each owner can fix their own. The
loader already refuses a dangling grant or rule, but one error at a time
and only at the moment of loading. This is the same knowledge as a list,
ahead of the change, and it is useful on its own: "what happens if I
touch this?" should be answerable before touching it.

READ-ONLY, FROM THE LOADED CONFIGURATION. Nothing here reads a file or
a database, so it cannot disagree with what is running. It reuses the
parsers each feature already has (`rules_for`, `dependencies_for`,
`derived_fields`, `enriched_fields`, `predicted_fields`, `unusual_of`)
rather than reading their YAML a second time: a second reading is where
the two would drift.

WHAT IT COVERS, and what it does not.

  Covered: role grants, action types (the types they touch, the fields
  they set, the fields their criteria read), links, row-security chains
  (including inherited ones), identifiers and title fields, field
  rules, dependencies, derived, enriched and predicted inputs, unusual
  checks, and declared triggers (their views' type and conditions).

  Not covered, deliberately: things stored beside the configuration --
  saved views, frozen sets, recipes, proposals, notes -- whose references
  are rows in databases, not lines in files. They are the next piece, and
  the report says so rather than implying it saw them.

  Not covered, because it is not a reference: `read:label:<name>` grants
  follow a classification, not a field; and the free text of example
  queries, which names things only in prose.

THE CONTROL THAT KEEPS IT HONEST is tests/unit/test_used_by_is_complete.py:
for every field and type of the fixture configuration, removing it makes
the real loader refuse exactly when this report is not empty. A reference
the loader would trip over and this report missed fails that test.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from core.ontology.derived_fields import derived_fields
from core.ontology.enriched_fields import enriched_fields
from core.ontology.field_rules import dependencies_for, rules_for
from core.ontology.predicted_fields import predicted_fields
from core.ontology.unusual_checks import unusual_of

_GRANT_VERBS = ("read", "discover", "write")
_GRANTS_SHOWN = 3


@dataclass(frozen=True)
class Referrer:
    """One place that names the thing."""

    kind: str   # grant, action, link, security, identifier, rule, dependency, derived, enriched, ...
    place: str  # where it is written, in the words a screen would use
    says: str   # what it does with the name

    def as_dict(self) -> dict:
        return {"kind": self.kind, "place": self.place, "says": self.says}


def used_by_type(schema: Mapping, roles: Mapping, action_types: Mapping, triggers,
                 object_type: str) -> list[Referrer]:
    """Everything outside the type that names it, or names one of its fields."""
    found: list[Referrer] = []
    found += _grants(roles, lambda owner, field: owner == object_type, whole_type=True)
    found += _links_of_type(schema, object_type)
    found += _security_chains(schema, lambda owner, _field: owner == object_type, exclude=object_type)
    found += _actions(action_types, schema, object_type, None)
    found += _triggers(triggers, object_type, None)
    return _ordered(found)


def used_by_field(schema: Mapping, roles: Mapping, action_types: Mapping, triggers,
                  object_type: str, field: str) -> list[Referrer]:
    """Everything that names one field of a type.

    A link's end is a field too, so a link field also lists the link it
    belongs to: removing one end removes both, and the report says so.
    """
    type_def = schema.get(object_type) or {}
    found: list[Referrer] = []
    found += _grants(roles, lambda owner, name: owner == object_type and name == field)
    found += _inside_the_type(type_def, object_type, field)
    found += _security_chains(schema, lambda owner, name: owner == object_type and name == field,
                              exclude=object_type)
    found += _actions(action_types, schema, object_type, field)
    found += _triggers(triggers, object_type, field)
    declared = (type_def.get("fields") or {}).get(field) or {}
    if declared.get("type") == "link":
        found.append(Referrer("link", f"link {declared.get('link_type')}",
                              f"{object_type}.{field} is one end of it; removing the link removes both ends"))
    return _ordered(found)


def used_by_link(schema: Mapping, roles: Mapping, action_types: Mapping, triggers,
                 link_type: str) -> list[Referrer]:
    """Everything that names either end of a link."""
    found: list[Referrer] = []
    for owner, name in _link_ends(schema, link_type):
        found += used_by_field(schema, roles, action_types, triggers, owner, name)
    # Both ends were listed with "one end of it"; say that once, not twice.
    return _ordered([item for item in found if item.kind != "link"])


def _ordered(found: list[Referrer]) -> list[Referrer]:
    unique = {(item.kind, item.place, item.says): item for item in found}
    return [unique[key] for key in sorted(unique)]


def _link_ends(schema: Mapping, link_type: str) -> list[tuple[str, str]]:
    return [(owner, name)
            for owner, type_def in schema.items()
            for name, field in (type_def.get("fields") or {}).items()
            if field.get("type") == "link" and field.get("link_type") == link_type]


def _grants(roles: Mapping, matches, whole_type: bool = False) -> list[Referrer]:
    """Role grants naming a type or field, one row per role.
    `matches(type, field_or_None)`; a role holding several is one row."""
    found = []
    for role, definition in sorted(roles.items()):
        named = []
        for grant in sorted((definition or {}).get("allowed_actions") or []):
            verb, _, rest = grant.partition(":")
            if verb not in _GRANT_VERBS or rest.startswith("label:"):
                continue
            owner, _, name = rest.partition(".")
            if (not name and whole_type and matches(owner, None)) or (name and matches(owner, name)):
                named.append(grant)
        if named:
            shown = ", ".join(named[:_GRANTS_SHOWN])
            more = f" and {len(named) - _GRANTS_SHOWN} more" if len(named) > _GRANTS_SHOWN else ""
            noun = "grant" if len(named) == 1 else "grants"
            found.append(Referrer("grant", f"role {role}", f"has {len(named)} {noun} naming it: {shown}{more}"))
    return found


def _links_of_type(schema: Mapping, object_type: str) -> list[Referrer]:
    """One row per link type with an end on, or pointing at, the type."""
    names = {field.get("link_type")
             for owner, type_def in schema.items()
             for field in (type_def.get("fields") or {}).values()
             if field.get("type") == "link" and object_type in (owner, field.get("target"))}
    found = []
    for name in sorted(names):
        ends = " and ".join(f"{owner}.{end}" for owner, end in sorted(_link_ends(schema, name)))
        found.append(Referrer("link", f"link {name}", f"joins {ends}"))
    return found


def _rule_end(schema: Mapping, object_type: str) -> list[tuple[str, str]]:
    """[(type, field)] along a type's row rule: each link it hops by as
    (type, link field), ending at the plain field that carries the rule."""
    hops: list[tuple[str, str]] = []
    seen = {object_type}
    current = object_type
    while True:
        security = (schema.get(current) or {}).get("security") or {}
        if "field" in security:
            hops.append((current, security["field"]))
            return hops
        via = security.get("via_field")
        if via is None:
            return hops
        hops.append((current, via))
        current = ((schema.get(current) or {}).get("fields") or {}).get(via, {}).get("target")
        if current is None or current in seen:
            return hops
        seen.add(current)


def _security_chains(schema: Mapping, matches, exclude: str) -> list[Referrer]:
    """Other types whose row rule is read through the thing named.

    A type with `via_field` takes its rule from the type that link
    points at, and so on down. `hops[0]` is the type's own block; the
    rest are the types it borrows from, which are what can be named."""
    found = []
    for owner in sorted(schema):
        if owner == exclude:
            continue
        for hop_type, hop_field in _rule_end(schema, owner)[1:]:
            if matches(hop_type, hop_field):
                found.append(Referrer("security", f"{owner} row rule",
                                      f"borrows its rule through {hop_type}.{hop_field}"))
                break
    return found


def _inside_the_type(type_def: Mapping, object_type: str, field: str) -> list[Referrer]:
    """The type's own blocks that name one of its fields."""
    found: list[Referrer] = []
    where = f"type {object_type}"

    def add(kind: str, place: str, says: str) -> None:
        found.append(Referrer(kind, f"{where}, {place}" if place else where, says))

    if type_def.get("id_field") == field:
        add("identifier", "", "uses it as its identifier")
    if type_def.get("title_field") == field:
        add("title", "", "uses it as its title")
    security = type_def.get("security") or {}
    inherited = type_def.get("security_inherited_from")
    for key in ("field", "via_field"):
        if security.get(key) == field:
            source = f" (inherited from silo {inherited})" if inherited else ""
            add("security", "row rule", (f"is based on it{source}" if key == "field"
                                         else f"borrows its rule from the type this links to{source}"))
    for rule in rules_for(type_def):
        if field in (rule.field, rule.other):
            add("rule", f"rule {rule.name}", f"checks {rule.describe()}")
    for dependency in dependencies_for(type_def):
        if field == dependency.dependent or field in dependency.determinant:
            add("dependency", f"dependency {dependency.name}", dependency.describe())
    for name, derivation in derived_fields(type_def).items():
        if field in derivation.inputs:
            add("derived", f"field {name}", f"is calculated from it: {derivation.describe()}")
    for name, enrichment in enriched_fields(type_def).items():
        if field in enrichment.inputs:
            add("enriched", f"field {name}", f"is {enrichment.describe()}")
    for name, prediction in predicted_fields(type_def).items():
        if field == prediction.target or field in prediction.inputs:
            add("predicted", f"field {name}", prediction.describe()
                if field in prediction.inputs else f"predicts {prediction.target}")
    unusual = unusual_of(type_def)
    if unusual and (field in unusual[0] or field in unusual[1]):
        add("unusual", "unusual-records check", "reads it")
    return found


def _actions(action_types: Mapping, schema: Mapping, object_type: str,
             field: "str | None") -> list[Referrer]:
    found = []
    for name, action in sorted(action_types.items()):
        place = f"action {name}"
        writes = [write for write in action.get("sub_writes") or []
                  if write.get("object_type") == object_type]
        if field is None:
            if object_type in (action.get("affected_object_types") or []) or writes or any(
                    spec.get("object_type") == object_type
                    for spec in (action.get("parameters") or {}).values()):
                found.append(Referrer("action", place, f"acts on {object_type}"))
            continue
        for write in writes:
            for mutation in write.get("mutations") or []:
                if (mutation.get("set") or {}).get("property") == field:
                    found.append(Referrer("action", place, f"sets {object_type}.{field}"))
            for criterion in write.get("submission_criteria") or []:
                if criterion.get("check") == "current_state" and criterion.get("field") == field:
                    found.append(Referrer("action", place, f"checks {object_type}.{field} before running"))
        if writes or object_type in (action.get("affected_object_types") or []):
            for criterion in action.get("submission_criteria") or []:
                if criterion.get("check") == "current_state" and criterion.get("field") == field:
                    found.append(Referrer("action", place, f"checks {object_type}.{field} before running"))
    return found


def _triggers(triggers, object_type: str, field: "str | None") -> list[Referrer]:
    found = []
    for trigger in triggers or ():
        for view in trigger.views_by_id.values():
            if view.object_type != object_type:
                continue
            if field is None:
                found.append(Referrer("trigger", f"trigger {trigger.name}", f"watches {object_type}"))
            elif any(isinstance(condition, Mapping) and condition.get("field") == field
                     for condition in view.conditions or ()):
                found.append(Referrer("trigger", f"trigger {trigger.name}",
                                      f"filters {object_type} on {field}"))
    return found
