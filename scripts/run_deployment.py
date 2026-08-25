"""
run_deployment.py  (single-tenant -- always runs the one deployment/ folder)

Loads the deployment's config+mediator, loads its example queries, runs
each one through the real pipeline, and prints the answer. This file
must never gain org-specific content -- if the deployment ever needs
something this script can't express generically, that's a sign the
data format (config.yaml / example_queries.yaml) needs a new field,
not that this script needs a special case for that org.

One server instance, one organization -- there is exactly one
deployment/ folder, never a name to choose between several.

Run from the project root:
    python3 -m scripts.run_deployment
"""

from pathlib import Path

from core.agent.agentic_loop import AgentLoop
from core.deployment_loader import load_deployment_bundle, load_example_queries, build_llm_adapter
from core.intermediate_layer.auth import resolve_user_record
from core.llm.synthesis_prompt import synthesize_insight
from core.logging_config import configure_logging
from core.ontology.write_mediator import WriteMediator, PendingWrite

DEPLOYMENT_DIR = Path("deployment")


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


def run_deployment() -> None:
    config, mediator = load_deployment_bundle(DEPLOYMENT_DIR)
    examples = load_example_queries(DEPLOYMENT_DIR)

    # Always wired up -- the actual gate is policy.yaml's roles, not
    # whether write plumbing exists. A deployment granting no role any
    # write: permission (the default) simply sees every proposed write
    # denied via the same PermissionError path already covered by
    # tests/unit/test_write_mediator.py -- harmless either way.
    # WriteMediator no longer takes users/security_attribute -- see
    # core/ontology/write_mediator.py's docstring.
    write_mediator = WriteMediator(mediator, config.roles)
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

        # Identity resolved ONCE, here, at the top of the request --
        # see core/intermediate_layer/auth.py's resolve_user_record()
        # docstring for why this replaced a per-check lookup.
        user_record = resolve_user_record(config.users, user_id, config.security_attribute)
        gathered = loop.run(user_record, query_text)
        real_data = AgentLoop.filter_real_data(gathered)

        insight = synthesize_insight(synthesis_client, query_text, real_data)
        print(insight)
        print()


if __name__ == "__main__":
    configure_logging()
    run_deployment()
