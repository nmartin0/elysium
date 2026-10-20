"""
rest.py  (a Json api on localhost, the shape small-business SaaS has)

The fourth way a small business'S data is reached, after a database on
a port, a database in a file, and a folder of CSV. Square, Stripe,
Shopify, QuickBooks Online, ServiceTitan, Jobber: none of them hand
anyone a database connection. They expose a paginated Json api behind
a bearer token, and that is the only way in. Foundry connects to these
through its Rest api source type.

What makes this authentic is not "it returns JSON". It is the four
things a consumer of such an API has to survive, none of which any
fixture reproduces:

  - pagination. A collection does not arrive in one response. It
    arrives in pages with an opaque cursor, and a consumer that reads
    the first page and stops silently loses everything after it. That
    is the single most common integration bug against APIs of this
    shape, and it is silent -- the data looks fine, there is just less
    of it.
  - authentication. A bearer token, and a 401 without it. A consumer
    that forgets the header gets a well-formed JSON error rather than
    a connection failure, which is a different thing to handle.
  - rate limiting. 429 with a Retry-After header. Real APIs do this
    and a consumer that ignores it makes the problem worse.
  - timestamps as strings. ISO 8601 with an offset, not epoch
    integers, because that is what these APIs emit -- and parsing them
    is a real source of off-by-one-day errors.

The cursor is opaque on purpose. It encodes an offset, but it is
base64 and a consumer has no business decoding it -- that is exactly
how real cursors behave, and a consumer that cracks one open and does
arithmetic on it is writing a bug this silo should not make easy.

Not a framework. http.server from the standard library, in a thread.
The simulator has two runtime dependencies and this is not worth a
third: the surface is four verbs on a handful of collections, and a
web framework would bring routing, validation and middleware that
nothing here needs.
"""

import base64
import binascii
import json
import math
import random
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

from simulator.silo import ConnectionDescriptor, Silo, SiloError
from simulator.silos.nodatabase import refuse_database

#: Square's default and a common one across these APIs. Small enough
#: that any realistic collection spans several pages, which is the
#: point: a consumer that ignores the cursor must visibly lose data.
DEFAULT_PAGE_SIZE = 100

#: The prefix these APIs conventionally version under.
API_PREFIX = "/v1"

#: Seconds a 429 asks the caller to wait when no window is running.
#: Real values vary; what matters is that the header is there to be
#: honoured or ignored.
RETRY_AFTER_SECONDS = 2

#: How long a rate-limit window lasts, in REAL seconds: a consumer waits
#: in wall time, as it would on Xero's 60-calls-a-minute limit
#: (developer.xero.com/faq/limits). REAL_SOURCES.md R2: the window used
#: to turn only when something called reset_rate_limit(), and nothing in
#: a running world did -- so once on, the API refused for ever.
DEFAULT_RATE_WINDOW_SECONDS = 60.0

#: How long a maintenance 503 asks the caller to wait.
MAINTENANCE_RETRY_AFTER_SECONDS = 30

#: Where a client exchanges its id and secret for an access token, when
#: tokens expire (`token_lifetime_seconds`). The client-credentials grant
#: (RFC 6749 section 4.4) is what Xero's server-to-server "custom
#: connections" use, with access tokens that "expire after 30 minutes"
#: and no refresh token (developer.xero.com/faq/custom-integration).
TOKEN_PATH = "/oauth/token"

#: The statuses a failing request answers with, by default: the server
#: errors Stripe lists (docs.stripe.com/api/errors) and a gateway in front
#: of an API gives.
DEFAULT_FAULT_STATUSES = (500, 502, 503, 504)

_SHUTDOWN_TIMEOUT = 10


def _encode_cursor(offset: int) -> str:
    """An opaque cursor. Base64 so it is obviously not for reading."""
    return base64.urlsafe_b64encode(f"offset:{offset}".encode()).decode()


