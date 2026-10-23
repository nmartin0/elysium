"""
addons.py  (an add-on's own server: what its manifest declares, who is
asking it, and what passes between it and the browser)

BLOCKING.md item 3, step 2: a module may bring A SERVER OF ITS OWN -- the
simulator's control panel needs one, and so does every add-on with work
Elysium does not do (Heliograph's market data). The browser never talks
to it directly. It talks to Elysium, at

    /api/addons/{module id}/{path}

and Elysium, having checked the session and that the module is offered
to this person, forwards the request to the add-on's server on loopback
(api/addon_servers.py). The owner's decisions, 22 October: ELYSIUM
STARTS the server (its lifecycle), and A SIGNED TOKEN tells it who is
asking.

THE PRECEDENTS. Home Assistant's add-on ingress: the add-on's interface
reached through Home Assistant, which "will take care of the
authentication and the secure connection". Google's Identity-Aware
Proxy for the token: the proxy puts a signed JWT in a header,
`x-goog-iap-jwt-assertion`, and an app is told to verify it rather than
trust the plain identity headers, because if the proxy is bypassed "the
attacker can forge the IAP unsigned identity headers". Loopback alone
would leave any program on the machine free to claim anyone.

THE TOKEN (`X-Elysium-Identity`) is a JWT, HS256, signed with a secret
made for that add-on each time its server starts, so

  - a program on the machine without the secret cannot make one;
  - a token made for one add-on is refused by another: the secret
    differs, and `aud` names the add-on;
  - one copied out of a log is good for a minute (`exp`).

    {"iss": "elysium", "aud": "<module id>", "sub": "<user id>",
     "name": "<user id>", "iat": ..., "exp": ...,
     "permissions": ["module:<module id>:<name>", ...]}

`permissions`: those of the add-on's own declared permissions this
person holds (core/modules.py), and no other grant of Elysium's.

A JWT and not a format of Elysium's own, so an add-on in any language
verifies it with the library it already has. `sdk/python/
elysium_addon.py` is a verifier needing nothing but Python's standard
library, for an add-on that may not import Elysium (the simulator).

WHAT PASSES. Both directions are ALLOWLISTS, not denylists: a header
nobody thought of is dropped rather than forwarded.

  - TO THE ADD-ON: what describes the request -- content type,
    language, caching validators, `Last-Event-ID` for a resumed event
    stream -- and NEVER the browser's cookies, its CSRF token or an
    `Authorization`: the session is Elysium's, and an add-on holding it
    could act as the person anywhere in Elysium. An `X-Elysium-Identity`
    the browser sent is dropped too, and the proxy's own put in its
    place.
  - TO THE BROWSER: what describes the response, and NEVER `Set-Cookie`
    -- the add-on's responses arrive on Elysium's origin, and a cookie
    set there would be set for Elysium -- nor a `Location` naming the
    add-on's own loopback address.

AND A PROXIED RESPONSE CANNOT RUN SCRIPT ON ELYSIUM'S ORIGIN: it is
served with `Content-Security-Policy: sandbox` (api/app.py), so HTML an
add-on returns -- by mistake or otherwise -- renders, if a browser opens
it, as a document with an origin of its own and no script. An add-on's
pages are its module's bundle, served by Elysium like any module's; its
server answers the bundle's calls.

Standard library only: this is a leaf of core.
"""

import base64
import hashlib
import hmac
import json
import secrets
import sys
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

#: The header carrying who is asking, to the add-on's server.
IDENTITY_HEADER = "X-Elysium-Identity"
#: Who signs the token.
ISSUER = "elysium"
#: How long a token is good for. A request reaches the add-on within
#: milliseconds of the token being made; a minute covers a clock step.
TOKEN_SECONDS = 60
#: Where an add-on's server is reached: /api/addons/{id}/{path}.
PROXY_PREFIX = "/api/addons/"
#: The policy on every proxied response (see the module docstring).
SANDBOX_POLICY = "sandbox; default-src 'none'; frame-ancestors 'none'"

