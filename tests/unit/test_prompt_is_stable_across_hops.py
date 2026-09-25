"""The system prompt does not change between hops, and when it must,
the change is confined to a TRAILING section.

AR-1 measured this on the real loop over a real mediator. Seven hops
of a real query as `user_alice` (region us-west, role
customer_service), reading a customer, its email, its transactions and
their amounts:

    hop    system    user   total   shared   reuse   diverges in
      2      5989     218    6207     6061   97.6%   user message
      3      5989     339    6328     6182   97.7%   user message
      4      5989     473    6462     6303   97.5%   user message
      5      5989     618    6607     6437   97.4%   user message
      6      6135     732    6867     5989   87.2%   SYSTEM PROMPT
      7      6138     847    6985     6135   87.8%   SYSTEM PROMPT

WHILE THE SYSTEM PROMPT HOLDS STILL, reuse is 97.4%-97.7% and the
divergence is in the user message where `gathered` grows -- which is
the cheapest place it can be.

ON THE HOP A WRITE BECOMES RELEVANT IT DOES NOT HOLD STILL. Once
Transaction ids have been read, _action_state_notes() starts
rendering, the system prompt grows (5989 -> 6135 -> 6138), and reuse
falls about ten points. That is a REAL, MEASURED cost in the shipped
deployment, not a hypothetical: `RecategorizeTransactions` targets
Transaction, so any query that reaches a transaction pays it.

AN EARLIER VERSION OF THIS FILE SAID THE SYSTEM PROMPT WAS
BYTE-IDENTICAL ON EVERY HOP. That was measured with the user id
"alice", which the shipped policy.yaml does not define -- it names her
"user_alice" -- and resolve_user_record() returns an EMPTY UserRecord
for an unknown id. So every read was denied, visible_schema was empty,
and every result was null. The prompt still grew, hop by hop, which is
exactly why the run looked healthy. The reuse figure survived
re-measurement; the stability claim did not.

WHY IT MATTERS: prefill dominates here. MODEL_SELECTION-001 measured
~5.4 tokens/s prefill against ~1.5 decode, so re-reading a prompt is
most of what a hop costs. An engine can only skip a prefix it has
already seen, and only up to the first token that differs. A change
that moves per-hop state EARLIER therefore costs the whole remainder,
on every hop, forever -- while looking like a tidier way to render the
same information.

THE DESIGN THIS PINS is already in the code and already explained in a
comment: _action_state_notes() renders as its own trailing section
"rather than inline in each action's block, because inline it changed
the middle of the system prompt on the exact hop a write became
relevant". That comment is correct and it cannot fail a build, which
is the same gap test_prompt_prefix_is_user_specific.py was written to
close for the cross-user property.

THIS FILE DOES NOT CLAIM THE NOTES ARE FREE. They cost the ten points
above. It pins only that the cost stays confined to the tail, so that
the hops BEFORE a write becomes relevant keep their 97%, and so that
the notes cannot migrate into the body where they would cost every hop
of every query. Removing that cost entirely is AR-2, which is a design
change and not this.

NOT THE SAME PROPERTY AS test_prompt_prefix_is_user_specific, and the
two pull in opposite directions, which is worth stating so neither is
"improved" into breaking the other:

    test_prompt_prefix_is_user_specific  two DIFFERENT users must
                                         share almost NO prefix
    this file                            one user's SUCCESSIVE HOPS
                                         must share almost ALL of it

Both hold today because the divergence between users is at the HEAD
(the per-user schema) and the divergence between hops is at the TAIL
(gathered, then the notes). Anything that moves per-hop state toward
the head breaks this file; anything that moves shared boilerplate
toward the head breaks that one.
"""

from core.llm.agent_step_prompt import _action_state_notes, _build_system_prompt

SCHEMA = {
    "Ticket": {
        "id_field": "ticket_id",
        "fields": {
            "status": {"type": "data", "data_type": "string"},
            "title": {"type": "data", "data_type": "string"},
        },
    }
}

