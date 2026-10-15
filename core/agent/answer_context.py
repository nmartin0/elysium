"""What comes with an answer: how it was understood, where it leads, and
what to ask next (BLOCKING "What the Query screen should contain").

THE QUESTION, READ BACK. Power BI's Q&A restates a question under the
box, and ThoughtSpot shows the tokens it interpreted -- both so a person
can see what the system took them to mean before trusting the number.
Those restatements come from a parser that runs BEFORE the answer.
Elysium's understanding is the agent's steps, so the read-back is those
steps in the ontology's own words: "Found 1 Customer whose Name is Ada
Okafor", "Counted Transactions whose Customer is cust_001". It is what
was DONE, which is the stronger claim -- a restatement can be right
about the question and the agent still wrong about what it fetched.

NO EXTRA MODEL CALL, which is the reason clarifying questions were
refused: the model is already the slow part. Everything here is
deterministic, from the record the loop already keeps.

FOLLOW-ON QUESTIONS, EACH ONE WHOLE. A conversation thread was refused
-- "threading makes 'which generation answered this' much harder to
state" -- so a follow-on is a complete question someone could have
typed, never "and her tickets?": "What support tickets does Ada Okafor
have?". Picking one puts it in the box; asking it is a fresh question.

TWO THINGS DELIBERATELY NOT BUILT, kept here because the planning item
that recorded them is gone. CLARIFYING QUESTIONS before answering: an
extra model call on a system where the model is already the slow part,
for a problem nobody has reported. A CONVERSATION THREAD: Elysium
answers questions about an ontology, it is not a chat assistant, and
threading makes "which generation answered this" much harder to state.

DOORS. An answer that names an object should lead to it, and one built
from a set should open that set in Browse -- DEV_UI's dead end, "a
search gives rows; the rows do not become a THING", applied to answers.

NOTHING HERE THE ANSWER COULD NOT SAY. Built only from
AgentLoop.filter_real_data(gathered) -- what synthesis receives, denied
reads already stripped -- and named from the agent's own visible
schema. A refused read is not "read back", which would reconstruct
exactly what uniform denial hides; the access trace, which is the
caller's own audit of their own request, is where refusals belong.
"""

from core.agent.set_context import condition_clause, field_label
from core.filters import FilterError, agent_conditions

#: Enough to show how an answer was reached; more is the trace's job.
MAX_READ_BACK = 8
MAX_FOLLOW_ONS = 3
MAX_DOORS = 3

_AGGREGATE_WORDS = {
    "count": "Counted",
    "sum": "Added up",
    "avg": "Averaged",
    "min": "Found the lowest",
    "max": "Found the highest",
}


def _type_label(schema: dict, object_type: str, count: int | None = None) -> str:
    type_def = schema.get(object_type) or {}
    if count == 1:
        return str(type_def.get("display_name") or object_type)
    return str(type_def.get("plural_display_name") or type_def.get("display_name") or object_type)


def _is_handle(value) -> bool:
    return isinstance(value, str) and value.startswith("$")


def _conditions_of(step_filter) -> list | None:
    """The agent's filter as conditions, or None when it cannot be said:
    a plan handle stands for an earlier step's result, and describing it
    as a literal "$a" would be a sentence about nothing."""
    if not isinstance(step_filter, dict):
        return []
    if any(_is_handle(value) or (isinstance(value, list) and any(_is_handle(v) for v in value))
           for value in step_filter.values()):
        return None
    try:
        return agent_conditions(step_filter)
    except FilterError:
        return None


def _where(schema: dict, object_type: str, step_filter) -> str:
    conditions = _conditions_of(step_filter)
    if not conditions:
        return ""
    fields = (schema.get(object_type) or {}).get("fields") or {}
    try:
        return " " + " and ".join(condition_clause(condition, fields) for condition in conditions)
    except ValueError:
        return ""


def _count(entry: dict) -> int | None:
    result = entry.get("result")
    if isinstance(entry.get("total"), int):
        return entry["total"]
    return len(result) if isinstance(result, list) else None


def _titles(gathered: list[dict]) -> dict[tuple[str, str], str]:
    """Every display name the loop fetched, by (type, id)."""
    titles: dict[tuple[str, str], str] = {}
    for entry in gathered:
        object_type = str(_target_type(entry) or entry.get("object_type") or "")
        for object_id, title in (entry.get("titles") or {}).items():
            if title:
                titles[(object_type, str(object_id))] = str(title)
    return titles


