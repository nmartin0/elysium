"""
run_deployment.py  (generic -- works for ANY deployment, unmodified)

Loads one deployment's config+mediator, loads its example queries, runs
each one through the real pipeline, and prints the answer. This file
must never gain org-specific content -- if a deployment ever needs
something this script can't express generically, that's a sign the
data format (config.yaml / example_queries.yaml) needs a new field,
not that this script needs a special case for that org.

Run from the project root:
    python3 -m scripts.run_deployment acme_corp
"""

import sys
from pathlib import Path

from core.agent.agentic_loop import AgentLoop
from core.deployment_loader import load_deployment_bundle, load_example_queries
from core.intermediate_layer.auth import get_user_security_value
from core.llm.ollama_client import OllamaClient
from core.llm.synthesis_prompt import synthesize_insight
from core.logging_config import configure_logging


def run_deployment(deployment_name: str) -> None:
    deployment_dir = Path("deployments") / deployment_name
    config, mediator = load_deployment_bundle(deployment_dir)
    examples = load_example_queries(deployment_dir)

    loop = AgentLoop.from_deployment(config, mediator)
    synthesis_client = OllamaClient.for_synthesis(config)

    for example in examples:
        user_id = example["user_id"]
        query_text = example["query"]
        print(f"--- {query_text!r} (as {user_id}) ---")

        user_security_value = get_user_security_value(config.users, user_id, config.security_attribute)
        if user_security_value is None:
            print("Unknown user -- no security attribute on record.\n")
            continue

        gathered = loop.run(user_security_value, query_text)
        real_data = AgentLoop.filter_real_data(gathered)

        insight = synthesize_insight(synthesis_client, query_text, real_data)
        print(insight)
        print()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 -m scripts.run_deployment <deployment_name>")
        sys.exit(1)

    configure_logging()
    run_deployment(sys.argv[1])
