"""
The prompt diverges early between users, and must keep doing so.

ROADMAP.md's security backlog: prefix caching makes a cache hit
measurably faster than a miss, and published attacks (PROMPTPEEK,
EarlyBird, InputSnatch) reconstruct another tenant's prompt token by
token from latency alone, reporting up to 100% success against
unprotected vLLM and SGLang deployments.

THE ATTACK NEEDS STRICT PREFIX ALIGNMENT -- a probe must match from the
very first token. _build_system_prompt() puts the MAC/RBAC-filtered
schema near the front, so two users with different access diverge
almost immediately and neither can align far against the other. The
per-user schema acts as a cache partition key.

THAT IS ACCIDENTAL, and the entry says it must not be optimised away.
Moving the generic instructions and examples ABOVE the schema -- to
lengthen the shared prefix and improve cache hit rates -- would be a
security regression wearing the costume of a performance win. It is
exactly the change that creates the alignable cross-privilege prefix
these attacks need.

Until now that was a comment. A comment does not fail a build.
"""

from core.llm.agent_step_prompt import _build_system_prompt

# The most divergent case there is: no object type, field or id in
# common. Whatever these two share is shared by EVERY pair of users.
CUSTOMER = {"Customer": {"id_field": "customer_id", "fields": {"name": {"type": "string"}}}}
SHIPMENT = {"Shipment": {"id_field": "shipment_id", "fields": {"port": {"type": "string"}}}}

# Two users with nothing in common now share "- ", the opening of a
# list item, and nothing else. The budget allows a little slack for
# wording changes and no more -- it was 160 while a fixed preamble came
# first, and tightening it is the point of this change rather than an
# incidental effect of it.
MAX_SHARED_CHARS = 8


def _shared_prefix(first: str, second: str) -> int:
    shared = 0
    # strict=False deliberately: the two prompts are DIFFERENT lengths,
    # which is the whole point -- stopping at the shorter one is correct.
    for a, b in zip(first, second, strict=False):
        if a != b:
            break
        shared += 1
    return shared


def test_two_users_with_disjoint_schemas_share_almost_no_prefix():
    """THE REGRESSION GUARD.

    Measured before the fix: 103 characters, about 25 tokens -- a fixed
    preamble plus the "- " that opens the first object type line. That
    was a foothold, not a wall: an attacker aligns on it and probes
    forward, and what they recover first is the victim's leading object
    type name, which visible_schema filters per user.

    Measured after: 2 characters. The schema is now the first thing in
    the prompt, so there is nothing to align against.

    The budget allows slack for wording and no more. It fails loudly if
    someone moves the instructions, the examples or the step vocabulary
    ABOVE the schema, which would take this into the thousands.
    """
    shared = _shared_prefix(
        _build_system_prompt(CUSTOMER, [], False, {}),
        _build_system_prompt(SHIPMENT, [], False, {}),
    )

    assert shared <= MAX_SHARED_CHARS, (
        f"two users with nothing in common share {shared} characters of prompt "
        f"prefix. A shared prefix is what a KV-cache timing attack aligns "
        f"against -- see ROADMAP.md's security backlog before raising this budget"
    )


def test_the_schema_appears_before_the_examples():
    """The structural version of the same property.

    A character budget catches the large regression; this catches the
    intent directly, and says which way round the file must stay.
    """
    prompt = _build_system_prompt(CUSTOMER, [], False, {})

    assert prompt.index("Customer") < prompt.index("PLACEHOLDER")


def test_the_same_user_gets_a_byte_identical_prompt():
    """THE CONTROL, and the reason this is not solved by a random salt.

    One user's own prompt must be stable across their own queries, or
    every query pays a full prefix miss on hardware where prompt
    evaluation is already the dominant cost. The goal is divergence
    BETWEEN users, not noise within one.
    """
    first = _build_system_prompt(CUSTOMER, [], False, {})
    second = _build_system_prompt(CUSTOMER, [], False, {})

    assert first == second
