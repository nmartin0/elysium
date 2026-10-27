"""A silo's row rule, and `security: inherit` (27 October, owner-agreed).

THE DECISION. A type created over a source should take its row rule from
where the source lives, as Foundry does (the object type's permissions
come from its backing datasource's location). Elysium's 19 October rule
still holds -- "nothing is implicit": a type with no `security` block is
an error -- so inheritance is WRITTEN OUT TWICE, on purpose, by a person:

  data_silos.yaml     the silo says its rule:   security: unrestricted
                                          or    security: {field: region}
  ontology_schema.yaml the type says it follows:  security: inherit

WHEN IT IS RESOLVED: at load, before anything reads the schema. The
resolved block is an ordinary one, so the mediator, the write-down check,
who_can_see and the validators see exactly what they always saw. That is
what makes the inheritance LIVE: editing the silo's rule and reloading
changes every type that inherits it, with no copy to go stale.

WHAT CANNOT HAPPEN, each refused at load with the type's name:

  * `inherit` on a silo that declares no rule. Inheritance can never turn
    into "everyone sees every row" by omission.
  * `inherit` on a type with no storage (a type with no source must have
    its security configured by hand -- nothing exists to inherit from).
  * a silo rule that is anything but `unrestricted` or {field: <name>}. A
    silo has no links, so `via_field` has no meaning there.
  * an inherited {field: x} on a type that has no plain data field x --
    the ordinary security validation says so, because the resolved block
    goes through it like any other.

The type's own `storage.silo` decides; `additional_storage` (a property
borrowed from another silo) never does.
"""

INHERIT = "inherit"
INHERITED_FROM = "security_inherited_from"


def silo_rules(data_silos_raw: dict) -> dict[str, dict]:
    """{silo: normalised block} for the silos that declare one."""
    rules: dict[str, dict] = {}
    for name, silo in ((data_silos_raw or {}).get("data_silos") or {}).items():
        if not isinstance(silo, dict) or "security" not in silo:
            continue
        declared = silo["security"]
        if declared == "unrestricted":
            rules[name] = {"unrestricted": True}
        elif (isinstance(declared, dict) and set(declared) == {"field"}
              and isinstance(declared["field"], str) and declared["field"]):
            rules[name] = {"field": declared["field"]}
        else:
            raise ValueError(
                f"data_silos.yaml: silo {name!r}: security must be the word "
                f"`unrestricted` or `{{field: <name>}}`; got {declared!r}.")
    return rules


def resolve_inherited_security(schema_raw: dict, data_silos_raw: dict) -> dict:
    """`security: inherit` -> its silo's block, in place. Also records the
    silo on the type (`security_inherited_from`) so screens can say where
    a rule came from."""
    rules = silo_rules(data_silos_raw)
    for type_name, type_def in (schema_raw.get("object_types") or {}).items():
        if not isinstance(type_def, dict) or type_def.get("security") != INHERIT:
            continue
        silo = (type_def.get("storage") or {}).get("silo")
        if not silo:
            raise ValueError(
                f"Object type {type_name!r}: `security: inherit` needs a source "
                f"to inherit from, and it declares no storage. Write its security out.")
        if silo not in rules:
            raise ValueError(
                f"Object type {type_name!r}: `security: inherit` follows silo "
                f"{silo!r}, which declares no security in data_silos.yaml. Give the "
                f"silo a rule, or write this type's security out.")
        type_def["security"] = dict(rules[silo])
        type_def[INHERITED_FROM] = silo
    return schema_raw
