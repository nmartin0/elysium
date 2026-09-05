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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, Request

from api.csrf_middleware import csrf_protect
from api.request_size_limit_middleware import RequestSizeLimitMiddleware
from core.agent.agentic_loop import AgentLoop
from core.auth.credential_store import CredentialStore
from core.auth.login_attempt_tracker import LoginAttemptTracker
from core.auth.query_rate_limiter import QueryRateLimiter
from core.auth.session_store import SessionStore
from core.deployment_loader import RuntimePaths, build_llm_adapter, load_deployment_bundle, resolve_runtime_paths
from core.lock_store import LockStore
from core.ontology.write_mediator import WriteMediator
from core.pending_write_store import PendingWriteStore
from core.user_directory import UserDirectory

logger = logging.getLogger(__name__)

UI_DIST_DIR = Path(__file__).resolve().parent.parent / "ui" / "dist"


def create_app(runtime_paths: RuntimePaths | None = None) -> FastAPI:
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
        return response

    if runtime_paths is None:
        runtime_paths = resolve_runtime_paths()

    config, mediator = load_deployment_bundle(
        runtime_paths.config_dir, runtime_paths.data_dir, runtime_paths.log_dir
    )

    app.state.config = config
    app.state.mediator = mediator
    # Kept alongside the three stores below for tests/integration/
    # test_api.py's own direct, HTTP-bypassing test-setup DB access --
    # a genuinely different, legitimate need from route handlers, which
    # should use the shared store instances instead of re-deriving this
    # path and calling a free function on every single request.
    app.state.credentials_db_path = runtime_paths.data_dir / "credentials.db"
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
    app.state.user_directory = UserDirectory(app.state.credentials_db_path, config.roles)
    # Built ONCE -- see module docstring for why this must not be
    # reconstructed per request. Reads its own write_log directly from
    # mediator (see WriteMediator's own write_log property) -- nothing
    # to pass or verify matches here; load_deployment_bundle() always
    # constructs mediator with a real write_log, and WriteMediator's
    # own __init__ raises a clear error if that were ever not true.
    app.state.write_mediator = WriteMediator(mediator, config.roles, config.action_types)
    # Generic, resource-agnostic locking -- see core/lock_store.py's
    # own module docstring for the full mechanism. Its own, dedicated
    # SQLite file (matches write_log.db's own precedent), built
    # directly here rather than threaded through load_deployment_
    # bundle() -- this is shell-level infrastructure, not part of a
    # specific deployment's own config/schema/mediator the way that
    # function's own return value is.
    app.state.lock_store = LockStore(runtime_paths.data_dir / "resource_locks.db")
    # THE resume-on-startup half of crash recovery -- see
    # WriteMediator.resume_pending_writes()'s own docstring for the
    # full mechanism. Runs ONCE, here, before this app ever serves a
    # request -- any write left over from a PREVIOUS run of this
    # process that crashed mid-apply gets reconciled against live
    # backend state before anything new can be proposed against the
    # same objects.
    resume_summary = app.state.write_mediator.resume_pending_writes()
    if resume_summary["resumed"] or resume_summary["already_applied"] or resume_summary["ambiguous"]:
        logger.info(f"resume_pending_writes() on startup: {resume_summary}")
    if resume_summary["ambiguous"]:
        logger.warning(
            f"{resume_summary['ambiguous']} write(s) left ambiguous after resume -- "
            f"see audit.log's write_resume_ambiguous entries for detail; these need manual review."
        )
    app.state.loop = AgentLoop.from_deployment(config, mediator, write_mediator=app.state.write_mediator)
    app.state.synthesis_client = build_llm_adapter(config, config.synthesis_model)
    app.state.executor = ThreadPoolExecutor(max_workers=config.max_concurrent_requests)
    # Shares the SAME AuditLog instance mediator itself holds -- not a
    # second, separately-constructed one that happens to point at the
    # same file, matching the "one shared instance" discipline this
    # whole app.state build already uses for write_log/credential_store/
    # session_store/user_directory.
    app.state.pending_writes = PendingWriteStore(audit_log=mediator.audit_log)

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


