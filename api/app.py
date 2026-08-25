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

CREDENTIALS_DB_PATH lives inside deployment/ (deployment/credentials.db)
-- same "one fixed location, no config needed" convention already used
for deployment/logs/.
"""

from pathlib import Path

from fastapi import FastAPI

from core.agent.agentic_loop import AgentLoop
from core.deployment_loader import build_llm_adapter, load_deployment_bundle

DEPLOYMENT_DIR = Path("deployment")
CREDENTIALS_DB_PATH = DEPLOYMENT_DIR / "credentials.db"


def create_app() -> FastAPI:
    app = FastAPI(title="LLM Data Mediator")

    config, mediator = load_deployment_bundle(DEPLOYMENT_DIR)

    app.state.config = config
    app.state.mediator = mediator
    app.state.credentials_db_path = CREDENTIALS_DB_PATH
    # Built ONCE -- see module docstring for why this must not be
    # reconstructed per request.
    app.state.loop = AgentLoop.from_deployment(config, mediator)
    app.state.synthesis_client = build_llm_adapter(config, config.synthesis_model)

    from api.routes import router
    app.include_router(router)

    return app


app = create_app()
