"""
run_deployment.py  (single-tenant -- one Elysium instance, one organization)

Loads the deployment's config+mediator, loads its example queries, runs
each one through the real pipeline, and prints the answer. This file
must never gain org-specific content -- if the deployment ever needs
something this script can't express generically, that's a sign the
data format (config.yaml / example_queries.yaml) needs a new field,
not that this script needs a special case for that org.

Config, data, and logs are three genuinely independent locations,
always -- resolve_runtime_paths() decides where each actually is
(deployment/etc, deployment/var/lib, deployment/var/log for local
development; /etc/elysium, /var/lib/elysium, /var/log/elysium for a
real install, via ELYSIUM_CONFIG_DIR/ELYSIUM_DATA_DIR/ELYSIUM_LOG_DIR --
see scripts/install.sh). This script itself never needs to know which
mode it's running in.

run_deployment() takes an OPTIONAL runtime_paths, resolved lazily
inside it when not given, rather than a module-level global resolved
once at import time -- see scripts/serve_requests.py's own docstring
for the identical reasoning (matches api/app.py's own
create_app(runtime_paths) pattern). resolve_runtime_paths() is called
exactly once either way -- inside run_deployment() itself when
__main__ below calls it with no arguments, the normal case -- not
baked in at import time before a caller could ever override it.

Run from the project root:
    python3 -m scripts.run_deployment
"""

from core.agent.agentic_loop import AgentLoop
from core.deployment_loader import (
    RuntimePaths,
    build_llm_adapter,
    load_deployment_bundle,
    load_example_queries,
    resolve_runtime_paths,
)
from core.intermediate_layer.auth import resolve_user_record
from core.llm.synthesis_prompt import synthesize_insight
from core.logging_config import configure_logging
from core.ontology.write_mediator import PendingWrite, WriteMediator


def _terminal_confirm_write(pending: PendingWrite) -> bool:
    # The "hardcoded, non-LLM code" confirmation gate for this entry
    # point specifically -- a real terminal prompt showing EXACTLY what
    # was proposed (both the description AND each sub-write's raw
    # changes dict, so nothing is hidden behind a possibly-incomplete
    # summary) before anything executes.
    #
    # Loops over pending.sub_writes rather than indexing [0] -- unlike
    # write_mediator.py's own apply-side methods, this is pure display,
    # with no atomicity concern tying it to exactly one sub-write for
    # now. A human reviewing a future multi-object proposal already
    # sees every one of its sub-writes here, even though nothing can
    # construct more than one yet (see PendingWrite's own docstring).
    print("\n--- WRITE CONFIRMATION NEEDED ---")
    print(pending.description)
    for sub_write in pending.sub_writes:
        print(f"  {sub_write.operation} {sub_write.object_type} {sub_write.object_id!r}: {sub_write.changes}")
    answer = input("Approve this write? [y/N]: ").strip().lower()
    return answer == "y"


def run_deployment(runtime_paths: RuntimePaths | None = None) -> None:
    if runtime_paths is None:
        runtime_paths = resolve_runtime_paths()
    config, mediator = load_deployment_bundle(
        runtime_paths.config_dir, runtime_paths.data_dir, runtime_paths.log_dir
    )
    examples = load_example_queries(runtime_paths.config_dir)

    # Always wired up -- the actual gate is policy.yaml's roles, not
    # whether write plumbing exists. A deployment granting no role any
    # write: permission (the default) simply sees every proposed write
    # denied via the same PermissionError path already covered by
    # tests/unit/test_write_mediator.py -- harmless either way. Reads
    # its own write_log directly from mediator (see WriteMediator's
    # own write_log property) -- nothing to pass or verify matches
    # here.
    write_mediator = WriteMediator(mediator, config.roles, config.action_types)
    # THE resume-on-startup half of crash recovery -- see
    # WriteMediator.resume_pending_writes()'s own docstring for the
    # full mechanism. Runs ONCE, here, before any example query in this
    # run touches the same objects.
    resume_summary = write_mediator.resume_pending_writes()
    if any(resume_summary.values()):
        print(f"resume_pending_writes() on startup: {resume_summary}")
    if resume_summary["ambiguous"]:
        print(
            f"WARNING: {resume_summary['ambiguous']} write(s) left ambiguous after resume -- "
            f"see audit.log's write_resume_ambiguous entries for detail; these need manual review."
        )
    # confirm_write is NOT passed to AgentLoop anymore -- a proposed
    # write stops the loop and comes back via AgentLoopResult.
    # pending_write; THIS script confirms it, right here, after run()
    # returns -- see core/agent/agentic_loop.py's module docstring.
    loop = AgentLoop.from_deployment(config, mediator, write_mediator=write_mediator)
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
        result = loop.run(user_record, query_text)

        if result.pending_write is not None:
            approved = _terminal_confirm_write(result.pending_write)
            outcome = write_mediator.confirm_and_execute(result.pending_write, approved)
            print(outcome)
        else:
            real_data = AgentLoop.filter_real_data(result.gathered)
            insight = synthesize_insight(synthesis_client, query_text, real_data, result.hit_max_hops)
            print(insight)
        print()


if __name__ == "__main__":
    configure_logging()
    run_deployment()