app = create_app()


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# RESOLVED (kept for history):
# - docs_url/redoc_url/openapi_url all explicitly set to None -- a
#   real, confirmed security bug, found during a broader "backend is
#   a kernel, frontend is userspace" audit (see mediator.py's and
#   api/routes.py's own AI-notes for the three related HTTP-response
#   leaks this same audit found): FastAPI's own /docs, /redoc, and
#   /openapi.json are ENABLED BY DEFAULT and are NOT gated by
#   get_current_user() at all -- they're registered directly on the
#   app itself, entirely outside the protected router. Confirmed
#   live, before this fix, that a completely unauthenticated request
#   could browse the FULL API surface this way, including every
#   admin-only route's own path. Elysium has no third-party API
#   consumers to serve a public explorer FOR -- the frontend already
#   knows exactly what it calls -- so there's no legitimate audience
#   left for this once that's true. Disabled outright, not merely
#   auth-gated -- a real, considered choice: gating FastAPI's own
#   built-in docs routes behind a custom auth check is possible but
#   meaningfully more involved than warranted for a feature with no
#   real audience here. A real, new, dedicated test added
#   (test_docs_redoc_openapi_are_genuinely_unavailable, tests/
#   integration/test_api.py), deliberately with NO login at all --
#   the real point is these are unreachable regardless of auth state,
#   not merely rejected for a missing session. Confirmed meaningful
#   via a real negative control. Verified live too: a real,
#   completely unauthenticated curl against a real, running server
#   confirmed all three now genuinely 404.
# - TWO real, separate bugs, both found by the user testing Stage 2's
#   real react-router-dom routing directly, both fixed in the same
#   pass, neither one caused by the other:
#
#   (1) Every real API route used to live at the SAME, unprefixed
#       paths as this app's own client-side routes could (/objects/
#       {type}/{id}, /query, ...). A raw browser page navigation to a
#       bookmarked Object View URL matched the REAL backend route
#       directly (no auth header on a page navigation), producing the
#       backend's own raw 401 JSON instead of ever loading this app.
#       A first attempt (renaming just the one colliding client-side
#       route) was explicitly judged not idiomatic or fully safe --
#       a SECOND collision (/query) was found sitting there, unfixed,
#       confirmed with a real 502 from a raw curl request. Fixed
#       properly, structurally: every real route now lives under
#       /api (include_router(router, prefix="/api"), the documented,
#       official FastAPI mechanism -- fastapi.tiangolo.com/tutorial/
#       bigger-applications/). A client-side route can never again
#       collide with a real API path, because the frontend never
#       defines one starting with /api -- not case-by-case vigilance,
#       a real, structural guarantee. ui/src/api.js's own apiFetch()
#       is the ONE place that adds this prefix; every caller in that
#       file still passes a plain, unprefixed path.
#
#   (2) A SEPARATE, genuinely unrelated bug, found while fixing (1):
#       the OLD app.mount("/", StaticFiles(..., html=True)) never
#       actually provided real SPA-fallback routing for an arbitrary
#       client-side path -- only for a literal root/directory path.
#       A fresh GET (with a real browser's own Accept: text/html) to
#       /browse -- an existing, already-shipped route, nothing to do
#       with the /api collision -- 404'd against a real, production-
#       mode server. This was ALWAYS broken; it only became
#       observable once Stage 2 added real client-side routes at all
#       (before that, everything lived at "/", which StaticFiles
#       already handled correctly). Fixed with app.frontend() --
#       FastAPI's own real, native, documented SPA-serving mechanism,
#       shipped 2026-06-20 (FastAPI 0.138.0) -- confirmed directly
#       against this project's own installed version (0.141.1), not
#       assumed from documentation alone. Correctly distinguishes a
#       real page navigation (Accept: text/html) from a request for a
#       missing sub-resource (a JS/CSS asset with Accept: */*, which
#       still 404s, never silently served index.html instead) --
#       verified directly with real curl requests using the correct
#       Accept headers for each case, catching one flawed test of my
#       own along the way (an artificially-forced Accept: text/html
#       on a .js request, which no real browser would ever send,
#       initially made this look broken when it wasn't).
#
#   Both fixes verified in BOTH dev (Vite's proxy) and production
#   (this file's own app.frontend()) modes, with real servers, not
#   assumed from one mode to generalize to the other.
