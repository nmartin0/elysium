"""Field classifications: what a property's VALUES are, declared once (R12).

    fields:
      email:
        type: data
        classification: pii
      salary:
        type: data
        classification: [pii, financial]

A LABEL SAYS WHAT A VALUE IS -- personal, financial. By default that
is all it does: it is recorded where the data goes, so that anyone
reading the lake -- a backup, an auditor, a future REST catalog (R17)
-- can see which columns hold what. A deployment that sets
`access: label_enforcement: true` also lets labels decide who may read
a field; compile_label_access below is that rule, decided by the owner
on 2026-10-12 (formerly BLOCKING 6, "grant by TAG rather than by field
name").

WHY IT MUST PROPAGATE, which is the whole of R12. Foundry: "If a
dataset has a file marking, every dataset that depends on it inherits
that marking", and "restricting access to a dataset always restricts
access to any data derived from it". A label on the ontology property
alone describes ONE of three copies of the value: the source column is
copied verbatim into bronze, standardised into silver, and conformed
into gold. core/mirror/classifications.py carries it to all three.

THE VOCABULARY IS OPEN, deliberately: which labels exist is each
deployment's choice. A grant naming a label no field carries is refused
at load (policy_validation), so a misspelt grant cannot pass silently. What is checked is SHAPE -- lowercase,
identifier-like -- so "PII" and "pii " cannot quietly become three
labels for one thing.

REMOVING ONE IS AN ONTOLOGY EDIT, and recorded as one (config history).
Foundry calls removal "a sensitive action" requiring its own permission;
here it is whoever may change the ontology, which is the same set of
people who could have declared the field unclassified in the first
place.
"""

import re

_LABEL = re.compile(r"^[a-z][a-z0-9_]*$")


def field_classifications(field_info: dict) -> frozenset[str]:
    """The labels one field declares. Empty when it declares none."""
    declared = field_info.get("classification")
    if declared is None:
        return frozenset()
    if isinstance(declared, str):
        return frozenset({declared})
    return frozenset(declared)


def validate_field_classification(object_type_name: str, field_name: str,
                                  field_info: dict) -> None:
    """Refuses a classification that is not a label or list of labels."""
    declared = field_info.get("classification")
    if declared is None:
        return
    labels = [declared] if isinstance(declared, str) else declared
    if not isinstance(labels, list) or not labels:
        raise ValueError(
            f"Object type {object_type_name!r}: field {field_name!r} declares a "
            f"`classification` that is neither a label nor a non-empty list of "
            f"labels: {declared!r}."
        )
    for label in labels:
        if not isinstance(label, str) or not _LABEL.match(label):
            raise ValueError(
                f"Object type {object_type_name!r}: field {field_name!r} declares "
                f"classification {label!r}. A label is lowercase letters, digits "
                f"and underscores, starting with a letter -- 'pii', not 'PII' -- "
                f"so one label cannot be spelled three ways."
            )


#: The grant that reads every field carrying a label (formerly BLOCKING 6).
#: The same string policy_validation.LABEL_GRANT_PREFIX checks.
LABEL_GRANT_PREFIX = "read:label:"


def compile_label_access(roles: dict, object_types: dict) -> dict:
    """The roles with classification labels turned into field grants.

    AS THE OWNER DECIDED IT (2026-10-12): a label both
    GRANTS and RESTRICTS, a label grant never opens a type, and the
    whole is opt-in per deployment.

    For every field that carries labels, in every type the role can READ:

        readable  if the role holds read:label:L for EVERY label L
        otherwise demoted -- read: becomes discover:, so the role may
                  still know the field exists and not what it holds

    GRANT: `read:label:pii` replaces a list of read:T.f strings for
    every pii field -- the 160-to-3,120-grants-per-role burden the original
    proposal counted. RESTRICT: a field labelled pii is unreadable without the
    label, whatever per-field grant a role was given -- Foundry's
    markings, "every dataset that depends on it inherits that marking",
    and conjunctive: [pii, financial] needs both. DEMOTED, NOT REMOVED:
    Foundry likewise lets a user see that a marked dataset exists
    without its data, which is this project's discover: rung.

    A LABEL NEVER OPENS A TYPE: no field of a type the role lacks
    read:<Type> for is touched, granted or not.

    COMPILED, NOT CHECKED PER READ. The result is ordinary grants, so
    every caller of authorize() -- the mediator, the agent, the write
    path's reads -- sees the same answer without learning what a label
    is. The DECLARED roles stay as they are for the role editor; only
    the mediators are handed these.
    """
    compiled = {}
    for role_name, role in roles.items():
        grants = set(role.get("allowed_actions") or ())
        held = {grant[len(LABEL_GRANT_PREFIX):] for grant in grants
                if grant.startswith(LABEL_GRANT_PREFIX)}
        for object_type, type_def in object_types.items():
            if f"read:{object_type}" not in grants:
                continue
            for field_name, info in (type_def.get("fields") or {}).items():
                labels = field_classifications(info)
                if not labels:
                    continue
                field_grant = f"read:{object_type}.{field_name}"
                if labels <= held:
                    grants.add(field_grant)
                elif field_grant in grants:
                    grants.discard(field_grant)
                    grants.add(f"discover:{object_type}.{field_name}")
        compiled[role_name] = {**role, "allowed_actions": frozenset(grants)}
    return compiled


def label_access_changes(roles: dict, object_types: dict) -> dict[str, tuple[list, list]]:
    """{role: (field grants it would GAIN, field grants it would LOSE)}
    were label enforcement turned on. What an operator reads before
    flipping the switch; empty lists for a role nothing changes for."""
    compiled = compile_label_access(roles, object_types)
    changes = {}
    for role_name, role in roles.items():
        before = {g for g in role.get("allowed_actions") or () if g.startswith("read:") and "." in g}
        after = {g for g in compiled[role_name]["allowed_actions"]
                 if g.startswith("read:") and "." in g}
        changes[role_name] = (sorted(after - before), sorted(before - after))
    return changes
