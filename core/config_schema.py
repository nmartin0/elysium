"""
config_schema.py  (the SHAPE of every configuration file, once)

WHAT THIS REFUSES: a key nothing reads. `agnet:` for `agent:`,
`max_hop` for `max_hops`, `submission_criterias` for
`submission_criteria`, a field's `colum:` -- each used to load cleanly
and do nothing, so a misspelling looked exactly like a setting that
was working. Now the load stops and says which file, which key, and
the nearest key that exists:

    config.yaml: unknown key `agent.max_hop`; did you mean `max_hops`?

ONE MODEL PER FILE, pydantic with extra="forbid": config.yaml,
ontology_schema.yaml (and source_bindings.yaml, whose keys are the
binding half of the same objects), policy.yaml (roles and users) and
data_silos.yaml (silos). The models name KEYS and the structure that
holds them. They deliberately do not re-check VALUES: the checks that
already exist (whole numbers, the choice lists, the cross references
between files) stay where they are, one place each, and run after
this. A value of the wrong type is therefore not reported here; only
a key that is not on the list is.

WHERE A BLOCK ALREADY REFUSES ITS OWN UNKNOWN KEYS, it is `Any` here
and its own check speaks: triggers (core/declared_triggers.py),
constraints, field rules, deprecation, lineage, freshness targets,
unusual checks, value types, and so on. Writing their key lists a
second time would be the drift this file exists to end. The same goes
for what is free-form by design: an adapter's `connection`, the
mirror's `storage` options.

A KEY ADDED TO THE LOADER MUST BE ADDED HERE, or a deployment that
uses it is refused. tests/unit/test_config_schema.py loads every
shipped configuration through these models.

A leaf module: it imports pydantic and the standard library only, so
the loader, the linter and the editors can all use it.
"""

import difflib
import types
import typing
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- config.yaml ----------------------------------------------------------

class _Llm(_Strict):
    provider: Any = None
    connection: Any = None
    model: Any = None
    step_model: Any = None
    synthesis_model: Any = None
    embedding_model: Any = None
    embedding_budget_seconds: Any = None
    embedding_dimensions: Any = None
    embedding_prefixes: Any = None
    embedding_connection: Any = None


class _Agent(_Strict):
    max_hops: Any = None
    max_consecutive_duplicates: Any = None
    max_consecutive_invalid_steps: Any = None
    query_deadline_seconds: Any = None
    constrain_steps: Any = None
    max_tokens_per_query: Any = None
    max_concurrent_requests: Any = None
    filter_operators: Any = None
    search_result_cap: Any = None
    free_text_search: Any = None
    remember_from_query: Any = None
    meaning_search: Any = None
    brief_answers: Any = None
    answer_max_tokens: Any = None


class _Writes(_Strict):
    pending_write_ttl_minutes: Any = None


class _Access(_Strict):
    label_enforcement: Any = None


class _Tools(_Strict):
    enabled: Any = None


class _Mirror(_Strict):
    storage: Any = None
    identity_inference: Any = None
    retain_publications: Any = None
    # Refused by the loader with its own explanation (GOLD-9); named
    # here so that message, not "unknown key", is what an author reads.
    read_from_mirror: Any = None


class _Freshness(_Strict):
    sync_interval_hours: Any = None


class ConfigFile(_Strict):
    """config.yaml."""
    llm: _Llm | None = None
    agent: _Agent | None = None
    tools: _Tools | None = None
    writes: _Writes | None = None
    access: _Access | None = None
    mirror: _Mirror | None = None
    freshness: _Freshness | None = None
    lineage: Any = None
    triggers: Any = None
    write_targets: Any = None
    trusted_proxies: Any = None
    on_type_mismatch: Any = None
    on_suspected_rename: Any = None
    ingest_undeclared_columns: Any = None
    source_locale: Any = None
    bulk_action_limit: Any = None
    deprecation_lead_days: Any = None


# --- ontology_schema.yaml / source_bindings.yaml --------------------------

class _Storage(_Strict):
    silo: Any = None
    table: Any = None
    id_column: Any = None
    id_type: Any = None


