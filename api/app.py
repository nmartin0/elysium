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

Logging is now wired through directly, not configured separately --
load_deployment_bundle() below builds the ONE shared AuditLog instance
mediator itself owns; app.state.pending_writes reads it back from
mediator, same "shared instance, not a separate copy" discipline as
write_log/credential_store/session_store/user_directory. See
core/intermediate_layer/audit.py's own module docstring for why this
replaced the old module-level configure_audit_log() global entirely.

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

STATIC UI SERVING: if ui/dist exists (a built React app -- see ui/'s
own README), it's served by this SAME process via app.frontend() --
FastAPI's own, real, native SPA-serving mechanism (0.138.0+; see this
method's own call below for the fuller history, including a real bug
this replaced) -- one systemd unit, not a separate static host,
matching this project's "minimal ops burden" philosophy (see install/
install.sh). Registered AFTER the API router, not before -- FastAPI's
own real path operations always take priority over frontend fallback
routes, so every real API path is matched by the router first; the
frontend fallback only ever handles what's left over. A SECOND,
independent safeguard beyond that alone: the router itself only ever
matches /api/* (see its own include_router() call below), so there is
no collision possible between a real backend path and a client-side
react-router-dom route even in principle. Registration is CONDITIONAL,
not required -- a checkout where nobody's run `npm run build` yet
still runs correctly as a pure API backend; only a real install
(which does build the UI) gets it served automatically.
"""

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from api.csrf_middleware import csrf_protect
from api.generation_header_middleware import GenerationHeaderMiddleware
from api.reload import follow_reload_epoch, install_sighup_handler
from api.request_metrics_middleware import RequestMetricsMiddleware
from api.request_size_limit_middleware import RequestSizeLimitMiddleware
from core.artifact_store import ArtifactStore
from core.auth.credential_store import CredentialStore
from core.auth.database import connection
from core.auth.login_attempt_tracker import LoginAttemptTracker
from core.auth.query_rate_limiter import QueryRateLimiter
from core.auth.session_store import SessionStore
from core.concurrency import share_limits_under
from core.config_history import ConfigHistory, record_generation
from core.deployment_loader import (
    RuntimePaths,
    build_generation,
    build_live_read_adapters,
    resolve_runtime_paths,
)
from core.ontology.mediator import security_cache_scope
from core.pending_write_persistence import PendingWritePersistence
from core.pending_write_store import PendingWriteStore
from core.request_metrics import RETENTION_SECONDS, RequestMetrics
from core.source_health import source_failures
from core.sqlite_connection import (
    require_assertions_enabled,
    require_json_each,
)
from core.user_directory import UserDirectory

logger = logging.getLogger(__name__)

UI_DIST_DIR = Path(__file__).resolve().parent.parent / "ui" / "dist"


# The features denied by every response's Permissions-Policy (E-05); `()`
# is the empty allowlist -- not even this origin.
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"


def create_app(runtime_paths: RuntimePaths | None = None) -> FastAPI:
    # BEFORE anything else, including config loading. Several
    # data-integrity invariants in this project are enforced by
    # `assert` and are stripped by -O / PYTHONOPTIMIZE; starting
    # without them means silent corruption rather than louder failure.
    require_assertions_enabled()
    # THE WRITE LOG PASSES ID LISTS AS JSON, so a SQLite without
    # json_each cannot serve one. Checked here rather than discovered
    # at the first write-log read, where the error would name neither
    # the requirement nor what to do about it.
    require_json_each()

    # docs_url/redoc_url/openapi_url all explicitly None -- a real,
    # confirmed finding, part of the same broader "backend is a
    # kernel, frontend is userspace" audit: FastAPI's own /docs,
    # /redoc, and /openapi.json are ENABLED BY DEFAULT and NOT gated
    # by get_current_user() at all (registered directly on the app
    # itself, outside the protected router) -- confirmed live, not
    # assumed, that an entirely unauthenticated request could browse
    # the FULL API surface this way, including every admin-only route
    # path (GET /users/{username}/visible-schema and its own
    # siblings). Elysium has no third-party API consumers to serve a
    # public explorer FOR -- the frontend already knows exactly what
    # it calls, and there is no legitimate audience for this endpoint
    # left once that's true. Disabled outright, not merely
    # auth-gated: a real, considered choice, not the path of least
    # resistance -- gating FastAPI's own built-in docs routes behind
    # a custom auth check is possible but meaningfully more involved
    # than this app genuinely needs, for a feature with no real
    # audience here at all.
    app = FastAPI(title="LLM Data Mediator", docs_url=None, redoc_url=None, openapi_url=None)

    # VALIDATION ERRORS WITHOUT THE VALUES (E-01). FastAPI's default 422
    # returns each error's `input` -- the value that failed -- and `ctx`.
    # Measured: a login missing its username echoed the PASSWORD, and
    # /me/password echoed the caller's CURRENT one. `loc` and `msg` say
    # what was wrong and where; nothing in ui/ reads the other two
    # (checked). The owner's decision, September 21.
    @app.exception_handler(RequestValidationError)
    async def validation_errors_without_values(request: Request, exc: RequestValidationError):
        errors = [
            {key: value for key, value in error.items() if key not in ("input", "ctx")}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})

    # CSRF validation -- registered BEFORE add_security_headers below,
    # deliberately: Starlette's own middleware stack makes the LAST-
    # registered middleware the OUTERMOST one, so add_security_headers
    # (registered after this) wraps AROUND csrf_protect and therefore
    # still runs -- and still applies security headers -- even on a
    # request csrf_protect rejects and short-circuits before it ever
    # reaches a real route. Verified directly, not assumed: confirmed
    # live that a genuine 403 CSRF rejection still carries the same
    # Content-Security-Policy/X-Frame-Options headers as every other
    # response. See api/csrf_middleware.py's own docstring for why
    # this exists at all (SameSite=Strict alone, researched directly
    # against OWASP's own current CSRF guidance, was found insufficient
    # on its own).
    app.middleware("http")(csrf_protect)

    # Request size limit -- registered SECOND, between csrf_protect and
    # add_security_headers below, deliberately: a real, found gap this
    # app had NO protection against at all (confirmed directly, not
    # assumed -- neither FastAPI nor Starlette enforce a body size
    # limit by default). Registered AFTER csrf_protect so this runs
    # BEFORE it -- an oversized body is rejected before CSRF validation
    # ever spends any real work on it -- but BEFORE add_security_headers
    # below, so THAT stays the true outermost layer and still wraps
    # this middleware's own real 413 rejection too (confirmed directly,
    # with a real, isolated three-middleware test, before choosing this
    # exact registration order): every real response this app sends,
    # including a 413, carries the same, consistent security headers.
    # See api/request_size_limit_middleware.py's own docstring for the
    # full reasoning, including why this is a real ASGI middleware
    # class rather than the simpler style csrf_protect/
    # add_security_headers both use.
    app.add_middleware(RequestSizeLimitMiddleware)
    # Stamps the serving generation on every response, so a client can
    # notice a configuration reload on its next request rather than
    # believing what it was told at login. See the module docstring.
    app.add_middleware(GenerationHeaderMiddleware)
    # Times every request for the RED metrics. Added AFTER the others
    # so it wraps them: a request rejected for being too large is still
    # a request, and a dashboard that only counted the ones that got
    # through would understate the load.
    #
    # IT READS THE STORE OFF app.state AT REQUEST TIME, not at
    # registration. Middleware is registered before runtime_paths is
    # even resolved, so passing the store here would mean passing None
    # forever -- and a metrics middleware that silently recorded
    # nothing is worse than none, because the dashboard would show an
    # idle server.
    app.add_middleware(RequestMetricsMiddleware)

    # Security headers, applied to EVERY response -- a real, found gap:
    # this app previously set none at all. Verified directly before
    # writing a strict CSP, not assumed safe: grepped for inline
    # style={{}} props (zero), external <script>/<link> tags in
    # index.html (zero -- one same-origin <script type="module">
    # only), and any CDN/external CSS reference (zero) -- this app is
    # genuinely, fully self-contained, same-origin only, so a strict
    # default-src 'self' covers everything it actually needs, nothing
    # broken by tightening it this far.
    #
    # Strict-Transport-Security deliberately NOT set here -- TLS
    # termination is typically a deployment/reverse-proxy concern, not
    # this application's own code; setting it here risks either
    # conflicting with, or duplicating, whatever the real front-facing
    # proxy in a given deployment already sets. See README.md's own
    # "Known limitations, honestly" section for this noted as a real,
    # deployment-specific responsibility, not silently assumed handled.
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        # POWERFUL FEATURES, DENIED OUTRIGHT (E-05): nothing here uses a
        # camera, microphone, location, payment or USB device, so no page
        # -- nor anything injected into one -- may ask for them.
        response.headers["Permissions-Policy"] = PERMISSIONS_POLICY
        return response

    # FOLLOW ANY RELOAD ANOTHER WORKER ANNOUNCED, before this request
    # reads the configuration -- registered LAST, so it runs FIRST.
    #
    # ON THE THREAD POOL, like the SIGHUP handler's reload: the check is
    # one SELECT, but catching up is a ~22 ms rebuild, and on the event
    # loop that would stall every request in flight in this worker.
    # ONE SECURITY CACHE PER REQUEST, and none shared between requests.
    # A handler that searches and then reads a page of objects shares
    # one resolution; the next request starts empty. Starlette copies
    # this context into the thread that runs a synchronous handler, so
    # the scope reaches it. See core/ontology/mediator._SECURITY_CACHE.
    @app.middleware("http")
    async def security_cache_per_request(request: Request, call_next):
        with security_cache_scope():
            return await call_next(request)

    @app.middleware("http")
    async def follow_reload(request: Request, call_next):
        await run_in_threadpool(follow_reload_epoch, app)
        return await call_next(request)

    if runtime_paths is None:
        runtime_paths = resolve_runtime_paths()

    # ONE construction path. Everything derived from the configuration
    # files is built together, as an immutable DeploymentGeneration,
    # and the individual names below are VIEWS onto it rather than
    # independently constructed objects.
    #
    # (The five convenience attributes this once described are gone --
    # see THE ONLY REFERENCE below. This paragraph said they were
    # "kept for now" long after the migration that removed them, which
    # is a comment describing a hazard that no longer exists: the same
    # failure as a workaround, arriving from the documentation side.)
    generation = build_generation(
        runtime_paths.config_dir, runtime_paths.data_dir, runtime_paths.log_dir
    ,
        # SERVING (GOLD-8): this process answers reads, so it requires
        # published gold for every object type and refuses to start
        # without it. build_generation() itself does not, because the
        # SYNC builds generations too -- and it is what publishes gold.
        serving=True,)
    # THE ONLY REFERENCE. The five configuration-derived objects are
    # reachable through this and nowhere else -- there is deliberately
    # no app.state.config, no app.state.mediator and so on.
    #
    # Their absence is the point, not tidiness. While they existed, a
    # route could read app.state.mediator directly and get a DIFFERENT
    # generation from the one its request pinned -- schema and grants
    # disagreeing inside one request, silently, with nothing about the
    # call site looking wrong. Deleting them makes the pin structural
    # rather than advisory.
    app.state.runtime_paths = runtime_paths
    # WHAT each generation contained, not merely which one it was.
    # Without this a reload leaves an audit line saying 7 became 8 and
    # no way to see what either WAS -- see core/config_history.py.
    #
    # Its own database, beside write_log.db and artifacts.db rather
    # than inside credentials.db: configuration history has a different
    # retention story from credentials, and mixing them means a restore
    # or a purge cannot treat them differently.
    # CAPS ARE SHARED BY EVERY WORKER using this data directory -- a
    # model server's or a silo's capacity does not multiply with the
    # worker count. Before anything that limits is used.
    share_limits_under(runtime_paths.data_dir)
    app.state.config_history = ConfigHistory(runtime_paths.data_dir / "config_history.db")
    # THE EPOCH THIS WORKER STARTED AT. A fresh worker builds from the
    # latest configuration, so it is already current with every reload
    # announced before it began.
    app.state.reload_epoch = app.state.config_history.reload_epoch()
    app.state.failed_reload_epoch = None
    record_generation(app.state.config_history, generation)
    app.state.generation = generation

    # LIVE READS ARE A FALLBACK, and the service says so (GOLD-2b, the
    # owner's decision of September 22). Everything silver and gold do --
    # standardisation, the declared expectations and their quarantine,
    # duplicate-key handling, lineage, and gold itself -- lives in the
    # lake. A live read sees none of it, so a deployment running this way
    # is not running the pipeline it declared.
    if not generation.config.read_from_mirror:
        logger.warning(
            "read_from_mirror is off: reads go straight to the source databases, "
            "so standardisation, the declared expectations and their quarantine, "
            "duplicate-key handling, lineage and gold are all bypassed. This is a "
            "fallback for a deployment that has not synced yet.",
        )

    # EVERY SOURCE CHECKED AT STARTUP, each failure reported BY NAME
    # (E-13). Nothing called health_check() before, so an unreachable
    # database surfaced only as the first request that needed it failed.
    # NOT a refusal to start: the mirror may still serve its last synced
    # contents, and an operator needs the service up to see the failure
    # in Admin. Logged, and to journald under systemd.
    for silo_name, failure in source_failures(
        generation.config.silo_configs,
        build_live_read_adapters(runtime_paths, generation.config),
    ).items():
        logger.warning("Source %r failed its startup check: %s. The service is starting "
                       "anyway; reads needing it will fail until it answers.", silo_name, failure)
    config = generation.config
    # Kept alongside the three stores below for tests/integration/
    # test_api.py's own direct, HTTP-bypassing test-setup DB access --
    # a genuinely different, legitimate need from route handlers, which
    # should use the shared store instances instead of re-deriving this
    # path and calling a free function on every single request.
    app.state.credentials_db_path = runtime_paths.data_dir / "credentials.db"

    # The artifact store, wired here for the first time -- it has
    # existed since the Object Explorer work and only its own tests
    # ever constructed one.
    #
    # A SEPARATE database from credentials, deliberately. Artifacts are
    # user content with a retention story of their own; credentials are
    # the thing that must survive when everything else is discarded,
    # and mixing them means a restore or a purge cannot treat them
    # differently.
    app.state.artifact_store = ArtifactStore(runtime_paths.data_dir / "artifacts.db")
    # RED metrics: one row per request, written by
    # RequestMetricsMiddleware, read by the admin metrics route.
    app.state.request_metrics = RequestMetrics(runtime_paths.data_dir / "metrics.db")
    # A real, explicit schema-creation step, run here, once, before ANY
    # internal store below is constructed -- a real, necessary addition,
    # not previously needed: every store here used to lazily create its
    # own share of credentials.db's schema itself, on first real use
    # (core/auth/database.py's own connection() -- schema-verified once
    # per db_path, in-process, the first time ANY of these stores
    # actually ran a real query). That was always fine for a WRITE-
    # capable connection, since CREATE TABLE IF NOT EXISTS is itself a
    # write. It stops being fine the moment a genuinely READ-ONLY
    # connection (core/internal_storage.py's own InternalReadAdapter,
    # first real consumer: QueryRateLimitReader below) might be the
    # FIRST thing to ever touch this database -- a read-only connection
    # structurally cannot run CREATE TABLE either (see core/
    # sqlite_connection.py's own docstring: the authorizer denies it,
    # same as any other write-type operation), so relying on "whichever
    # store happens to run first" to create the schema would be a real,
    # order-dependent gap. This makes the guarantee explicit and
    # unconditional instead.
    with connection(app.state.credentials_db_path):
        pass
    # Built ONCE -- see module docstring for why this must not be
    # reconstructed per request, same reasoning as write_mediator
    # below. Every route now goes through these instances rather than
    # re-deriving credentials_db_path and calling a free function each
    # time -- see core/auth/credential_store.py, core/auth/session_store.py,
    # and core/user_directory.py's own docstrings for the full reasoning.
    app.state.credential_store = CredentialStore(app.state.credentials_db_path)
    app.state.session_store = SessionStore(app.state.credentials_db_path)
    app.state.login_attempt_tracker = LoginAttemptTracker(app.state.credentials_db_path)
    app.state.query_rate_limiter = QueryRateLimiter(app.state.credentials_db_path)
    # A CALLABLE, not config.roles: this object survives a reload (it
    # owns credentials.db) while the configuration it validates against
    # is replaced. A snapshot taken here would be stale the moment
    # anything reloaded -- see UserDirectory.__init__.
    app.state.user_directory = UserDirectory(
        app.state.credentials_db_path, lambda: app.state.generation.config.roles,
    )
    # Built ONCE -- see module docstring for why this must not be
    # reconstructed per request. Reads its own write_log directly from
    # mediator (see WriteMediator's own write_log property) -- nothing
    # to pass or verify matches here; load_deployment_bundle() always
    # constructs mediator with a real write_log, and WriteMediator's
    # own __init__ raises a clear error if that were ever not true.
    # STARTUP ONLY, and deliberately not part of build_generation().
    # This recovers writes interrupted by a crash; a RELOAD must not
    # repeat it, because the writes it recovers are already recovered
    # and re-running it against in-flight state is a different
    # operation with different risks.
    # OLD REQUEST TIMINGS, DROPPED AT STARTUP.
    #
    # AT STARTUP AND NOWHERE ELSE, which is a real limit rather than an
    # oversight: a server that runs for months without restarting keeps
    # accumulating. Measured at 192 KB per 10,000 requests, so ten
    # million requests is roughly 192 MB -- slow enough that restart
    # frequency is a reasonable sweep interval, and bounded enough that
    # nobody is surprised.
    #
    # The alternative, sweeping on every write, would put a DELETE in
    # the path of an occasional user request to reclaim space nobody is
    # short of. A scheduler would be a whole mechanism for the same.
    #
    # FAILURE HERE DOES NOT STOP THE SERVER. A metrics table that could
    # not be pruned is a disk-space problem for later; refusing to boot
    # over it is an outage now.
    try:
        dropped = app.state.request_metrics.forget_older_than(RETENTION_SECONDS)
        if dropped:
            logger.info(f"dropped {dropped} request metric(s) older than retention")
    except (OSError, sqlite3.Error) as e:
        logger.warning(f"request metrics not pruned at startup ({e})")

    resume_summary = generation.write_mediator.resume_pending_writes()
    if resume_summary["resumed"] or resume_summary["already_applied"] or resume_summary["ambiguous"]:
        logger.info(f"resume_pending_writes() on startup: {resume_summary}")
    if resume_summary["ambiguous"]:
        logger.warning(
            f"{resume_summary['ambiguous']} write(s) left ambiguous after resume -- "
            f"see audit.log's write_resume_ambiguous entries for detail; these need manual review."
        )
    # NOT REBUILT BY A RELOAD, and unfixable by the callable pattern
    # the other runtime-state holders use. A ThreadPoolExecutor's size
    # is fixed at construction, and rebuilding it would abandon
    # in-flight work -- so max_concurrent_requests is configuration
    # that is unreloadable by NATURE rather than by oversight.
    # templates/config.yaml says so where a deployer will read it.
    app.state.executor = ThreadPoolExecutor(max_workers=config.max_concurrent_requests)
    # Shares the SAME AuditLog instance mediator itself holds -- not a
    # second, separately-constructed one that happens to point at the
    # same file, matching the "one shared instance" discipline this
    # whole app.state build already uses for write_log/credential_store/
    # session_store/user_directory.
    # A CALLABLE: this store survives a reload while each generation
    # builds its own AuditLog. Holding an instance would stamp entries
    # with the STARTUP generation -- see PendingWriteStore.__init__.
    # THE TTL IS RUNTIME STATE, read once at startup and not rebuilt by
    # a reload -- the store survives a reload deliberately, and
    # rebuilding it to pick up a new TTL would discard every proposal
    # waiting for a decision. A changed TTL takes effect at the next
    # restart, which templates/config.yaml says.
    app.state.pending_writes = PendingWriteStore(
        ttl=timedelta(minutes=config.pending_write_ttl_minutes),
        audit_log=lambda: app.state.generation.mediator.audit_log,
        # PERSISTED, so a restart does not empty the approval queue.
        # For a product whose pitch is that writes are mediated and
        # approved, losing the queue on deploy was the worst fit
        # between the claim and the behaviour -- and the store's own
        # docstring said so, as a stated limitation.
        persistence=PendingWritePersistence(
            runtime_paths.data_dir / "pending_writes.db",
        ),
    )

    from api.routes import router
    # ALL real API routes live under /api -- a real, structural
    # guarantee, not individual, case-by-case vigilance: a client-side
    # frontend route can NEVER collide with a real backend path,
    # because the frontend never defines one starting with /api (see
    # ui/vite.config.js's own AI-notes for the real bug this closes,
    # found by the user testing a bookmarked Object View URL directly
    # -- a raw browser navigation to a path that was ALSO a real,
    # unprefixed backend route hit the backend directly, with no auth
    # header, instead of ever loading this app at all). Every existing
    # frontend/backend caller already updated to match -- see that
    # same AI-notes entry for the full list.
    # LAST, after everything is wired: a SIGHUP arriving mid-startup
    # would otherwise reload against a half-built app.state.
    install_sighup_handler(app)

    app.include_router(router, prefix="/api")

    if UI_DIST_DIR.is_dir():
        # app.frontend() -- FastAPI's own, real, native SPA-serving
        # mechanism (shipped 2026-06-20, FastAPI 0.138.0; confirmed
        # directly against this project's own installed version,
        # 0.141.1, not assumed from documentation alone). Replaces
        # the old app.mount("/", StaticFiles(..., html=True)) "hack"
        # this project used before -- REAL bug found by the user
        # testing a bookmarked client-side route directly: StaticFiles
        # (html=True) only serves index.html for an actual root/
        # directory path, NOT for an arbitrary client-side route like
        # /browse (confirmed directly: a fresh GET to that exact,
        # already-shipped, uncontroversial route 404'd against a real,
        # production-mode server -- a second, genuinely separate bug
        # from the /api-prefix collision found in the same session).
        # fallback="index.html" explicit, not "auto" -- this project
        # has no 404.html and never will, no reason to depend on
        # auto's own conditional logic for a file that doesn't exist.
        # Only ever engages for a real browser navigation (GET/HEAD,
        # Accept: text/html) -- a missing JS/CSS asset, or a genuine
        # API 404 under /api, is NEVER swallowed by this fallback.
        app.frontend("/", directory=UI_DIST_DIR, fallback="index.html")

    return app



def __getattr__(name: str) -> FastAPI:
    """`api.app.app`, built the first time something asks for it.

    IT WAS BUILT AT IMPORT: `app = create_app()` on the last line. So
    importing this module -- which every integration test does, for
    create_app -- started a whole application against the DEFAULT
    deployment, creating credentials.db, write_log.db, metrics.db,
    config_history.db and a mirror in the developer's data directory.
    Measured on a fresh clone: `python -c "import api.app"` alone made
    all five (E-08c).

    NOW LAZY (PEP 562): `uvicorn api.app:app` looks the attribute up by
    name, which lands here and builds it once; importing create_app
    never does. Chosen over uvicorn's --factory, which would change
    every command that starts the server -- the systemd unit, the docs,
    and the one typed each time.
    """
    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    built = create_app()
    # Cached as a real module attribute, so later lookups never reach
    # here again and every one returns the same app.
    globals()["app"] = built
    return built
