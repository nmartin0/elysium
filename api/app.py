"""
app.py  (the FastAPI application -- knows FastAPI exists; core/ never does)

Builds everything ONCE at startup and stores it on app.state: the
DataMediator, one AgentLoop instance, one synthesis LLM client. This
matters, not just for efficiency -- core/concurrency.py's
ConcurrencyLimiter is built once per AgentLoop/LLMAdapter construction
and enforces a limit ACROSS all callers of that one instance. Building
a fresh AgentLoop per request would silently give every request its
own private limiter that never sees any other request, defeating the
whole mechanism. One instance, reused, is required for the concurrency
protections already built to mean anything -- same pattern
scripts/serve_requests.py already uses.

WRITES ARE NOT WIRED UP YET, deliberately: scripts/run_deployment.py's
confirm_write is a blocking terminal input() call -- a human physically
at the same machine. That has no sensible meaning for a remote HTTP
caller. A real HTTP write flow needs its own two-phase design (propose,
return a pending-write reference, a separate confirm endpoint) -- built
out, not improvised inline here. Flagged as a genuine, deliberate gap,
not a forgotten one.

Authentication/authorization here is ENTIRELY database-backed
(core/user_directory.py + core/auth/), never policy.yaml's static
`users:` section -- that section remains what scripts/run_deployment.py
(a simple demo/dev tool) uses. The two are intentionally not unified:
api/ is the real, running service; run_deployment.py is not.

CREDENTIALS_DB_PATH lives in the DATA directory (deployment/var/lib/
credentials.db locally; /var/lib/elysium/credentials.db under a real
install) -- runtime state, not config, same reasoning that keeps
config_dir and data_dir independent throughout core/deployment_loader.py.

Logging is configured here too, via configure_audit_log() -- api/ is a
real entry point, same as scripts/run_deployment.py.

app.state.executor is OUR OWN explicit ThreadPoolExecutor, sized from
config.max_concurrent_requests -- the SAME config value and the SAME
mechanism scripts/serve_requests.py already uses, deliberately NOT
relying on Starlette's own separate, differently-sized internal thread
pool (the one it uses automatically for synchronous route handlers).
An explicit, understood concurrency boundary, not an ambient default --
see api/routes.py's /query for where this actually gets used.
"""

from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI

from core.agent.agentic_loop import AgentLoop
from core.deployment_loader import build_llm_adapter, load_deployment_bundle, resolve_runtime_paths
from core.intermediate_layer.audit import configure_audit_log

RUNTIME_PATHS = resolve_runtime_paths()
CREDENTIALS_DB_PATH = RUNTIME_PATHS.data_dir / "credentials.db"


def create_app() -> FastAPI:
    app = FastAPI(title="LLM Data Mediator")

    configure_audit_log(RUNTIME_PATHS.log_dir)
    config, mediator = load_deployment_bundle(RUNTIME_PATHS.config_dir, RUNTIME_PATHS.data_dir)

    app.state.config = config
    app.state.mediator = mediator
    app.state.credentials_db_path = CREDENTIALS_DB_PATH
    # Built ONCE -- see module docstring for why this must not be
    # reconstructed per request.
    app.state.loop = AgentLoop.from_deployment(config, mediator)
    app.state.synthesis_client = build_llm_adapter(config, config.synthesis_model)
    app.state.executor = ThreadPoolExecutor(max_workers=config.max_concurrent_requests)

    from api.routes import router
    app.include_router(router)

    return app


app = create_app()
