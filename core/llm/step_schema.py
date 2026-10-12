"""The step vocabulary as a JSON Schema, for constrained decoding (AR-5).

"CONSTRAIN THE STEP CHOICE FULLY; KEEP SYNTHESIS FREE." The research
behind AR-5 is "Let Me Speak Freely?" (Tam et al., 2024): format
restrictions measurably degrade a model's REASONING, and do not hurt --
often help -- tasks whose answer IS a structure. A step is a structure;
synthesis is prose. So the step call is constrained and synthesis is
not, which is the split this module exists to make possible.

WHAT IT CONSTRAINS IS WHAT THE BENCH MEASURED GOING WRONG. On the
deployment's own model, 2026-10-11 (BLOCKING 13), every step-mode
failure began with a value the schema below cannot express: a field
named "count", the id field `transaction_id`, a wildcard "*", a list
inside a one-value filter, an invented step name. Each is now outside
the grammar, so the model cannot emit it -- where before it emitted it,
was refused, and spent a hop (a minute on that hardware) learning so.

WHAT IT DOES NOT CONSTRAIN, deliberately: ids. They come from results
the model has read, change every hop, and the loop's own guards already
check them against what this run holds. Values in filters are likewise
free scalars -- their types are checked by `_check_filter_types`, which
can say what was wrong; a grammar could only forbid.

GENERATED FROM THE CALLER'S VISIBLE SCHEMA, so the grammar admits
exactly the types and fields this user may read, and nothing else --
the same filtering the prompt's own schema description gets.

THE SERVER DOES THE WORK. Ollama's `format` accepts a JSON Schema
("structured outputs") and llama.cpp compiles it to a grammar that
masks every token that would leave it; vLLM's `response_format` with
`json_schema` is the OpenAI-compatible equivalent. Nothing here parses
or validates -- next_step() still checks every reply exactly as before,
because a server that ignores the schema must still be safe.
"""

from core.functions.interface import Function
from core.ontology.schema import is_searchable_field

AGGREGATES = ("count", "sum", "avg", "min", "max")

_SCALAR = {"type": ["string", "number", "integer", "boolean"]}
_ID = {"type": ["string", "integer"]}


def _step(name: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        # "step" FIRST, in properties and in required, because a grammar
        # emits keys in schema order -- the model commits to what kind
        # of step it is writing before anything else, as the prompt's
        # own examples show it.
        "properties": {"step": {"const": name}, **properties},
        "required": ["step", *required],
        "additionalProperties": False,
    }


def _enum(names) -> dict:
    return {"enum": sorted(names)}


#: A date or time written the one way the executor reads it.
#: MEASURED: the constrained bench run sent {"transaction_date": "2"},
#: which the grammar admitted and the executor refused as not ISO-8601
#: -- a hop spent on a value the schema could have ruled out. A handle
#: is admitted too, so a plan can still pass one along.
_TEMPORAL = {"type": "string",
             "pattern": "^([0-9]{4}-[0-9]{2}-[0-9]{2}.*|\\$[A-Za-z_][A-Za-z0-9_]*)$"}
_TEMPORAL_TYPES = frozenset({"date", "timestamp", "timestamptz"})


def _value_for(info: dict) -> dict:
    data_type = str(info.get("data_type") or "").partition("@")[0]
    return _TEMPORAL if data_type in _TEMPORAL_TYPES else _SCALAR


def _filter(fields: dict, searchable: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {name: _value_for(fields[name]) for name in sorted(searchable)},
        "additionalProperties": False,
    }