def _decode_cursor(cursor: str) -> int:
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
        prefix, _, value = decoded.partition(":")
        if prefix != "offset":
            raise ValueError(decoded)
        return int(value)
    except (ValueError, UnicodeDecodeError, binascii.Error) as error:
        raise ValueError(f"malformed cursor: {cursor!r}") from error


class _Handler(BaseHTTPRequestHandler):
    """Routing for one silo. Held on the server, not on the class."""

    #: Set by the silo when the server is created.
    silo: "RestSilo"

    def log_message(self, format: str, *args: object) -> None:
        """Silence. http.server logs every request to stderr by
        default, which would bury a test run's real output."""

    def do_GET(self) -> None:  # noqa: N802 -- http.server's naming
        silo = self.server.silo  # type: ignore[attr-defined]

        if silo.maintenance:
            # Down for maintenance (simulator/outages.py): what real APIs
            # serve -- Stripe lists 503 among its server errors -- with a
            # Retry-After saying when to come back.
            self._respond(503, {"errors": [{"code": "MAINTENANCE",
                                            "detail": "Down for maintenance"}]},
                          extra_headers={"Retry-After": str(MAINTENANCE_RETRY_AFTER_SECONDS)})
            return

        silo._delay()
        allowed, limit_headers = silo._rate_limit_allows()
        if not allowed:
            self._respond(429, {"errors": [{"code": "RATE_LIMITED",
                                            "detail": "Too many requests"}]},
                          extra_headers=limit_headers)
            return
        self._limit_headers = limit_headers

        fault = silo._fault()
        if fault is not None:
            # A server error a retry may well get past: what a real API
            # gives now and then, and a gateway in front of it more often.
            self._respond(fault, {"errors": [{"code": "SERVER_ERROR",
                                              "detail": "The server could not answer"}]})
            return

        refusal = silo._refuse_token(self.headers.get("Authorization", ""))
        if refusal is not None:
            # A well-formed JSON error, not a connection failure --
            # which is a different thing for a consumer to handle, and
            # the thing that really happens. An expired token says so in
            # WWW-Authenticate, as RFC 6750 section 3.1 has it.
            detail, challenge = refusal
            self._respond(401, {"errors": [{"code": "UNAUTHORIZED", "detail": detail}]},
                          extra_headers={"WWW-Authenticate": challenge} if challenge else None)
            return

        path, _, query = self.path.partition("?")
        if not path.startswith(f"{API_PREFIX}/"):
            self._respond(404, {"errors": [{"code": "NOT_FOUND", "detail": path}]})
            return

        collection = path[len(API_PREFIX) + 1:].strip("/")
        if collection not in silo.collections:
            self._respond(404, {"errors": [{"code": "NOT_FOUND",
                                            "detail": f"No such collection: {collection}"}]})
            return

        parameters = dict(
            pair.split("=", 1) for pair in query.split("&") if "=" in pair
        )
        try:
            offset = _decode_cursor(parameters["cursor"]) if "cursor" in parameters else 0
        except ValueError as error:
            self._respond(400, {"errors": [{"code": "INVALID_CURSOR", "detail": str(error)}]})
            return

        records = silo.collections[collection]
        since = self.headers.get("If-Modified-Since")
        if since and silo.modified_since_field is not None:
            try:
                records = silo._modified_since(records, since)
            except ValueError as error:
                self._respond(400, {"errors": [{"code": "INVALID_DATE", "detail": str(error)}]})
                return
        page = records[offset: offset + silo.page_size]
        next_offset = offset + len(page)
        body: dict[str, object] = {"data": page}
        if next_offset < len(records):
            body["cursor"] = _encode_cursor(next_offset)
        self._respond(200, body)

    def do_POST(self) -> None:  # noqa: N802 -- http.server's naming
        """The token endpoint, and nothing else: this API takes no writes."""
        silo = self.server.silo  # type: ignore[attr-defined]
        path = self.path.partition("?")[0]
        if path != TOKEN_PATH or silo.token_lifetime_seconds is None:
            self._respond(404, {"errors": [{"code": "NOT_FOUND", "detail": path}]})
            return
        silo._delay()
        length = int(self.headers.get("Content-Length") or 0)
        form = dict(pair.split("=", 1) for pair in
                    self.rfile.read(length).decode().split("&") if "=" in pair)
        status, body = silo._issue_token(self.headers.get("Authorization", ""), form)
        self._respond(status, body)

    def _respond(self, status: int, body: dict, *, extra_headers: dict | None = None) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        # Where the caller stands against the rate limit, on every reply
        # while one is on -- as GitHub's x-ratelimit-* headers are.
        for name, value in {**getattr(self, "_limit_headers", {}), **(extra_headers or {})}.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)


