"""
agent_trace.py  (run one query against the real agent, and show its work)

    python -m scripts.agent_trace --user alice "who is Ada Okafor?"

WHY THIS EXISTS. The integration suite runs every scenario or none: on
a local model that was 1 hour 35 minutes for seventeen tests, and a
failure gave a pytest traceback rather than what the agent actually
did. `gathered` was printed as one long dict, which is where the
answer usually is and the hardest place to read it.

This runs ONE query, against whatever LLM the deployment configures,
and prints the trace as steps. It is a debugging tool, not a test --
it asserts nothing and has no expected output, because the thing you
are usually trying to find out is what the agent chose, not whether it
matched something you already predicted.

Deliberately uses the real loop, real mediator, real adapters and the
real deployment config. A harness that stubs any of those tells you
about the stub.

Useful for the UI too: it answers "what does the backend actually do
for this question" without a browser, which is the same question a
screen is asking.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from core.agent.agentic_loop import AgentLoop
from core.deployment_loader import (
    build_llm_adapter,
    load_deployment_bundle,
    resolve_runtime_paths,
)
from core.intermediate_layer.auth import resolve_user_record
from core.llm.interface import LLMUnavailable
from core.llm.synthesis_prompt import synthesize_insight
from core.ontology.write_mediator import WriteMediator

# Steps the loop records that are notes about its own behaviour rather
# than data it gathered. Shown differently because a run full of them
# is a different problem from a run that gathered the wrong things.
_LOOP_NOTES = {
    "rejected_invalid_step",
    "rejected_duplicate",
    "rejected_business_rule",
    "completeness_check",
}


def _render(step: dict, index: int) -> str:
    name = step.get("step", "?")
    if name in _LOOP_NOTES:
        return f"  {index:>2}. [{name}] {step.get('note', '')}"

    # The step the model asked for, minus the result, so the intent is
    # readable on one line even when the result is a thousand ids.
    asked = {k: v for k, v in step.items() if k not in ("result", "step", "note")}
    line = f"  {index:>2}. {name}({json.dumps(asked, default=str)})"

    result = step.get("result")
    if isinstance(result, list):
        preview = f"{len(result)} item(s)"
        if result:
            preview += f", first: {result[0]!r}"
    elif isinstance(result, dict):
        preview = json.dumps(result, default=str)
    else:
        preview = repr(result)
    if len(preview) > 160:
        preview = preview[:157] + "..."
    return f"{line}\n      -> {preview}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[2].strip())
    parser.add_argument("query", help="the question to ask, as one argument")
    parser.add_argument("--user", required=True, help="username from the deployment's own users")
    parser.add_argument("--config-dir", type=Path, default=None)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument(
        "--synthesize", action="store_true",
        help="also run the synthesis step and print the final answer",
    )
    args = parser.parse_args(argv)

    paths = resolve_runtime_paths()
    config_dir = args.config_dir or paths.config_dir
    data_dir = args.data_dir or paths.data_dir

    # The bundle returns write ADAPTERS, not a WriteMediator -- the
    # same shape api/app.py works with, so this builds one the same
    # way rather than inventing a second construction path.
    deployment, mediator, write_adapters = load_deployment_bundle(config_dir, data_dir)
    write_mediator = WriteMediator(
        mediator, write_adapters, deployment.roles, deployment.action_types
    )
    user_record = resolve_user_record(
        deployment.users, args.user, deployment.security_attribute
    )
    if user_record is None:
        print(f"No such user {args.user!r} in {config_dir}/policy.yaml", file=sys.stderr)
        return 2

    loop = AgentLoop.from_deployment(deployment, mediator, write_mediator)

    print(f"query : {args.query}")
    print(f"user  : {args.user} ({deployment.security_attribute}={user_record.security_value}, "
          f"role={user_record.role_name})")
    print(f"model : {deployment.llm_provider} / step={deployment.step_model}")
    print()

    started = time.time()
    try:
        result = loop.run(user_record, args.query)
    except LLMUnavailable as e:
        # The one failure worth catching by name: it means the model was
        # never reached, which looks nothing like the model answering
        # badly and should not be reported as a traceback.
        print(f"The model could not be reached: {e}", file=sys.stderr)
        return 1
    elapsed = time.time() - started

    print(f"steps ({len(result.gathered)}):")
    for index, step in enumerate(result.gathered, start=1):
        print(_render(step, index))

    print()
    print(f"elapsed        : {elapsed:.1f}s")
    print(f"hit max hops   : {result.hit_max_hops}")
    print(f"pending write  : {result.pending_write is not None}")

    if args.synthesize:
        client = build_llm_adapter(deployment, deployment.synthesis_model)
        print()
        print("answer:")
        print(f"  {synthesize_insight(client, args.query, result.gathered, deployment.step_model)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
