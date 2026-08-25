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

WRITES: proposing a write over HTTP is now real (see api/routes.py's
/query and /writes/{write_id}/confirm) -- app.state.write_mediator and
app.state.pending_writes (a PendingWriteStore, see core/
pending_write_store.py) are both built here, once, same lifecycle as
everything else. Confirmation is ALWAYS a separate, later HTTP request
from the one that proposed the write -- see core/agent/agentic_loop.py's
module docstring for why AgentLoop itself was changed to never confirm
a write on its own.

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

create_app() takes an OPTIONAL RuntimePaths -- defaulting to
resolve_runtime_paths() (the real, running server's normal path) when
not given. tests/integration/test_api.py passes its OWN, fully
isolated RuntimePaths (built fresh per test, under pytest's tmp_path)
to get a genuinely separate app instance -- its own mediator, its own
credentials database, its own audit log -- rather than mutating
app.state on the one real, module-level `app` instance. That mutation
approach was the earlier design; it meant tests could (and once did)
corrupt the real, shipped demo data. A real app instance per test,
built from a real but disposable fixture, makes that structurally
impossible instead of relying on careful cleanup.
"""

from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI

from core.agent.agentic_loop import AgentLoop
from core.deployment_loader import build_llm_adapter, load_deployment_bundle, resolve_runtime_paths, RuntimePaths
from core.intermediate_layer.audit import configure_audit_log
from core.ontology.write_mediator import WriteMediator
from core.pending_write_store import PendingWriteStore


def create_app(runtime_paths: RuntimePaths | None = None) -> FastAPI:
    app = FastAPI(title="LLM Data Mediator")

    if runtime_paths is None:
        runtime_paths = resolve_runtime_paths()

    configure_audit_log(runtime_paths.log_dir)
    config, mediator = load_deployment_bundle(runtime_paths.config_dir, runtime_paths.data_dir)

    app.state.config = config
    app.state.mediator = mediator
    app.state.credentials_db_path = runtime_paths.data_dir / "credentials.db"
    # Built ONCE -- see module docstring for why this must not be
    # reconstructed per request.
    app.state.write_mediator = WriteMediator(mediator, config.roles)
    app.state.loop = AgentLoop.from_deployment(config, mediator, write_mediator=app.state.write_mediator)
    app.state.synthesis_client = build_llm_adapter(config, config.synthesis_model)
    app.state.executor = ThreadPoolExecutor(max_workers=config.max_concurrent_requests)
    app.state.pending_writes = PendingWriteStore()

    from api.routes import router
    app.include_router(router)

    return app


app = create_app()