#: Request headers that reach the add-on, lower-cased. Everything else is
#: dropped -- Cookie, Authorization, X-CSRF-Token and X-Elysium-Identity
#: by name, because the module docstring says why, and the rest because
#: nothing asked for them.
REQUEST_HEADERS = frozenset({
    "accept", "accept-encoding", "accept-language", "cache-control",
    "content-type", "content-language", "if-match", "if-none-match",
    "if-modified-since", "if-unmodified-since", "last-event-id", "range",
})
#: Response headers that reach the browser, lower-cased.
RESPONSE_HEADERS = frozenset({
    "cache-control", "content-disposition", "content-encoding", "content-language",
    "content-range", "content-type", "etag", "expires", "last-modified",
    "retry-after", "vary",
})


class AddonError(ValueError):
    """An add-on's server declaration that cannot be used, said with its file."""


@dataclass(frozen=True)
class ServerSpec:
    """A module's own server, as its manifest declares it:

        "server": {"command": ["{python}", "server.py"],
                   "health": "/health", "stopSeconds": 10}

    `command` runs in the module's folder. `{python}` as its first word is
    the Python running Elysium -- an add-on written in Python needs no
    interpreter of its own -- and a first word starting `./` is a program
    in the module's folder; any other is looked up on PATH.
    """

    command: tuple[str, ...]
    #: GET here answers 200 while the server is sound.
    health: str = "/health"
    #: After SIGTERM, how long it has before SIGKILL.
    stop_seconds: float = 10.0


_SERVER_KEYS = frozenset({"command", "health", "stopSeconds"})
PYTHON = "{python}"


def parse_server(path: Path, raw: object) -> "ServerSpec | None":
    """A manifest's `server`, checked; None when it declares none."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise AddonError(f"{path}: `server` must be an object with a `command`")
    unknown = sorted(set(raw) - _SERVER_KEYS)
    if unknown:
        raise AddonError(f"{path}: `server` does not understand {unknown}")
    command = raw.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(w, str) and w for w in command):
        raise AddonError(f"{path}: `server.command` must be a list of words, such as "
                         f'["{PYTHON}", "server.py"]')
    if any("{" in word for word in command[1:]) or ("{" in command[0] and command[0] != PYTHON):
        # A typo such as {pyhton} would otherwise be run as a program name.
        raise AddonError(f"{path}: `server.command` may use {PYTHON} as its first word, "
                         f"and no other placeholder")
    health = raw.get("health", "/health")
    if not isinstance(health, str) or not health.startswith("/"):
        raise AddonError(f"{path}: `server.health` must be a path such as /health")
    stop = raw.get("stopSeconds", 10)
    if isinstance(stop, bool) or not isinstance(stop, (int, float)) or not 0 < stop <= 300:
        raise AddonError(f"{path}: `server.stopSeconds` must be a number of seconds, "
                         f"more than 0 and at most 300")
    return ServerSpec(command=tuple(command), health=health, stop_seconds=float(stop))


def command_line(spec: ServerSpec, folder: Path) -> list[str]:
    """The program and its arguments, ready to run in `folder`."""
    first, rest = spec.command[0], list(spec.command[1:])
    if first == PYTHON:
        return [sys.executable, *rest]
    if first.startswith("./"):
        return [str(folder / first[2:]), *rest]
    return [first, *rest]


# --- the token ---------------------------------------------------------------


def new_secret() -> str:
    """A signing secret for one run of one add-on's server."""
    return secrets.token_urlsafe(32)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


#: The JOSE header, fixed: the algorithm is the signer's choice, never
#: the token's (RFC 8725 §3.1, "Perform Algorithm Verification").
_HEADER = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())


def sign_identity(secret: str, *, audience: str, user_id: str, now: "float | None" = None,
                  permissions: "Iterable[str]" = ()) -> str:
    """A token saying that `user_id` is asking add-on `audience`, holding
    `permissions` -- of the add-on's OWN declared permissions, those this
    person holds (step 2.3), so an add-on with several can tell who may do
    what without asking Elysium. Never Elysium's other grants: an add-on
    has no business knowing who may read Customer."""
    issued = int(time.time() if now is None else now)
    claims = {"iss": ISSUER, "aud": audience, "sub": user_id, "name": user_id,
              "iat": issued, "exp": issued + TOKEN_SECONDS, "permissions": sorted(permissions)}
    body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(secret.encode(), f"{_HEADER}.{body}".encode(), hashlib.sha256).digest()
    return f"{_HEADER}.{body}.{_b64(signature)}"