class RestSilo(Silo):
    """One silo exposed as a paginated Json api on localhost."""

    kind: ClassVar[str] = "rest"
    requires_port: ClassVar[bool] = True

    def __init__(self, name: str, data_dir: Path, port: int, *,
                 token: str | None = "sim-token", page_size: int = DEFAULT_PAGE_SIZE,
                 rate_limit: int | None = None,
                 rate_window_seconds: float | None = DEFAULT_RATE_WINDOW_SECONDS,
                 token_lifetime_seconds: float | None = None,
                 fault_rate: float = 0.0,
                 fault_statuses: Sequence[int] = DEFAULT_FAULT_STATUSES,
                 latency_ms: float = 0.0, latency_jitter_ms: float = 0.0,
                 modified_since_field: str | None = None) -> None:
        super().__init__(name, data_dir)
        self.port = port
        #: None disables authentication entirely. Some small-business
        #: APIs really are open on a private network, and a pack should
        #: be able to say so rather than have a token forced on it.
        self.token = token
        self.page_size = page_size
        #: Requests allowed before 429s begin. None means no limit,
        #: which is the sane default -- a limiter on by default would
        #: make every consumer's first run fail for a reason that is
        #: not about the data.
        self.rate_limit = rate_limit
        self.rate_window_seconds = rate_window_seconds
        # The realism options (REAL_SOURCES.md R1, R3, R7), all off unless
        # a pack switches them on, as Toxiproxy's toxics are off until added.
        if token_lifetime_seconds is not None:
            if token is None:
                raise SiloError(f"{name}: tokens that expire need a client secret (`token`)")
            if token_lifetime_seconds <= 0:
                raise SiloError(f"{name}: token_lifetime_seconds must be positive")
        if not 0.0 <= fault_rate <= 1.0:
            raise SiloError(f"{name}: fault_rate is a share of requests, from 0 to 1")
        if not fault_statuses or any(not 500 <= int(status) <= 599 for status in fault_statuses):
            raise SiloError(f"{name}: fault_statuses are server errors, 500 to 599")
        if latency_ms < 0 or latency_jitter_ms < 0 or latency_jitter_ms > latency_ms:
            raise SiloError(f"{name}: latency_ms and latency_jitter_ms must be >= 0, "
                            f"the jitter no larger than the latency")
        #: Real seconds an access token lasts; None keeps one token for
        #: ever, as an API key does. When set, `token` is the client
        #: secret, exchanged at TOKEN_PATH for tokens that expire.
        self.token_lifetime_seconds = token_lifetime_seconds
        self.client_id = f"{name}-client"
        self._issued: dict[str, float] = {}
        #: The share of requests answered with a server error, and which:
        #: Toxiproxy's "toxicity", applied per request.
        self.fault_rate = fault_rate
        self.fault_statuses = tuple(int(status) for status in fault_statuses)
        #: Every reply delayed by latency +/- jitter, in milliseconds, as
        #: Toxiproxy's latency toxic does.
        self.latency_ms = latency_ms
        self.latency_jitter_ms = latency_jitter_ms
        #: The record field a GET's If-Modified-Since is compared with:
        #: Xero's filter. None ignores the header, as most APIs would.
        self.modified_since_field = modified_since_field
        #: Seeded by name: the same share of requests fails each run, though
        #: which ones depends on the order requests arrive in.
        self._random = random.Random(f"rest:{name}")
        self._sleep = time.sleep
        #: Wall time, replaceable by a test so it need not wait a minute.
        self._clock = time.monotonic
        self._window_started = self._clock()
        self.collections: dict[str, list[dict]] = {}
        #: True during an outage (simulator/outages.py): every request 503s.
        self.maintenance = False
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._request_count = 0
        self._lock = threading.Lock()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    # -- lifecycle ---------------------------------------------------

    def create(self) -> None:
        """Nothing on disk. The collections live in memory.

        Not a stub: this silo's state is whatever the simulation has
        published into it, and persisting that to disk would be a
        second copy to keep in step with no reader for it.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        if self._server is not None:
            return
        try:
            server = ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        except OSError as error:
            raise SiloError(f"{self.name}: cannot listen on port {self.port}: {error}") from error
        # Loopback only, by the bind address above. A simulated
        # business answering on a LAN interface would be a genuinely
        # bad thing to leave running.
        server.silo = self  # type: ignore[attr-defined]
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True,
                                        name=f"rest-silo-{self.name}")
        self._thread.start()

    def stop(self) -> None:
        """Stop serving. Quiet if it never was.

        Promises the outcome rather than the mechanism, the same as
        every other silo: a server already torn down by terminate()
        must not turn a teardown into an error.
        """
        server, thread = self._server, self._thread
        self._server, self._thread = None, None
        if server is None:
            return
        try:
            server.shutdown()
        except OSError:
            # terminate() closed the socket underneath it. The outcome
            # -- not serving -- is already achieved.
            pass
        server.server_close()
        if thread is not None:
            thread.join(timeout=_SHUTDOWN_TIMEOUT)

    def is_reachable(self) -> bool:
        """Whether the API answers at all.

        Any HTTP status counts, including 401 and 429. Those mean the
        service is up and is refusing this particular request, which is
        a different condition from the service being down -- and
        conflating them is how a health check reports an outage during
        a rate-limit window.
        """
        # Long enough to wait out the latency a pack set: a slow API is
        # slow, not down.
        wait = 2 + (self.latency_ms + self.latency_jitter_ms) / 1000.0
        try:
            urllib.request.urlopen(f"{self.base_url}{API_PREFIX}/", timeout=wait)
            return True
        except urllib.error.HTTPError:
            return True
        except OSError:
            return False

    def connection(self, database: str | None = None) -> ConnectionDescriptor:
        refuse_database(self.name, self.kind, database)
        details: dict[str, object] = {"base_url": self.base_url, "format": "json"}
        if self.token is not None and self.token_lifetime_seconds is not None:
            # What a consumer is given for a client-credentials API: where
            # to ask, and as whom. Never a token, which would expire.
            details["auth"] = "oauth_client_credentials"
            details["token_url"] = f"{self.base_url}{TOKEN_PATH}"
            details["client_id"] = self.client_id
            details["client_secret"] = self.token
        elif self.token is not None:
            details["auth"] = "bearer"
            details["token"] = self.token
        return ConnectionDescriptor(kind=self.kind, details=details)

    def terminate(self) -> None:
        """Drop the listening socket without a graceful shutdown.

        The API equivalent of a process being killed: connections stop
        being accepted immediately, mid-flight requests are cut, and a
        consumer sees a connection error rather than a clean response.
        """
        server = self._server
        if server is None:
            return
        try:
            server.socket.close()
        except OSError:
            pass
        self._server, self._thread = None, None

    # -- publishing --------------------------------------------------

    def publish(self, collection: str, records: Sequence[dict]) -> None:
        """Replace a collection's contents."""
        with self._lock:
            self.collections[collection] = [dict(record) for record in records]

    def append(self, collection: str, record: dict) -> None:
        """Add one record, creating the collection if needed."""
        with self._lock:
            self.collections.setdefault(collection, []).append(dict(record))

    # -- realism (REAL_SOURCES.md R1, R3, R7) ---------------------------

    def _delay(self) -> None:
        if self.latency_ms <= 0:
            return
        with self._lock:
            jitter = self._random.uniform(-self.latency_jitter_ms, self.latency_jitter_ms)
        self._sleep((self.latency_ms + jitter) / 1000.0)

    def _fault(self) -> "int | None":
        if self.fault_rate <= 0:
            return None
        with self._lock:
            if self._random.random() >= self.fault_rate:
                return None
            return self._random.choice(self.fault_statuses)

    def _refuse_token(self, header: str) -> "tuple[str, str | None] | None":
        """None if the Authorization header may pass; otherwise what to
        say, and the WWW-Authenticate challenge."""
        if self.token is None:
            return None
        if self.token_lifetime_seconds is None:
            if header == f"Bearer {self.token}":
                return None
            return "Missing or invalid bearer token", None
        presented = header[len("Bearer "):] if header.startswith("Bearer ") else ""
        with self._lock:
            expires = self._issued.get(presented)
            now = self._clock()
        if expires is None:
            return ("Missing or invalid bearer token",
                    'Bearer error="invalid_token", error_description="Unknown token"')
        if now >= expires:
            return ("The access token expired",
                    'Bearer error="invalid_token", error_description="The access token expired"')
        return None

    def _issue_token(self, header: str, form: dict) -> "tuple[int, dict]":
        """RFC 6749 section 4.4: the client authenticates by HTTP Basic or
        by form fields (section 2.3.1) and is given a token that expires."""
        form = {key: urllib.parse.unquote_plus(value) for key, value in form.items()}
        client_id, secret = form.get("client_id"), form.get("client_secret")
        if header.startswith("Basic "):
            try:
                pair = base64.b64decode(header[len("Basic "):]).decode()
            except (binascii.Error, UnicodeDecodeError):
                pair = ""
            client_id, _, secret = pair.partition(":")
        if client_id != self.client_id or secret != self.token:
            return 401, {"error": "invalid_client"}
        if form.get("grant_type") != "client_credentials":
            return 400, {"error": "unsupported_grant_type"}
        assert self.token_lifetime_seconds is not None  # the caller checked
        issued = secrets.token_urlsafe(24)
        with self._lock:
            now = self._clock()
            # Expired ones are forgotten, so a long run does not grow a list.
            self._issued = {t: e for t, e in self._issued.items() if e > now}
            self._issued[issued] = now + self.token_lifetime_seconds
        return 200, {"access_token": issued, "token_type": "Bearer",
                     "expires_in": int(self.token_lifetime_seconds)}

    def _modified_since(self, records: list[dict], since: str) -> list[dict]:
        """Records whose `modified_since_field` is at or after `since`.

        An ISO 8601 moment, as Xero's examples give, or an HTTP-date
        (RFC 9110), which is what the header formally carries. A moment
        without an offset is UTC, as Xero says its dates are."""
        def moment(text: str) -> datetime:
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(text)
                except (TypeError, ValueError) as error:
                    raise ValueError(f"not a date: {text!r}") from error
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

        threshold = moment(since)
        field = self.modified_since_field
        kept = []
        for record in records:
            value = record.get(field)
            if value is None:
                continue        # never modified, as far as the API can say
            try:
                changed = moment(str(value))
            except ValueError:
                # The API's own data, not the caller's header, is at fault;
                # it is served rather than silently dropped.
                kept.append(record)
                continue
            if changed >= threshold:
                kept.append(record)
        return kept

    # -- rate limiting -----------------------------------------------

    def _rate_limit_allows(self) -> tuple[bool, dict[str, str]]:
        """(allowed, headers saying where the caller stands).

        The window rolls on the clock, as real APIs' do, unless
        `rate_window_seconds` is None, which keeps the old manual window
        for a test or a scenario that wants to turn it itself. Headers in
        GitHub's x-ratelimit-* form, and on a refusal a Retry-After of the
        seconds the window has left (RFC 9110)."""
        if self.rate_limit is None:
            return True, {}
        with self._lock:
            now = self._clock()
            if self.rate_window_seconds is not None and \
                    now - self._window_started >= self.rate_window_seconds:
                self._window_started, self._request_count = now, 0
            self._request_count += 1
            allowed = self._request_count <= self.rate_limit
            if self.rate_window_seconds is None:
                left = float(RETRY_AFTER_SECONDS)
            else:
                left = max(0.0, self.rate_window_seconds - (now - self._window_started))
            headers = {"X-RateLimit-Limit": str(self.rate_limit),
                       "X-RateLimit-Remaining": str(max(0, self.rate_limit - self._request_count)),
                       "X-RateLimit-Reset": str(math.ceil(left))}
            if not allowed:
                headers["Retry-After"] = str(max(1, math.ceil(left)))
            return allowed, headers

    def reset_rate_limit(self) -> None:
        """Begin a fresh window.

        Real APIs reset on a rolling clock. This is deliberately manual
        so a pack or a scenario decides when the window turns, rather
        than a consumer's behaviour depending on how long a test took.
        """
        with self._lock:
            self._request_count = 0
            self._window_started = self._clock()


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section
# whenever something genuinely open, deferred, or rejected comes up here.
# =============================================================================
#
# RESOLVED (kept for history): cursors are base64 rather than a plain integer
# offset, and are decoded only here. Real cursors are opaque, and a consumer
# that cracks one open and does arithmetic on it is writing a bug -- one this
# silo should not make easy by handing out a readable number.
#
# RESOLVED: rate limiting is off by default. A limiter on by default would make
# a consumer's first run fail for a reason that has nothing to do with the
# data. Its window used to turn only by hand, which nothing in a running world
# did, so once on it refused for ever; since 20 October it rolls on a clock a
# test can replace (REAL_SOURCES.md R2), and rate_window_seconds=None keeps the
# manual window for a scenario that wants it.
#
# RESOLVED: is_reachable() counts 401 and 429 as reachable. Those mean the
# service is up and refusing this request, which is a different condition from
# the service being down; conflating them is how a health check reports an
# outage during a rate-limit window.
#
# RESOLVED: ConnectionDescriptor carries a token for this kind, which
# contradicts an earlier claim in simulator/silo.py that no silo has
# credentials. That claim was true when every silo trusted loopback and is not
# now -- the docstring there has been corrected rather than left to rot.
#
# DEFERRED (known, intentional, not yet built): GET only. These APIs also
# accept writes, and a consumer with writeback enabled would POST. Adding it
# means deciding what a write does to a simulation that owns the data, which is
# a real design question and not a handler method.
#
# DEFERRED: no webhooks. Square, Stripe and QuickBooks Online all push events
# as well as serving polls, and a consumer built on webhooks behaves very
# differently from one that polls. Worth simulating; needs somewhere to push
# to, which is a consumer-side fact the simulator does not have.
#
# DEFERRED: collections live in memory, so a restart empties them. Fine while a
# run is one process; the moment a world is resumed across processes this needs
# the same treatment the other silos get from their own storage.
#
# RESOLVED (20 October, item 12 step 2): realism options, every one off unless
# a pack sets it -- token_lifetime_seconds (client credentials, as Xero's
# custom connections), fault_rate/fault_statuses and latency_ms/jitter (as
# Toxiproxy), modified_since_field (Xero's If-Modified-Since). Faults and
# jitter draw from a Random seeded by the silo's name, so a world fails the
# same way each run.
#
# DEFERRED: rotating refresh tokens (Xero's and QuickBooks' authorization-code
# apps). Client credentials is the server-to-server form a reporting tool
# uses; rotation matters to an app acting for a signed-in user.
#
# DEFERRED: a fault that cuts the connection mid-body rather than answering
# 5xx (Toxiproxy's limit_data). http.server makes it awkward; the 5xx and
# the outage cover the consumer's retry path between them.