class _Field(_Strict):
    type: Any = None
    data_type: Any = None
    description: Any = None
    display_name: Any = None
    classification: Any = None
    cardinality: Any = None
    target: Any = None
    via_field: Any = None
    decimal_places: Any = None
    required: Any = None
    timezone: Any = None
    visibility: Any = None
    status: Any = None
    deprecation: Any = None
    # where the value comes from (the bindings half)
    column: Any = None
    storage: Any = None
    via_table: Any = None
    via_column: Any = None
    via_target_column: Any = None
    # blocks that check their own keys
    constraints: Any = None
    on_violation: Any = None
    standardise: Any = None
    outliers: Any = None
    survivorship: Any = None
    derived: Any = None
    enrich: Any = None
    predict: Any = None
    value_type: Any = None


class _ObjectType(_Strict):
    description: Any = None
    display_name: Any = None
    plural_display_name: Any = None
    id_field: Any = None
    title_field: Any = None
    fields: dict[str, _Field | None] | None = None
    security: Any = None
    storage: _Storage | None = None
    additional_storage: Any = None
    discoverable: Any = None
    icon: Any = None
    color: Any = None
    group: Any = None
    status: Any = None
    deprecation: Any = None
    # blocks that check their own keys
    rules: Any = None
    dependencies: Any = None
    identity: Any = None
    semantic_search: Any = None
    survivorship: Any = None
    unusual: Any = None
    freshness: Any = None


class _LinkType(_Strict):
    source: Any = None
    target: Any = None
    cardinality: Any = None
    foreign_key_column: Any = None
    join_table: Any = None
    display_name: Any = None
    description: Any = None
    status: Any = None
    deprecation: Any = None


class _Parameter(_Strict):
    type: Any = None
    object_type: Any = None
    required: Any = None
    default_to_current_object: Any = None
    display_name: Any = None
    description: Any = None


class _Mutation(_Strict):
    set: Any = None


class _SubWrite(_Strict):
    object_type: Any = None
    object_id: Any = None
    operation: Any = None
    mutations: list[_Mutation | None] | None = None
    submission_criteria: Any = None  # each criterion checks its own keys


class _ActionType(_Strict):
    description: Any = None
    display_name: Any = None
    affected_object_types: Any = None
    parameters: dict[str, _Parameter | None] | None = None
    sub_writes: list[_SubWrite | None] | None = None
    auto_execute: Any = None
    automatable: Any = None
    owner_may_approve_automation: Any = None
    status: Any = None
    deprecation: Any = None
    # Not a valid key HERE: criteria belong to each sub_write, and
    # core/ontology/submission_criteria.py refuses this one by name,
    # which says where they go. Accepted by the shape so that message,
    # not "unknown key", is what an author reads.
    submission_criteria: Any = None


class OntologyFile(_Strict):
    """ontology_schema.yaml."""
    object_types: dict[str, _ObjectType | None] | None = None
    link_types: dict[str, _LinkType | None] | None = None
    action_types: dict[str, _ActionType | None] | None = None


class _BoundField(_Strict):
    column: Any = None
    storage: Any = None
    via_table: Any = None
    via_column: Any = None
    via_target_column: Any = None


class _BoundType(_Strict):
    storage: _Storage | None = None
    additional_storage: Any = None
    fields: dict[str, _BoundField | None] | None = None


class BindingsFile(_Strict):
    """source_bindings.yaml: where each object type's data comes from."""
    object_types: dict[str, _BoundType | None] | None = None


# --- policy.yaml -----------------------------------------------------------

class _Role(_Strict):
    allowed_actions: Any = None


class PolicyFile(_Strict):
    """policy.yaml. `users` entries are checked by hand below: their keys
    are `role` and whatever attribute the file names as its
    `security_attribute`."""
    security_attribute: Any = None
    roles: dict[str, _Role | None] | None = None
    users: Any = None


# --- data_silos.yaml -------------------------------------------------------

class _Silo(_Strict):
    adapter: Any = None
    connection: Any = None  # the adapter's own arguments
    locale: Any = None
    security: Any = None
    incremental: Any = None
    excel_dates: Any = None
    zero_dates_as_null: Any = None


class SilosFile(_Strict):
    """data_silos.yaml."""
    data_silos: dict[str, _Silo | None] | None = None


MODELS: dict[str, type[BaseModel]] = {
    "config.yaml": ConfigFile,
    "ontology_schema.yaml": OntologyFile,
    "source_bindings.yaml": BindingsFile,
    "policy.yaml": PolicyFile,
    "data_silos.yaml": SilosFile,
}


# --- walking a model by an error's location -------------------------------