# --- what passes ---------------------------------------------------------------


def request_headers(incoming: Iterable[tuple[str, str]]) -> dict[str, str]:
    """The browser's headers that reach the add-on (REQUEST_HEADERS)."""
    return {name: value for name, value in incoming if name.lower() in REQUEST_HEADERS}


def response_headers(upstream: Iterable[tuple[str, str]]) -> dict[str, str]:
    """The add-on's headers that reach the browser (RESPONSE_HEADERS)."""
    return {name: value for name, value in upstream if name.lower() in RESPONSE_HEADERS}


# --- the outbox (step 2.4) -------------------------------------------------
#
# AN ADD-ON POSTS TO THE INBOX BY DROPPING A FILE, the owner's choice of
# 23 October over an HTTP call into Elysium: no new door into Elysium, and
# a notice written while Elysium is offline -- the simulator's world
# crashing, say -- is delivered when it is back. The spool-directory
# pattern of mail systems (Postfix's maildrop, Maildir's tmp/new): the
# writer writes under a temporary name and renames, so a reader never
# sees half a file; the reader takes the whole file or none of it.
#
#     <add-on's directory>/outbox/<name>.json
#     {"to": "everyone" | ["alice", ...], "summary": "...", "detail": "..."}
#
# DELIVERED ONLY TO PEOPLE THE MODULE IS OFFERED TO (the owner's choice):
# "everyone" means them, and a name among them; any other name is
# dropped, so an add-on can reach nobody who could not use it.
#
# THE FILE'S NAME IS THE DEDUPE KEY: a file delivered and not yet removed
# when Elysium stopped is delivered again on its return, and ignored by
# the notification store's dedupe key (core/notifications.py).

OUTBOX = "outbox"
#: Where a refused file is moved, its reason said in the add-on's log.
REFUSED = "refused"
MAX_OUTBOX_BYTES = 64 * 1024
MAX_SUMMARY = 200
MAX_DETAIL = 4000
MAX_RECIPIENTS = 500


@dataclass(frozen=True)
class OutboxMessage:
    """One notice an add-on asked for. `to` None: everyone it is offered to."""

    to: "tuple[str, ...] | None"
    summary: str
    detail: "str | None"


def parse_outbox_message(raw: bytes) -> OutboxMessage:
    """A file from an add-on's outbox, checked; AddonError says what is wrong."""
    if len(raw) > MAX_OUTBOX_BYTES:
        raise AddonError(f"larger than {MAX_OUTBOX_BYTES} bytes")
    try:
        body = json.loads(raw)
    except ValueError as error:
        raise AddonError(f"not JSON ({error})") from None
    if not isinstance(body, Mapping):
        raise AddonError("must be an object with `to` and `summary`")
    unknown = sorted(set(body) - {"to", "summary", "detail"})
    if unknown:
        raise AddonError(f"does not understand {unknown}")
    to = body.get("to")
    if to == "everyone":
        recipients = None
    elif isinstance(to, list) and to and len(to) <= MAX_RECIPIENTS and all(isinstance(n, str) and n for n in to):
        recipients = tuple(dict.fromkeys(to))
    else:
        raise AddonError(f'`to` must be "everyone" or a list of up to {MAX_RECIPIENTS} user names')
    summary = body.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_SUMMARY:
        raise AddonError(f"`summary` must be text of 1 to {MAX_SUMMARY} characters")
    detail = body.get("detail")
    if detail is not None and (not isinstance(detail, str) or len(detail) > MAX_DETAIL):
        raise AddonError(f"`detail` must be text of at most {MAX_DETAIL} characters")
    return OutboxMessage(to=recipients, summary=summary.strip(), detail=detail)


def notification_kind(module_id: str) -> str:
    """The kind an add-on's notice is stored under: shown in the Inbox as
    the module's name (api/routes.py), so an add-on declares no kinds."""
    return f"module:{module_id}"


def outbox_dedupe_key(module_id: str, file_name: str, user_id: str) -> str:
    """One notice per file per person, however often the file is read."""
    return f"addon:{module_id}:{file_name}:{user_id}"
