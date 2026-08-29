"""
Integration tests: real Ollama, confirm a real model discovers and
follows a link that genuinely crosses a data-silo boundary -- not that
the resolution mechanism itself works correctly (already proven with a
scripted model by tests/unit/test_cross_silo_links.py). SLOW, requires
Ollama.

Runs against tests/integration/fixtures/ (see conftest.py) -- a fully
isolated test deployment, now with TWO genuinely separate SQLite
databases: primary_sql (Customer, Transaction) and support_crm
(SupportTicket). Customer.support_tickets is a reverse link whose
via_table physically lives in support_crm, not primary_sql -- the
model has no way to know this from the question alone (agent_step_prompt.py
never renders physical storage details into the prompt at all -- only
core/ontology/schema.py's semantic keys, id_field/fields; see
core/ontology/mediator.py's own docstring). It can only discover the
link's existence by reading its own visible_schema().

TWO DELIBERATELY DIFFERENT tests, not one -- an earlier version of this
file only had the first, and its first real run revealed something
worth testing separately: SupportTicket had its OWN id_field/customer_id
grants, making it independently, directly searchable (search_object(
"SupportTicket", {"customer_id": ...})) -- a completely valid,
DIFFERENT way to reach the same cross-silo data, not a bug, but not
what "follows the ontology's link" specifically means either. Both
paths are worth proving:

  1. test_real_model_follows_a_link_across_silos (user_alice) -- the
     model is free to reach SupportTicket HOWEVER it decides to, direct
     search included. Proves the mechanism is discoverable and usable
     at all.
  2. test_real_model_is_forced_to_follow_the_link_when_no_alternate_path_exists
     (user_frank) -- SupportTicket's id_field and customer_id grants
     are deliberately withheld, so direct search can never locate
     cust_001's tickets. The ONLY path that can work is genuinely
     following Customer.support_tickets. See fixtures/policy.yaml's
     customer_service_link_only role for exactly what's withheld and
     the one honest caveat (subject/status remain technically
     searchable in the RBAC sense, just practically unusable without
     already knowing the exact value).
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record
from core.deployment_loader import build_llm_adapter
from core.llm.synthesis_prompt import synthesize_insight

QUERY_TEXT = "What support tickets does cust_001 have, and what are their statuses?"


@pytest.mark.integration
def test_real_model_follows_a_link_across_silos(deployment, mediator):
    loop = AgentLoop.from_deployment(deployment, mediator)
    synthesis_client = build_llm_adapter(deployment, deployment.synthesis_model)
    user_record = resolve_user_record(deployment.users, "user_alice", deployment.security_attribute)

    result = loop.run(user_record, QUERY_TEXT)

    print(f"\n[diagnostic] full gathered steps: {result.gathered}")

    # THE thing this test exists to prove: at least one gathered step
    # genuinely reached into SupportTicket -- a type whose data
    # physically lives in a DIFFERENT database than where the query
    # started (Customer, in primary_sql). No step in this trace was
    # scripted; the model chose every one of them itself. Deliberately
    # NOT asserting HOW it got there -- user_alice's grants allow
    # either a direct search_object("SupportTicket", ...) or following
    # Customer.support_tickets, and both are valid, safe paths to the
    # same real data.
    support_ticket_steps = [item for item in result.gathered if item.get("object_type") == "SupportTicket"]
    assert len(support_ticket_steps) > 0, (
        f"Expected the model to reach SupportTicket somehow, "
        f"but it never did. Gathered: {result.gathered}"
    )

    real_data = AgentLoop.filter_real_data(result.gathered)
    answer = synthesize_insight(synthesis_client, QUERY_TEXT, real_data, result.hit_max_hops)
    print(f"[diagnostic] final synthesized answer: {answer!r}")

    real_subjects = {
        item["result"] for item in real_data
        if item.get("object_type") == "SupportTicket" and item.get("field_name") == "subject"
    }
    if real_subjects:
        assert real_subjects & {"Login page returns a 500 error", "Requesting a refund for hardware order"}


@pytest.mark.integration
def test_real_model_is_forced_to_follow_the_link_when_no_alternate_path_exists(deployment, mediator):
    loop = AgentLoop.from_deployment(deployment, mediator)
    synthesis_client = build_llm_adapter(deployment, deployment.synthesis_model)
    user_record = resolve_user_record(deployment.users, "user_frank", deployment.security_attribute)

    result = loop.run(user_record, QUERY_TEXT)

    print(f"\n[diagnostic] full gathered steps: {result.gathered}")

    # A direct search_object("SupportTicket", {"customer_id": ...})
    # attempt must never SUCCEED for this user -- customer_id was
    # deliberately never granted, so it isn't a filterable column at
    # all (ValueError: Invalid search criteria, caught by AgentLoop's
    # own invalid-step recovery). The model may still ATTEMPT it (it
    # has no way to know in advance it will fail), but no such attempt
    # should appear with a real result.
    illegitimate_search_successes = [
        item for item in result.gathered
        if item.get("step") == "search_object" and item.get("object_type") == "SupportTicket"
        and item.get("result")
    ]
    assert illegitimate_search_successes == [], (
        f"A direct search_object on SupportTicket should never succeed for "
        f"user_frank -- got: {illegitimate_search_successes}"
    )

    # THE thing this test specifically exists to prove: the model
    # reached SupportTicket data ONLY via the reverse link.
    support_tickets_link_followed = any(
        item.get("step") == "get_field" and item.get("object_type") == "Customer"
        and item.get("field_name") == "support_tickets" and item.get("result")
        for item in result.gathered
    )
    assert support_tickets_link_followed, (
        f"Expected the model to follow Customer.support_tickets -- the ONLY "
        f"viable path to cust_001's tickets for this user -- but it never did. "
        f"Gathered: {result.gathered}"
    )

    real_data = AgentLoop.filter_real_data(result.gathered)
    answer = synthesize_insight(synthesis_client, QUERY_TEXT, real_data, result.hit_max_hops)
    print(f"[diagnostic] final synthesized answer: {answer!r}")