def _target_type(entry: dict) -> str | None:
    # search_around's ids and titles are of the LINK'S TARGET, which the
    # entry records nowhere but in the schema; resolved by the caller.
    return entry.get("_target")


def _annotate_targets(gathered: list[dict], schema: dict) -> list[dict]:
    annotated = []
    for entry in gathered:
        if entry.get("step") == "search_around":
            fields = (schema.get(entry.get("object_type")) or {}).get("fields") or {}
            target = (fields.get(entry.get("link_field")) or {}).get("target")
            entry = {**entry, "_target": target}
        annotated.append(entry)
    return annotated


def read_back(real_data: list[dict], schema: dict) -> list[str]:
    """What the agent did to answer, one sentence a step, in order."""
    gathered = _annotate_targets(real_data, schema)
    titles = _titles(gathered)
    sentences: list[str] = []
    reads: dict[tuple[str, str], list[str]] = {}

    def flush_reads():
        for (object_type, object_id), names in reads.items():
            fields = (schema.get(object_type) or {}).get("fields") or {}
            named = [field_label(fields, name) for name in names]
            labels = named[0] if len(named) == 1 else f"{', '.join(named[:-1])} and {named[-1]}"
            who = titles.get((object_type, object_id), object_id)
            sentences.append(f"Read {labels} of {_type_label(schema, object_type, 1)} {who}")
        reads.clear()

    for entry in gathered:
        step = entry.get("step")
        object_type = entry.get("object_type") or ""
        if step == "get_field":
            key = (object_type, str(entry.get("object_id")))
            reads.setdefault(key, [])
            field_name = str(entry.get("field_name") or "")
            if field_name and field_name not in reads[key]:
                reads[key].append(field_name)
            continue
        flush_reads()
        if step == "search_object":
            count = _count(entry)
            found = "no" if count == 0 else str(count)
            sentences.append(f"Found {found} {_type_label(schema, object_type, count)}"
                             f"{_where(schema, object_type, entry.get('filter'))}")
        elif step == "search_text":
            count = _count(entry)
            sentences.append(f"Searched {_type_label(schema, object_type)} for {entry.get('text')!r} "
                             f"and found {count if count else 'none'}")
        elif step == "search_around":
            target = entry.get("_target") or "objects"
            count = _count(entry)
            fields = (schema.get(object_type) or {}).get("fields") or {}
            sentences.append(
                f"Followed {field_label(fields, entry.get('link_field', ''))} from the "
                f"{_type_label(schema, object_type)}{_where(schema, object_type, entry.get('filter'))}"
                f" to {count if count is not None else 'some'} {_type_label(schema, target, count)}")
        elif step == "aggregate_object":
            fields = (schema.get(object_type) or {}).get("fields") or {}
            verb = _AGGREGATE_WORDS.get(str(entry.get("aggregate")), "Summarised")
            measured = (f" {field_label(fields, entry['field_name'])} across"
                        if entry.get("field_name") and entry.get("aggregate") != "count" else "")
            by = f", by {field_label(fields, entry['group_by'])}" if entry.get("group_by") else ""
            sentences.append(f"{verb}{measured} {_type_label(schema, object_type)}"
                             f"{_where(schema, object_type, entry.get('filter'))}{by}")
        elif step == "use_tool":
            sentences.append(f"Used {entry.get('tool_name')}")
    flush_reads()

    # The same step twice reads as the same sentence twice; once is the fact.
    unique = list(dict.fromkeys(sentences))
    if len(unique) > MAX_READ_BACK:
        hidden = len(unique) - (MAX_READ_BACK - 1)
        return [*unique[: MAX_READ_BACK - 1], f"and {hidden} more steps"]
    return unique