# An action whose validity DOES depend on what has been read, which is
# the only way _action_state_notes() produces anything at all.
REOPEN = {
    "ReopenTicket": {
        "description": "Reopen a closed ticket.",
        "affected_object_types": ["Ticket"],
        "parameters": {
            "ticket_id": {"type": "object_reference", "object_type": "Ticket", "required": True},
        },
        "sub_writes": [
            {
                "object_type": "Ticket",
                "object_id": "parameter.ticket_id",
                "operation": "update",
                "mutations": [{"set": {"property": "status", "value": "open"}}],
                "submission_criteria": [
                    {
                        "description": "Ticket must currently be closed to reopen it",
                        "check": "current_state",
                        "field": "status",
                        "operator": "equals",
                        "value": "closed",
                    }
                ],
            }
        ],
    }
}

# Hop 3 has read a ticket's status; hop 2 had not. That is exactly the
# hop on which the action-availability notes start saying something.
GATHERED_EARLY: list[dict] = [
    {"step": "search_object", "object_type": "Ticket", "filter": {}, "result": ["t_001"]},
]
GATHERED_LATER: list[dict] = [
    *GATHERED_EARLY,
    {
        "step": "get_field",
        "object_type": "Ticket",
        "object_id": "t_001",
        "field_name": "status",
        "result": "closed",
    },
]


def _shared_prefix(first: str, second: str) -> int:
    shared = 0
    # strict=False deliberately: the prompts are different lengths, and
    # stopping at the shorter one is the correct comparison.
    for a, b in zip(first, second, strict=False):
        if a != b:
            break
        shared += 1
    return shared


def _prompt(gathered: list[dict]) -> str:
    return _build_system_prompt(SCHEMA, [], True, REOPEN, gathered)


def test_the_notes_this_guards_actually_fire():
    """THE GUARD'S OWN GUARD.

    Every assertion below is vacuous if _action_state_notes() returns
    "" for this fixture -- two identical prompts share a prefix
    trivially. AR-1's first measurement run was exactly that vacuum:
    it ran against the shipped deployment, whose one action declares
    no submission_criteria, so the notes were empty and the "system
    prompt is stable" result proved nothing about the case that can
    move it.

    So: assert the fixture reaches the code being tested, before
    testing it.
    """
    assert _action_state_notes(REOPEN, GATHERED_LATER) != ""
    assert _action_state_notes(REOPEN, GATHERED_EARLY) == ""


def test_per_hop_state_never_moves_the_head_of_the_system_prompt():
    """Everything before the notes is byte-identical across hops."""
    early = _prompt(GATHERED_EARLY)
    later = _prompt(GATHERED_LATER)

    assert early != later, (
        "the fixture no longer exercises a hop that changes the prompt"
    )

    shared = _shared_prefix(early, later)
    # The shorter prompt is the one with no notes, so everything it
    # holds must survive verbatim into the longer one.
    assert shared == len(early), (
        f"per-hop state moved into the body of the system prompt: the hops "
        f"diverge at character {shared} of {len(early)}, not at the tail. "
        f"Everything after that point is re-read by the model on every "
        f"single hop."
    )


def test_the_only_difference_between_hops_is_the_trailing_section():
    """And the tail that differs IS the notes, not something else."""
    early = _prompt(GATHERED_EARLY)
    later = _prompt(GATHERED_LATER)

    assert later[len(early):] == _action_state_notes(REOPEN, GATHERED_LATER)


def test_a_hop_that_reads_nothing_relevant_changes_nothing_at_all():
    """The opposite direction, so the guard cannot be satisfied by a
    prompt that simply always differs.

    Without this, an implementation that appended a timestamp or a hop
    counter to every prompt would pass the three assertions above and
    destroy reuse completely.
    """
    unrelated = [
        *GATHERED_EARLY,
        {
            "step": "get_field",
            "object_type": "Ticket",
            "object_id": "t_001",
            "field_name": "title",
            "result": "Printer jammed",
        },
    ]
    assert _prompt(unrelated) == _prompt(GATHERED_EARLY)
