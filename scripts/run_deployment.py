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
from core.deployment_loader import load_deployment_bundle, load_example_queries, build_llm_adapter
from core.llm.synthesis_prompt import synthesize_insight
from core.logging_config import configure_logging
from core.ontology.write_mediator import WriteMediator, PendingWrite


def _terminal_confirm_write(pending: PendingWrite) -> bool:
    # The "hardcoded, non-LLM code" confirmation gate for this entry
    # point specifically -- a real terminal prompt showing EXACTLY what
    # was proposed (both the description AND the raw changes dict, so
    # nothing is hidden behind a possibly-incomplete summary) before
    # anything executes.
    print("\n--- WRITE CONFIRMATION NEEDED ---")
    print(pending.description)
    print(f"Raw changes: {pending.changes}")
    answer = input("Approve this write? [y/N]: ").strip().lower()
    return answer == "y"


def run_deployment(deployment_name: str) -> None:
    deployment_dir = Path("deployments") / deployment_name
    config, mediator = load_deployment_bundle(deployment_dir)
    examples = load_example_queries(deployment_dir)

    # Always wired up -- the actual gate is policy.yaml's roles, not
    # whether write plumbing exists. A deployment granting no role any
    # write: permission (acme_corp's default) simply sees every
    # proposed write denied via the same PermissionError path already
    # covered by tests/unit/test_write_mediator.py -- harmless either way.
    write_mediator = WriteMediator(mediator, config.users, config.roles, config.security_attribute)
    loop = AgentLoop.from_deployment(
        config, mediator, write_mediator=write_mediator, confirm_write=_terminal_confirm_write
    )
    synthesis_client = build_llm_adapter(config, config.synthesis_model)

    for example in examples:
        user_id = example["user_id"]
        query_text = example["query"]
        print(f"--- {query_text!r} (as {user_id}) ---")

        # Pure UX courtesy, not a security check -- the real enforcement
        # happens inside DataMediator regardless. Just avoids running a
        # full (potentially multi-minute) agent loop for a user_id
        # that's obviously not even in policy.yaml at all.
        if user_id not in config.users:
            print("Unknown user -- not in policy.yaml.\n")
            continue

        # No separate security-value resolution needed anymore --
        # DataMediator resolves both the MAC value and the RBAC role
        # internally, per object, via check_access().
        gathered = loop.run(user_id, query_text)
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
