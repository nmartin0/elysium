"""The set on screen, said in words for the agent (DEV_UI 5.4).

"THE AGENT EVERYWHERE: 'ask about this set' inside Browse, seeded with
what is on screen. Elysium's actual edge over the prior art, where AI
sits alongside rather than inside." Browse used to send a phrase --
"About the 404 Transaction objects matching 2 filters:" -- which named
how many filters and not what they were, so the agent had to guess
which 404 were meant.

NOW IT SENDS THE SET ITSELF -- the type, the text search, the conditions
-- and this turns it into a sentence appended to the question, in the
ontology's own display names:

    This question is about the Transaction objects whose Category is
    one of refund, hardware and whose Amount is at least 100.

WHY A SENTENCE AND NOT A STRUCTURE IN THE PROMPT. The step prompt is
byte-identical across hops and across questions, and changing it is a
measured change (core/llm/agent_features.py); a question that says more
is not. The agent reads the set the way it reads any question, under
the asker's own grants: the conditions narrow what they may already
see, so passing them trusts nothing a client could abuse.

VALIDATED HERE, NOT TRUSTED. The type must be one the asker may see and
every field one they may read -- against their visible schema, so an
unknown field and a hidden one are refused alike (uniform denial) --
and each condition must be well-formed in the filter vocabulary.
"""

from core.filters import FieldFilter, FilterError, parse_filters, validate_filter

#: How much of the question the set may add. A set filtered on a list of
#: two hundred ids is described by its count, not read out.
MAX_VALUES_LISTED = 12


class SetContextError(ValueError):
    """The set cannot be described for this asker."""


def field_label(fields: dict, field: str) -> str:
    """A field's display name, or its api name made readable."""
    return str((fields.get(field) or {}).get("display_name") or field.replace("_", " ").capitalize())


def _values(values) -> str:
    shown = [str(value) for value in values[:MAX_VALUES_LISTED]]
    more = len(values) - len(shown)
    return ", ".join(shown) + (f" and {more} more" if more > 0 else "")


def condition_clause(condition: FieldFilter, fields: dict) -> str:
    """One condition as a relative clause -- "whose Amount is at least
    100". Shared with core/agent/answer_context.py, so a set described
    to the agent and a step read back to a person say it the same way."""
    name, value, operator = field_label(fields, condition.field), condition.value, condition.operator
    if operator == "equals":
        return f"whose {name} is {value}"
    if operator == "in":
        return f"whose {name} is one of {_values(value)}"
    if operator == "not_in":
        return f"whose {name} is none of {_values(value)}"
    if operator == "contains":
        return f"whose {name} contains {value!r}"
    if operator in ("range", "date_range"):
        low = value.get("min" if operator == "range" else "start")
        high = value.get("max" if operator == "range" else "end")
        if low is not None and high is not None:
            return f"whose {name} is between {low} and {high}"
        return f"whose {name} is at least {low}" if low is not None else f"whose {name} is at most {high}"
    if operator == "relative_date":
        since, until = value.get("since_days_ago"), value.get("until_days_ago")
        if since is not None and until is not None:
            return f"whose {name} is from {since} to {until} days ago"
        return (f"whose {name} is within the last {since} days" if since is not None
                else f"whose {name} is more than {until} days ago")
    raise SetContextError(f"no words for the operator {operator!r}")


def describe_set(visible_schema: dict, object_type: str, conditions_raw=None,
                 text: str = "") -> str:
    """The sentence. Raises SetContextError for a set this asker could not
    have built -- an unknown or unreadable type or field, or a malformed
    condition."""
    type_def = (visible_schema or {}).get(object_type)
    if type_def is None:
        raise SetContextError("Unknown set")
    fields = type_def.get("fields") or {}
    try:
        conditions = parse_filters(conditions_raw or [])
    except FilterError as e:
        raise SetContextError(str(e)) from e
    clauses = []
    for condition in conditions:
        if condition.field not in fields:
            # The same answer for absent and unreadable.
            raise SetContextError("Unknown set")
        try:
            validate_filter(condition, (fields.get(condition.field) or {}).get("data_type"))
        except FilterError as e:
            raise SetContextError(str(e)) from e
        clauses.append(condition_clause(condition, fields))
    if text.strip():
        clauses.append(f"matching the search {text.strip()!r}")
    described = f"the {object_type} objects" + (" " + " and ".join(clauses) if clauses else "")
    return f"This question is about {described}."


def question_about(question: str, sentence: str) -> str:
    """The question as the agent receives it: the asker's words first, the
    set after, so the asker's question is never rewritten."""
    return f"{question.rstrip()}\n\n{sentence}"
