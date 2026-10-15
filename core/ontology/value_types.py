"""What a value IS, declared once: its check, its tidying, its key (R28).

    fields:
      email:
        value_type: email
      phone:
        value_type: {phone: GB}     # region for numbers written nationally

ONE DECLARATION FOR THREE THINGS that otherwise have to be kept in step
by hand, and drift:

  the CHECK          constraints: {email: true} / {phone: GB}   (DEP-4)
  the TIDYING        standardise: {email: true} / {phone: GB}   (DEP-4)
  the CANONICAL KEY  what identity matching compares: an address
                     lower-cased whole, a number in E.164 -- so
                     "Ada@Example.com" and "ada@example.com", or
                     "020 7946 0018" and "+44 20 7946 0018", are one key.

Foundry's precedent is the VALUE TYPE: a semantic type layered on a base
type, carrying its own validation, reused across properties. That is
this, kept to the kinds the reference-data libraries can actually
judge.

THE KEY IS NEVER THE VALUE. standardise.py keeps a mailbox's case,
because RFC 5321 lets a server treat `Ada` and `ada` as two mailboxes;
the KEY folds it, because for deciding that two records are one person
nearly every real deployment treats them as the same. The same line
identity's `casefold` draws (ZOO-24), here made by the type.

EXPANDED AT LOAD into the rules it stands for, so everything downstream
-- writes, silver, the schema screen -- reads ordinary constraints and
standardisation it already understands. A field that declares its own
constraint or standardise rule for the same thing keeps its own.
"""

from collections.abc import Mapping

from core.ontology.field_types import is_computed

KINDS = ("email", "phone")


def value_type_of(field: Mapping) -> "tuple[str, object] | None":
    """(kind, setting) -- ("email", True) or ("phone", "GB") -- or None."""
    declared = field.get("value_type")
    if declared is None:
        return None
    if declared == "email":
        return "email", True
    if declared == "phone":
        return "phone", True
    if hasattr(declared, "get") and set(declared) == {"phone"}:
        return "phone", declared["phone"]
    return "invalid", declared


def validate_and_expand_value_types(object_types: Mapping) -> None:
    """Refuses a value type that cannot apply, then writes the rules it
    stands for into the RAW schema, before it is frozen."""
    for type_name, type_def in object_types.items():
        for field_name, field in (type_def.get("fields") or {}).items():
            found = value_type_of(field)
            if found is None:
                continue
            where = f"{type_name}.{field_name}.value_type"
            kind, setting = found
            if kind == "invalid":
                raise ValueError(f"{where} must be one of {list(KINDS)} or {{phone: <region>}}, "
                                 f"got {setting!r}.")
            if (field.get("data_type") or "string") != "string":
                raise ValueError(f"{where}: an {kind} is text, and this field is "
                                 f"{field.get('data_type')}.")
            if field.get("type") == "link" or is_computed(field):
                raise ValueError(f"{where}: a value type describes a stored value.")
            if kind == "phone":
                from core.ontology.value_checks import check_phone_setting

                check_phone_setting(setting, where)
            constraints = field.setdefault("constraints", {})
            constraints.setdefault(kind, setting)
            if field.get("standardise") is not False:
                rules = field.setdefault("standardise", {})
                rules.setdefault(kind, setting)


def canonical_key(value, field: Mapping) -> str:
    """The text identity matching compares for this value: canonical
    for a declared value type, the value's own text otherwise. A value
    the library cannot read keys as itself -- it matches only itself,
    which is the safe failure for a match key."""
    text = str(value)
    found = value_type_of(field)
    if found is None:
        return text
    kind, setting = found
    if kind == "email":
        from core.ontology.value_checks import email_normalised

        return email_normalised(text.strip()).casefold()
    if kind == "phone":
        from core.ontology.value_checks import phone_e164

        return phone_e164(text.strip(), setting)
    return text
