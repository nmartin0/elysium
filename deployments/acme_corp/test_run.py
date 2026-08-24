"""
test_run.py  (wires everything together, end to end -- for acme_corp)

Pipeline construction goes through AgentLoop.from_deployment() and
OllamaClient.for_synthesis() -- one authoritative implementation shared
with the integration tests, instead of each place separately
constructing clients/loop by hand.

KNOWN GAP, still true: this path only enforces the security attribute
(region, per this deployment's policy.yaml) via the engine's own checks.
It does NOT check auth.authorize() at all, so user_carol -- who has an
empty allowed_actions list -- will still get real data back for
cust_004, since her region matches. Reconnecting this loop to
core/intermediate_layer/gateway.py (auth + audit) is still a real task.

Run from the project root:
    python3 -m deployments.acme_corp.test_run
"""

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import get_user_security_value
from core.llm.ollama_client import OllamaClient
from core.llm.synthesis_prompt import synthesize_insight
from core.logging_config import configure_logging

from deployments.acme_corp.deployment import config
from deployments.acme_corp.ontology_adapter import engine

configure_logging()

loop = AgentLoop.from_deployment(config, engine)
synthesis_client = OllamaClient.for_synthesis(config)


def run_example(user_id: str, query_text: str) -> None:
    print(f"--- {query_text!r} (as {user_id}) ---")

    user_security_value = get_user_security_value(config.users, user_id, config.security_attribute)
    if user_security_value is None:
        print("Unknown user -- no security attribute on record.\n")
        return

    gathered = loop.run(user_security_value, query_text)
    real_data = AgentLoop.filter_real_data(gathered)

    insight = synthesize_insight(synthesis_client, query_text, real_data)
    print(insight)
    print()


if __name__ == "__main__":
    run_example("user_alice", "What are cust_001's recent transactions?")
    run_example("user_alice", "What are cust_003's recent transactions?")
    run_example("user_carol", "What are cust_004's recent transactions?")