def doors(real_data: list[dict], schema: dict) -> list[dict]:
    """Where the answer leads: the objects it is about, and the sets it
    counted or listed, when Browse can show exactly that set.

    A SET ONLY WHEN BROWSE CAN SAY IT EXACTLY. Browse's URL filters are
    one-of lists; a range or a text match has no form there, and a door
    to "Transactions" for "Transactions over 100" would open a different
    set under the same words. So those get no door rather than a wrong one.
    """
    gathered = _annotate_targets(real_data, schema)
    titles = _titles(gathered)
    found: list[dict] = []
    seen: set = set()

    def add(door: dict, key):
        if key not in seen and len(found) < MAX_DOORS:
            seen.add(key)
            found.append(door)

    for entry in gathered:
        step = entry.get("step")
        object_type = entry.get("object_type") or ""
        result = entry.get("result")
        if step in ("search_object", "search_around", "search_text") and isinstance(result, list):
            type_of_ids = entry.get("_target") or object_type
            if len(result) == 1 and type_of_ids in schema:
                object_id = str(result[0])
                add({"kind": "object", "object_type": type_of_ids, "object_id": object_id,
                     "label": titles.get((type_of_ids, object_id), object_id)},
                    ("object", type_of_ids, object_id))
            elif len(result) > 1 and step == "search_object":
                browse = _browse_filters(entry.get("filter"))
                if browse is not None:
                    count = _count(entry)
                    add({"kind": "set", "object_type": object_type, "filters": browse,
                         "label": f"{count} {_type_label(schema, object_type, count)}"},
                        ("set", object_type, repr(browse)))
        elif step == "aggregate_object":
            browse = _browse_filters(entry.get("filter"))
            if browse is not None:
                add({"kind": "set", "object_type": object_type, "filters": browse,
                     "label": f"The {_type_label(schema, object_type)} counted"
                     if entry.get("aggregate") == "count"
                     else f"The {_type_label(schema, object_type)} summarised"},
                    ("set", object_type, repr(browse)))
        elif step == "get_field" and object_type in schema:
            object_id = str(entry.get("object_id"))
            add({"kind": "object", "object_type": object_type, "object_id": object_id,
                 "label": titles.get((object_type, object_id), object_id)},
                ("object", object_type, object_id))
    return found


def _browse_filters(step_filter) -> list[dict] | None:
    """The filter as Browse's {field, values, mode}, or None if it has no
    exact form there."""
    conditions = _conditions_of(step_filter)
    if conditions is None:
        return None
    browse = []
    for condition in conditions:
        if condition.operator == "equals":
            browse.append({"field": condition.field, "values": [str(condition.value)], "mode": "keep"})
        elif condition.operator in ("in", "not_in"):
            browse.append({"field": condition.field, "values": [str(v) for v in condition.value],
                           "mode": "keep" if condition.operator == "in" else "exclude"})
        else:
            return None
    return browse


def follow_ons(question: str, real_data: list[dict], schema: dict) -> list[str]:
    """Questions worth asking next, each complete on its own."""
    gathered = _annotate_targets(real_data, schema)
    titles = _titles(gathered)
    suggestions: list[str] = []

    # WHAT ELSE IS ATTACHED TO THE ONE THING THE ANSWER WAS ABOUT: its
    # links the agent did not follow. Only for a single object with a
    # name -- "What tickets does cust_001 have?" reads as a database
    # query, not a question.
    subject = next((door for door in doors(real_data, schema)
                    if door["kind"] == "object"
                    and (door["object_type"], door["object_id"]) in titles), None)
    if subject is not None:
        type_def = schema.get(subject["object_type"]) or {}
        followed = {entry.get("link_field") for entry in gathered
                    if entry.get("step") == "search_around"
                    and entry.get("object_type") == subject["object_type"]}
        for name, field in sorted((type_def.get("fields") or {}).items()):
            if field.get("type") != "link" or name in followed or field.get("target") not in schema:
                continue
            label = field_label(type_def.get("fields") or {}, name).lower()
            many = "many" in str(field.get("cardinality") or "").split("_to_")[-1]
            suggestions.append(f"What {label} does {subject['label']} have?" if many
                               else f"What is the {label} of {subject['label']}?")
            if len(suggestions) >= 2:
                break

    # A SINGLE NUMBER, BROKEN DOWN: the question as asked, by a field
    # that could split it. One suggestion, from the type's own fields in
    # declaration order -- the author's order is the best guess at what
    # matters, and a guess is all this is.
    total = next((entry for entry in gathered
                  if entry.get("step") == "aggregate_object" and not entry.get("group_by")), None)
    if total is not None:
        type_def = schema.get(total.get("object_type")) or {}
        skip = {type_def.get("id_field"), type_def.get("title_field"), total.get("field_name")}
        candidate = next((name for name, field in (type_def.get("fields") or {}).items()
                          if field.get("type") != "link" and name not in skip
                          and field.get("data_type") in (None, "string")), None)
        if candidate is not None:
            label = field_label(type_def.get("fields") or {}, candidate).lower()
            asked = question.strip().rstrip("?.!").strip()
            if asked:
                suggestions.append(f"{asked}, broken down by {label}?")

    return list(dict.fromkeys(suggestions))[:MAX_FOLLOW_ONS]
