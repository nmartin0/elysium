"""Which "something changed" hints a caller may be told about.

THE TRANSPORT IS NOT BUILT and this is not it. There is no SSE, no
`EventSource`, no streaming response anywhere in `api/`, and whether
live updates are wanted enough to carry a streaming endpoint is the
owner's call. This is the half that has to be right BEFORE that
decision, not invented under deadline after it.

THE DESIGN DECISION IT SERVES, quoted rather than summarised because
the wording is the point:

    EVENTS CARRY NO DATA. An event says "something of this kind
    changed", never what changed. The client then refetches through
    the SAME authorised endpoints it already uses, so MAC, roles and
    every permission check apply exactly as they do now.

    The alternative -- pushing the changed object down the stream --
    would put a second, parallel read path beside the mediator, and
    every security rule would have to be re-implemented on it
    correctly, forever. That is how leaks happen.

THAT IS THE INDUSTRY'S SECURITY-FIRST ANSWER, not a local preference.
The trade-off is named the same way elsewhere: "rich payloads bypass
authorization -- data in events is accessible to all subscribers
regardless of permission levels", while "notification events preserve
security -- API calls enforce field-level and row-level authorization
properly". The published guidance for regulated data is "never in
events, API with authorization only", and for systems whose consumers
have DIFFERENT authorization levels, "notification + API required".
Elysium authorises per field and per row, so it is squarely that case.

AND THE USUAL OBJECTION DOES NOT APPLY HERE. Thin events are
criticised because "a consumer that receives an ID and immediately
asks you for the record has not been decoupled from you -- it has been
given a slightly slower way to call your API". True, and here the
refetch IS the point: it is where authorization happens. The cost
everyone else complains about is the security property.

WHAT THIS MODULE ADDS. A hint names a TYPE, and a type name is itself
a disclosure: telling someone with no grant on `Customer` that "a
Customer changed" tells them the deployment HAS customers and that
somebody is editing them.

AND IT DOES NOT DECIDE THAT QUESTION ITSELF. `visible_schema` already
answers "which types may this caller know exist", including a type
"whenever discover:{type} is granted". A hint filter that asked again
would be a second place deciding one security rule.
"""

#: What a hint may say about a change. A verb, nothing else -- no id,
#: no field name, no count. "Three Customers changed" is a measurement
#: of data the caller may not be able to read.
CHANGE_KINDS = ("created", "updated", "deleted")


def hints_for(visible_schema: dict, changed_types) -> "list[str]":
    """The types this caller may be told about, from those that changed.

    IT TAKES THE CALLER'S VISIBLE SCHEMA rather than asking its own
    question, and that is the whole design. `DataMediator.visible_schema`
    already decides which types a caller may know exist -- it includes a
    type "whenever discover:{type} is granted" -- and a hint says
    precisely that a type exists and is in use. Deciding it again here
    would be a SECOND PLACE deciding one security question, which is
    how two rules drift apart.

    My first version did ask its own: it imported `authorize` and
    tested `discover:` itself. It was correct on the day and would stop
    being correct the first time the ladder changed in one place.

    PER CALLER, NEVER FANNED OUT, which is the rule
    `core/notifications.py` already states for its own rows:
    "filtering-after-assembly is where these systems leak, because the
    unfiltered thing existed". The visible schema passed in is one
    caller's.

    ORDER IS THE INPUT'S, de-duplicated. Not sorted: a stable ordering
    across recipients is one more thing two colleagues could compare.
    """
    seen = set()
    allowed = []
    for object_type in changed_types or ():
        if object_type in seen:
            continue
        seen.add(object_type)
        if object_type in (visible_schema or {}):
            allowed.append(object_type)
    return allowed


def describe_hint(object_type: str, change_kind: str) -> dict:
    """The whole payload a hint is permitted to carry.

    A TYPE AND A VERB. No id, no field, no count, no timestamp of the
    change itself -- each of those is a fact about data the recipient
    may not be able to read, and a hint that carries one has become a
    second read path with no authorization on it.

    A COUNT IS THE TEMPTING ONE and the reason this returns a fixed
    shape rather than a dict the caller fills. "4 Customers changed"
    looks harmless and is a measurement: repeated over a day it maps
    the size and rhythm of a compartment somebody cannot see.
    """
    if change_kind not in CHANGE_KINDS:
        raise ValueError(
            f"a hint may say {list(CHANGE_KINDS)}, not {change_kind!r}. "
            f"Anything more specific is a fact about data the recipient "
            f"may not be allowed to read."
        )
    return {"object_type": object_type, "change": change_kind}
