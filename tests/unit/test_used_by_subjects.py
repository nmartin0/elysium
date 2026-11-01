"""Every row of the "used by" report lists the names it mentions.

A removal shows a person only the rows whose names they could find in
Schema (core/ontology/removal.visible_to), and it judges that by
`Referrer.subjects`. A row that mentions `Account` in its words and does
not list it would be shown to someone who cannot discover Account -- the
leak this guards, and the one a new kind of row would introduce silently.

The check is a drift check in the sense AGENTS.md allows: it reads the
words of every row the report produces for every type, field and link of
two schemas (the hand-built one with every kind of reference, and the
fixture configuration) and requires every type name, qualified
`Type.field` and (inside a type) bare field name in them to be listed,
except the name asked about.
"""

import re
from pathlib import Path

from core.deployment_loader import load_deployment
from core.ontology.used_by import used_by_field, used_by_link, used_by_type
from tests.unit import test_used_by as built

FIXTURES = Path(__file__).resolve().parents[1] / "integration" / "fixtures"


def _mentioned(row, schema, owner: str, asked: set[str]) -> set[str]:
    """The types, fields and links the row's words name besides what was asked."""
    words = f"{row.place} {row.says}"
    found = set()
    for type_name, definition in schema.items():
        if re.search(rf"\b{re.escape(type_name)}\b", words):
            found.add(type_name)
        for field in definition.get("fields") or {}:
            if re.search(rf"\b{re.escape(type_name)}\.{re.escape(field)}\b", words):
                found.add(f"{type_name}.{field}")
    # Inside the type a row names its other fields bare, never qualified.
    for field in (schema.get(owner) or {}).get("fields") or {}:
        if row.place.startswith(f"type {owner}") and re.search(rf"\b{re.escape(field)}\b", words):
            found.add(f"{owner}.{field}")
    return found - asked


def _covered(name: str, subjects: tuple[str, ...]) -> bool:
    """A field listed covers its type; a type listed covers only itself."""
    return name in subjects or any(subject.startswith(f"{name}.") for subject in subjects)


def _cases(schema, roles, actions, triggers):
    for type_name, definition in schema.items():
        yield type_name, used_by_type(schema, roles, actions, triggers, type_name), {type_name}
        for field in definition.get("fields") or {}:
            if definition["fields"][field].get("type") == "link":
                continue
            yield (f"{type_name}.{field}", used_by_field(schema, roles, actions, triggers, type_name, field),
                   {type_name, f"{type_name}.{field}"})
    links = {f["link_type"]: [] for d in schema.values() for f in (d.get("fields") or {}).values()
             if f.get("type") == "link"}
    for link in links:
        ends = {f"{owner}.{name}" for owner, d in schema.items() for name, f in (d.get("fields") or {}).items()
                if f.get("type") == "link" and f.get("link_type") == link}
        yield (f"link {link}", used_by_link(schema, roles, actions, triggers, link),
               ends | {end.split(".")[0] for end in ends})


def _check(schema, roles, actions, triggers):
    rows = 0
    for asked_name, found, asked in _cases(schema, roles, actions, triggers):
        for row in found:
            rows += 1
            owner = row.place.split(",")[0].removeprefix("type ").strip()
            for name in _mentioned(row, schema, owner, asked):
                assert _covered(name, row.subjects), (
                    f"asking about {asked_name}: the row {row.kind!r} {row.place!r} says {row.says!r} "
                    f"and mentions {name}, which its subjects {row.subjects} do not list")
    return rows


def test_every_kind_of_row_in_the_hand_built_schema_lists_what_it_mentions():
    schema = built._schema()
    schema["Order"]["fields"]["cost"].update(status="deprecated", deprecation={"reason": "x", "replaced_by": "price"})
    schema["Line"]["status"] = "deprecated"
    schema["Line"]["deprecation"] = {"reason": "x", "replaced_by": "Order"}
    schema["Line"]["fields"]["order"].update(status="deprecated", deprecation={"reason": "x", "replaced_by": "lines"})
    roles = {**built.ROLES, "wide": {"allowed_actions": ["read:Order.cost", "read:Order.margin", "read:Line"]}}

    rows = _check(schema, roles, built.ACTIONS, [built._trigger([{"field": "price"}])])

    assert rows > 25


def test_every_row_the_fixture_configuration_produces_lists_what_it_mentions():
    config = load_deployment(FIXTURES)

    rows = _check(config.schema, config.roles, config.action_types, config.declared_triggers)

    assert rows > 100


def test_the_check_itself_notices_a_row_that_forgets_a_name():
    from core.ontology.used_by import Referrer

    row = Referrer("security", "Line row rule", "borrows its rule through Order.region", ("Line",))

    mentioned = _mentioned(row, built._schema(), "Line", {"Line"})

    assert "Order.region" in mentioned and not _covered("Order.region", row.subjects)
    assert _covered("Order.region", ("Line", "Order.region"))