def _models_in(annotation: Any) -> "tuple[type[BaseModel] | None, str | None]":
    """The model an annotation holds, and how it is held: None, "dict" or "list"."""
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        for arg in args:
            found = _models_in(arg)
            if found[0] is not None:
                return found
        return None, None
    if origin is dict and len(args) == 2:
        inner, _ = _models_in(args[1])
        return (inner, "dict") if inner is not None else (None, None)
    if origin is list and args:
        inner, _ = _models_in(args[0])
        return (inner, "list") if inner is not None else (None, None)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation, None
    return None, None


def _model_at(model: type[BaseModel], location: tuple) -> "type[BaseModel] | None":
    """The model that describes the mapping found at `location`."""
    current: type[BaseModel] | None = model
    index = 0
    while index < len(location):
        if current is None or location[index] not in current.model_fields:
            return None
        held, how = _models_in(current.model_fields[location[index]].annotation)
        index += 1
        if held is None:
            return None
        if how is not None:
            index += 1  # the name or position inside the dict or list
        current = held
    return current


def _dotted(location: tuple) -> str:
    """A location as a path: object_types.Customer.fields.name.colum, sub_writes[0]."""
    path = ""
    for part in location:
        path += f"[{part}]" if isinstance(part, int) else (f".{part}" if path else str(part))
    return path


def unknown_key_findings(filename: str, data: Any, *,
                         security_attribute: "str | None" = None) -> list[tuple[tuple, str]]:
    """Every unknown key in a parsed file, as (location, message).

    `location` is the path of keys to the offending one, for callers
    that can point at a line. `filename` picks the model. A file that
    is not a mapping, or a name with no model, yields nothing: those are
    other checks' to make.
    """
    model = MODELS.get(filename)
    if model is None or not isinstance(data, dict):
        return []
    found: list[tuple[tuple, str]] = []
    try:
        model.model_validate(data)
    except ValidationError as error:
        for problem in error.errors():
            if problem["type"] != "extra_forbidden":
                continue  # a wrong VALUE is the existing checks' to report
            location = tuple(problem["loc"])
            owner = _model_at(model, location[:-1])
            valid = sorted(owner.model_fields) if owner is not None else []
            found.append((location, _message(filename, location, valid)))
    if filename == "policy.yaml":
        found += _unknown_user_keys(data, security_attribute)
    elif filename == "ontology_schema.yaml":
        found += _unknown_security_keys(filename, data.get("object_types"))
    return found


def unknown_keys(filename: str, data: Any, *, security_attribute: "str | None" = None) -> list[str]:
    """The messages of unknown_key_findings."""
    return [message for _, message in unknown_key_findings(
        filename, data, security_attribute=security_attribute)]


def _message(filename: str, location: tuple, valid: list[str]) -> str:
    key = str(location[-1])
    text = f"{filename}: unknown key `{_dotted(location)}`"
    near = difflib.get_close_matches(key, valid, n=1, cutoff=0.6)
    if near:
        return f"{text}; did you mean `{near[0]}`?"
    if valid:
        return f"{text}; valid keys here: {', '.join(valid)}."
    return text + "."


#: The keys of a row-security rule written out: `security: {field: region}`.
#: (The word forms, `unrestricted` and `inherit`, are strings, not mappings.)
_SECURITY_KEYS = ("field", "via_field")


def _unknown_security_keys(filename: str, owners: Any) -> list[tuple[tuple, str]]:
    """Unknown keys in each object type's `security:` mapping. A silo's
    own `security:` is refused by core/ontology/silo_security.py, which
    says what it may be."""
    if not isinstance(owners, dict):
        return []
    messages = []
    for name, owner in owners.items():
        security = owner.get("security") if isinstance(owner, dict) else None
        if not isinstance(security, dict):
            continue
        for key in security:
            if key not in _SECURITY_KEYS and key != "unrestricted":  # what `unrestricted` becomes
                location = ("object_types", name, "security", key)
                messages.append((location, _message(filename, location, list(_SECURITY_KEYS))))
    return messages


def _unknown_user_keys(data: dict, security_attribute: "str | None") -> list[tuple[tuple, str]]:
    users = data.get("users")
    if not isinstance(users, dict):
        return []
    attribute = security_attribute if security_attribute is not None else data.get("security_attribute")
    valid = sorted({"role", *([attribute] if isinstance(attribute, str) else [])})
    messages = []
    for user, entry in users.items():
        if not isinstance(entry, dict):
            continue
        for key in entry:
            if key not in valid:
                location = ("users", user, key)
                messages.append((location, _message("policy.yaml", location, valid)))
    return messages

