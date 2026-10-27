"""The "used by" report cannot miss a reference the loader would trip over.

The report (core/ontology/used_by.py) is only worth having if it is
COMPLETE: a removal gated on it would let through anything it forgot.
Its authority is the real loader. For every field, type and link of the
fixture configuration this removes the thing from a copy of the files,
loads the copy with the real loader, and requires:

    the loader refuses  =>  the report is not empty

TWICE, because almost everything here is granted to some role, and a
grant alone would make any report look non-empty. First with the
target's grants taken out of the copy too, so the loader can refuse only
for something that is NOT a grant, and the report must list a row that is
not a grant. Then, when that load succeeds but the load with the grants
left in refuses, grants were the whole reason and the report must list one.

A report that is not empty although the loader accepts is allowed (a
reference the loader does not check, such as a declared trigger's
filter).
"""

import shutil
from pathlib import Path

import pytest
import yaml

from core.deployment_loader import load_deployment
from core.ontology.used_by import used_by_field, used_by_link, used_by_type

FIXTURES = Path(__file__).resolve().parents[1] / "integration" / "fixtures"

#: The same thing, removed from a copy: (kind, type, name).
def _targets(schema_raw: dict) -> list[tuple]:
    found = []
    for type_name, type_def in schema_raw["object_types"].items():
        found.append(("type", type_name, None))
        for field_name, field in (type_def.get("fields") or {}).items():
            if field.get("type") != "link":
                found.append(("field", type_name, field_name))
    for link_name in schema_raw.get("link_types") or {}:
        found.append(("link", None, link_name))
    return found


def _without(schema_raw: dict, kind: str, type_name, name) -> dict:
    changed = yaml.safe_load(yaml.safe_dump(schema_raw))
    if kind == "type":
        del changed["object_types"][type_name]
    elif kind == "field":
        del changed["object_types"][type_name]["fields"][name]
    else:
        del changed["link_types"][name]
    return changed


def _names(grant: str, kind: str, type_name, name) -> bool:
    """Does a grant name the thing removed (a type's fields and a link's ends included)?"""
    verb, _, rest = grant.partition(":")
    if verb not in ("read", "discover", "write") or rest.startswith("label:"):
        return False
    owner, _, field = rest.partition(".")
    if kind == "type":
        return owner == type_name
    if kind == "field":
        return (owner, field) == (type_name, name)
    return (owner, field) in LINK_ENDS.get(name, ())


def _loader_accepts(tmp_path: Path, changed: dict, strip: "tuple | None" = None) -> bool:
    """Loads a copy with `changed` as its ontology; with `strip` =
    (kind, type, name), the grants naming that thing are taken out of the
    policy file as well."""
    copy = tmp_path / "copy"
    if copy.exists():
        shutil.rmtree(copy)
    shutil.copytree(FIXTURES, copy)
    (copy / "ontology_schema.yaml").write_text(yaml.safe_dump(changed, sort_keys=False))
    if strip is not None:
        policy = yaml.safe_load((copy / "policy.yaml").read_text())
        for role in policy["roles"].values():
            role["allowed_actions"] = [grant for grant in role.get("allowed_actions") or []
                                       if not _names(grant, *strip)]
        (copy / "policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False))
    try:
        load_deployment(copy)
    except (ValueError, KeyError):
        return False
    return True


def _report(config, kind: str, type_name, name) -> list:
    args = (config.schema, config.roles, config.action_types, config.declared_triggers)
    if kind == "type":
        return used_by_type(*args, type_name)
    if kind == "field":
        return used_by_field(*args, type_name, name)
    return used_by_link(*args, name)


SCHEMA_RAW = yaml.safe_load((FIXTURES / "ontology_schema.yaml").read_text())
CONFIG = load_deployment(FIXTURES)
#: {link type: ((type, api_name), ...)} -- a link's two ends are what grants name.
LINK_ENDS = {
    link: tuple((side["object_type"], side["api_name"]) for side in (spec["source"], spec["target"]))
    for link, spec in SCHEMA_RAW.get("link_types", {}).items()
}


@pytest.mark.parametrize("kind,type_name,name", _targets(SCHEMA_RAW),
                         ids=lambda value: str(value))
def test_whatever_the_loader_refuses_the_report_lists(tmp_path, kind, type_name, name):
    changed = _without(SCHEMA_RAW, kind, type_name, name)
    found = _report(CONFIG, kind, type_name, name)
    what = f"{kind} {type_name or ''}.{name or ''}"

    if not _loader_accepts(tmp_path, changed, strip=(kind, type_name, name)):
        assert [row for row in found if row.kind != "grant"], (
            f"removing {what} makes the loader refuse for a reason that is not a grant, and the "
            f"used-by report lists none: a reference is missing from core/ontology/used_by.py")
    elif not _loader_accepts(tmp_path, changed):
        assert [row for row in found if row.kind == "grant"], (
            f"removing {what} makes the loader refuse only because of a grant, and the used-by "
            f"report lists no grant")