#: A plan step's own id, and a handle naming one -- core/llm/plan.py's
#: _STEP_ID and _HANDLE, which decide what the executor accepts.
_STEP_ID = {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"}
_HANDLE = {"type": "string", "pattern": "^\\$[A-Za-z_][A-Za-z0-9_]*$"}
#: An id written out in a plan's list: anything but a handle. A handle
#: INSIDE a list is the bench's wrapped-handle mistake.
_PLAN_ID = {"anyOf": [{"type": "integer"}, {"type": "string", "pattern": "^[^$].*$"}]}


def _steps_for_type(object_type: str, definition: dict, in_plan: bool = False) -> list[dict]:
    fields = definition.get("fields") or {}
    if not fields:
        return []
    readable = list(fields)
    searchable = [name for name, info in fields.items() if is_searchable_field(info)]
    data = [name for name, info in fields.items() if info.get("type") == "data"]
    links = [name for name, info in fields.items() if info.get("type") == "link"]
    this_type = {"const": object_type}

    steps = [
        _step("get_field", {"object_type": this_type, "object_id": _ID,
                            "field_name": _enum(readable)},
              ["object_type", "object_id", "field_name"]),
        _step("get_object", {"object_type": this_type,
                             # IN A PLAN, A HANDLE STANDS FOR THE LIST -- and
                             # bare, never wrapped: the bench's plan wrote
                             # ["$b"] and found nothing (plan.py says why).
                             "object_ids": ({"anyOf": [_HANDLE, {"type": "array",
                                                                 "items": _PLAN_ID,
                                                                 "minItems": 1}]}
                                            if in_plan else
                                            {"type": "array", "items": _ID, "minItems": 1}),
                             "field_names": {"type": "array", "items": _enum(readable),
                                             "minItems": 1}},
              ["object_type", "object_ids", "field_names"]),
    ]
    if searchable:
        steps.append(_step("search_object", {"object_type": this_type,
                                             "filter": _filter(fields, searchable)},
                           ["object_type", "filter"]))
    aggregate = {"object_type": this_type, "filter": _filter(fields, searchable),
                 "aggregate": _enum(AGGREGATES)}
    if data:
        # DATA ONLY, BOTH. A link is not aggregatable -- the mediator
        # refuses it -- and the constrained bench run spent a hop on
        # group_by "customer_id" because this once admitted it.
        aggregate["field_name"] = _enum(data)
        aggregate["group_by"] = _enum(data)
    steps.append(_step("aggregate_object", aggregate, ["object_type", "aggregate"]))
    if links:
        steps.append(_step("search_around", {"object_type": this_type,
                                             "filter": _filter(fields, searchable),
                                             "link_field": _enum(links)},
                           ["object_type", "link_field"]))
    return steps


def step_schema(visible_schema: dict, tools: list[Function], writes_enabled: bool,
                visible_action_types: dict) -> dict:
    """Every step this caller may take, as one JSON Schema.

    THE SAME ARGUMENTS AS THE SYSTEM PROMPT, so what the prompt offers
    and what the grammar admits cannot drift: a tool not listed is not
    callable, an action not visible cannot be proposed.
    """
    variants: list[dict] = [_step("finish", {}, [])]
    for object_type, definition in visible_schema.items():
        variants.extend(_steps_for_type(object_type, definition))
    if tools:
        variants.append(_step("use_tool", {"tool_name": _enum(tool.name for tool in tools),
                                           "args": {"type": "object"}},
                              ["tool_name", "args"]))
    if writes_enabled and visible_action_types:
        variants.append(_step("propose_action",
                              {"action_type": _enum(visible_action_types),
                               "parameters": {"type": "object"}},
                              ["action_type", "parameters"]))
    return {"anyOf": variants}


def plan_schema(visible_schema: dict, tools: list[Function], writes_enabled: bool,
                visible_action_types: dict, max_steps: int) -> dict:
    """A whole plan (AL-4) as one JSON Schema: the same steps, each with
    an id, at most `max_steps` of them, and no finish.

    THE BENCH'S PLAN FAILURES, 2026-10-11: a list inside a one-value
    filter, a handle wrapped in a list, and 26 steps against max_hops 8.
    The first two are outside the step branches; the third is
    `maxItems`. Each cost a re-plan, a minute or more of a CPU model's
    time, and the third failed the case outright.
    """
    items: list[dict] = []
    for object_type, definition in visible_schema.items():
        items.extend(_steps_for_type(object_type, definition, in_plan=True))
    if tools:
        items.append(_step("use_tool", {"tool_name": _enum(tool.name for tool in tools),
                                        "args": {"type": "object"}},
                           ["tool_name", "args"]))
    for item in items:
        # "id" FIRST, before "step", because that is the order the plan
        # instructions show and the executor reads.
        item["properties"] = {"id": _STEP_ID, **item["properties"]}
        item["required"] = ["id", *item["required"]]
    return {
        "type": "object",
        "properties": {"plan": {"type": "array", "items": {"anyOf": items},
                                "minItems": 1, "maxItems": max_steps}},
        "required": ["plan"],
        "additionalProperties": False,
    }
