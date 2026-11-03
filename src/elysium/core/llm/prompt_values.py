"""How a served value is written into a prompt (PA001-X2, G12, LB-5).

THE CRASH THIS EXISTS FOR. The mediator coerces every value to its
DECLARED type, so a `decimal` field is a decimal.Decimal and a `date`
field a datetime.date. `json.dumps` raises TypeError on both. The step
prompt serialises gathered results with json.dumps, so in the SHIPPED
configuration -- where Transaction.amount is declared decimal,
deliberately, for money -- the agent could not answer a question that
read an amount or a date. It raised out of the loop and the /query
request failed.

No existing agent test could see it: they mock the mediator and return
floats and strings. It took driving the real loop over a real mediator,
which is what the pipeline test tier does.

RENDERED AT THE DECLARED SCALE, NOT THE STORED ONE. A decimal is stored
at the column's scale (49.990000000) and declared with decimal_places
(2). The model should see what the ontology says the value IS, so
`decimal_places` wins where it is declared. That is the same rendering
question as PA001-G12 (live path 10.50, mirror 10.500000000), answered
once here rather than differently in each place.

WHY A STRING AND NOT A FLOAT for decimals: a float is a different
number. Decimal("12345678901234567.89") does not survive the trip, and
money is exactly the field type someone chose decimal for.

ONE PLACE, USED BY EVERY PROMPT BUILDER. The audit's own fix note, and
the reason this is a module rather than a `default=` lambda at the call
site: the next prompt builder to serialise a value must not have to
rediscover any of the above.
"""

import datetime
import decimal
import json
from typing import Any

# The ontology's field config key that says how a decimal should read.
DECIMAL_PLACES = "decimal_places"


def render_value(value: Any, field_config: dict | None = None) -> Any:
    """One value, in the form a model should read it.

    Anything json.dumps already handles is returned unchanged, so this
    is cheap and leaves strings, numbers, booleans and None alone.
    """
    if isinstance(value, decimal.Decimal):
        places = (field_config or {}).get(DECIMAL_PLACES)
        if places is not None:
            try:
                quantised = value.quantize(decimal.Decimal(1).scaleb(-int(places)))
                return f"{quantised:f}"
            except (decimal.InvalidOperation, ValueError, TypeError):
                pass  # an undeclarable scale is still better shown than crashed
        # NORMALISED, so a storage-scale 10.500000000 reads as 10.5
        # rather than teaching the model that money has nine places.
        return f"{value.normalize():f}"
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [render_value(item, field_config) for item in value]
    if isinstance(value, dict):
        return {key: render_value(item, field_config) for key, item in value.items()}
    return value


def _fields_for(visible_schema: dict, object_type: Any) -> dict:
    entry = (visible_schema or {}).get(object_type) or {}
    return entry.get("fields") or {}


def render_gathered(gathered: list[dict], visible_schema: dict | None = None) -> list[dict]:
    """The gathered steps, with every value renderable.

    USES THE STEP'S OWN object_type AND field_name to find the field's
    declaration, so `decimal_places` applies where it is declared.
    Where a step does not say (or the type is not visible), values fall
    back to the normalised form -- correct, just not scale-aware.
    """
    out = []
    for step in gathered:
        if not isinstance(step, dict):
            out.append(render_value(step))
            continue
        fields = _fields_for(visible_schema or {}, step.get("object_type"))
        rendered = {}
        for key, value in step.items():
            if key != "result":
                rendered[key] = render_value(value)
                continue
            named = step.get("field_name")
            if isinstance(value, dict) and not named:
                # get_object: {object_id: {field: value}} -- each field
                # carries its own declaration.
                rendered[key] = {
                    object_id: {
                        field: render_value(item, fields.get(field))
                        for field, item in (per_object or {}).items()
                    } if isinstance(per_object, dict) else render_value(per_object)
                    for object_id, per_object in value.items()
                }
            else:
                rendered[key] = render_value(value, fields.get(named))
        out.append(rendered)
    return out


def dumps_gathered(gathered: list[dict], visible_schema: dict | None = None) -> str:
    """render_gathered, as the JSON a prompt embeds.

    `default=str` is a LAST RESORT, not the mechanism: every type the
    ontology can serve is handled above. It is here so that a future
    declared type cannot crash a running agent while somebody adds it
    to render_value.
    """
    return json.dumps(render_gathered(gathered, visible_schema), default=str)
