"""
serve_requests.py  (single-tenant -- proves concurrent safety)

Dispatches multiple (user_id, query_text) requests concurrently via a
thread pool, sized from config.max_concurrent_requests. This is NOT a
real HTTP server -- see api/ for that. This proves the underlying
objects (loop, mediator, write_mediator) are genuinely safe for
concurrent calls, the prerequisite any real server would need anyway.

Threads, not async, because every real wait here (Ollama's
requests.post(), SQLite disk I/O) releases the GIL while waiting --
exactly the situation threads handle well.

Config/data location resolved via resolve_runtime_paths() -- see
scripts/run_deployment.py's docstring for why this script itself never
needs to know whether it's running from a local checkout or a real
FHS-based install. Taken as an OPTIONAL parameter, resolved lazily
inside serve() when not given, rather than a module-level global
resolved once at import time -- same reasoning, and same fix, as
api/app.py's own create_app(runtime_paths) (see its own docstring):
a module-level global would be baked in the moment this module is
first imported, before a caller (e.g. a future isolated test) ever
gets a chance to override it, and Python only ever executes a
module's top-level code once per process, so nothing later could
change it either.
"""

from concurrent.futures import ThreadPoolExecutor

from core.agent.agentic_loop import AgentLoop
from core.deployment_loader import RuntimePaths, load_deployment_bundle, resolve_runtime_paths
from core.intermediate_layer.auth import resolve_user_record


def serve(requests: list[tuple[str, str]], runtime_paths: RuntimePaths | None = None) -> list[list[dict]]:
    # requests: list of (user_id, query_text) pairs, dispatched concurrently.
    # Returns each request's raw gathered result, same order as input.
    if runtime_paths is None:
        runtime_paths = resolve_runtime_paths()
    config, mediator, _write_adapters = load_deployment_bundle(runtime_paths.config_dir, runtime_paths.data_dir)
    loop = AgentLoop.from_deployment(config, mediator)

    # Identity resolved ONCE per request, here -- AgentLoop.run() takes
    # a UserRecord, not a raw user_id string (see core/
    # intermediate_layer/auth.py's resolve_user_record() docstring).
    user_records = [
        resolve_user_record(config.users, user_id, config.security_attribute)
        for user_id, _ in requests
    ]

    with ThreadPoolExecutor(max_workers=config.max_concurrent_requests) as executor:
        futures = [
            executor.submit(loop.run, user_record, query_text)
            for user_record, (_, query_text) in zip(user_records, requests, strict=True)
        ]
        return [f.result() for f in futures]
