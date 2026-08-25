"""
serve_requests.py  (generic dispatch layer -- proves concurrent safety)

Dispatches multiple (user_id, query_text) requests concurrently via a
thread pool, sized from config.max_concurrent_requests. This is NOT a
real HTTP server -- that's a separate, later decision (new dependency,
real deployment concerns). This proves the underlying objects (loop,
mediator, write_mediator) are genuinely safe for concurrent calls, the
prerequisite any real server would need anyway.

Threads, not async, because every real wait here (Ollama's
requests.post(), SQLite disk I/O) releases the GIL while waiting --
exactly the situation threads handle well.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.agent.agentic_loop import AgentLoop
from core.deployment_loader import load_deployment_bundle


def serve(deployment_name: str, requests: list[tuple[str, str]]) -> list[list[dict]]:
    # requests: list of (user_id, query_text) pairs, dispatched concurrently.
    # Returns each request's raw gathered result, same order as input.
    config, mediator = load_deployment_bundle(Path("deployments") / deployment_name)
    loop = AgentLoop.from_deployment(config, mediator)

    with ThreadPoolExecutor(max_workers=config.max_concurrent_requests) as executor:
        futures = [executor.submit(loop.run, user_id, query_text) for user_id, query_text in requests]
        return [f.result() for f in futures]
