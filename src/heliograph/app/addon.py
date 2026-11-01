# SPDX-FileCopyrightText: 2026 Nicholas Martin
# SPDX-License-Identifier: LicenseRef-Proprietary

"""Heliograph as an add-on server of Elysium (decision D50).

Elysium starts ``heliograph serve`` from the module's folder, hands it a port
and a start file in the environment, and forwards the browser's calls to it
as ``/api/addons/heliograph/<path>`` with a signed header saying who asks.
This module is the whole of Heliograph's side of that contract:

- ``AddonStart`` reads the start file (``ELYSIUM_ADDON_START``). Without that
  variable there is no add-on mode, and nothing here changes how the engine
  behaves.
- ``IdentityGuard`` refuses every request that does not carry a good
  ``X-Elysium-Identity`` token, except the health check the supervisor makes
  without one. The token is an HS256 JWT made with a secret that exists for
  one run of the server; the algorithm is fixed here, never read from the
  token (RFC 8725 section 3.1).
- ``Outbox`` drops a notice for Elysium's Inbox as a file, written under a
  temporary name and renamed, its name the dedupe key.
- ``exit_when_elysium_does`` leaves when standard input (a pipe from Elysium)
  closes, so no server outlives an Elysium that was killed.

Written from Elysium's contract (``core/addons.py`` and
``sdk/python/elysium_addon.py`` at ``348414e0``), not copied from its files.
``tests/support/elysium.py`` signs tokens the way Elysium's ``sign_identity``
does, and ``tests/app/test_addon.py`` checks this guard against them.
"""

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from heliograph.app.config import ConfigError
from heliograph.core.clock import Clock
from heliograph.core.errors import HeliographError

START_VARIABLE = "ELYSIUM_ADDON_START"
"""The environment variable naming the start file; its presence is add-on mode."""

CONTRACT = 1
"""The version of Elysium's add-on contract this file speaks."""

MODULE = "heliograph"
"""The module's id, as ``integrations/elysium/module.json`` declares it."""

LEEWAY_SECONDS = 5
"""Seconds of clock difference tolerated on a token's ``iat`` and ``exp``."""

HEALTH = "/api/health"
"""The path ``module.json`` names as the health check; the only one answered unsigned."""

USE = "use"
"""The declared permission to read: backtests, reports, charts, plug-ins, configurations."""

OPERATE = "operate"
"""The declared permission to change anything: submit a backtest, keep a configuration."""

LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})

_NAME = re.compile(r"[A-Za-z0-9_-]{1,100}")
"""What Elysium accepts as an outbox file's name (its dedupe key)."""

NOTICE_SUMMARY = 200
NOTICE_DETAIL = 4000
"""The longest summary and detail Elysium takes in a notice."""


class NotSignedInError(HeliographError, PermissionError):
    """A request carried no token, or one this add-on must not accept."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AddonStart:
    """What Elysium started this server with: the start file's content."""

    id: str
    port: int
    header: str
    secret: str = field(repr=False)
    issuer: str
    audience: str
    options: Mapping[str, Any]
    data_dir: Path
    outbox: Path | None

    @staticmethod
    def from_environment(environ: Mapping[str, str]) -> "AddonStart | None":
        """The start file ``ELYSIUM_ADDON_START`` names; ``None`` outside Elysium.

        Raises:
            ConfigError: if the file cannot be read, is not what the contract
                describes, or is for another module.
        """
        if START_VARIABLE not in environ:
            return None
        path = environ[START_VARIABLE]
        if not path:
            # Set but empty is not "outside Elysium": a wrapper that lost the
            # path must stop the server, not leave it open.
            raise ConfigError(f"{START_VARIABLE} is set but empty")
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigError(f"cannot read the add-on start file {path}: {exc}") from exc
        try:
            return AddonStart._parse(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"the add-on start file {path} is not as expected: {exc!r}") from exc

    @staticmethod
    def _parse(raw: object) -> "AddonStart":
        if not isinstance(raw, dict):
            raise TypeError("an object was expected")
        if raw.get("contract") != CONTRACT:
            raise ValueError(f"contract {raw.get('contract')!r}, and this speaks {CONTRACT}")
        if raw["id"] != MODULE:
            raise ValueError(f"started as module {raw['id']!r}, not {MODULE!r}")
        identity = raw["identity"]
        options = raw.get("options") or {}
        if not isinstance(options, dict):
            raise TypeError("options must be an object")
        outbox = raw.get("outbox")
        start = AddonStart(
            id=str(raw["id"]),
            port=int(raw["port"]),
            header=str(identity["header"]),
            secret=str(identity["secret"]),
            issuer=str(identity["issuer"]),
            audience=str(identity["audience"]),
            options=options,
            data_dir=Path(raw["dataDir"]),
            outbox=Path(outbox) if outbox else None,
        )
        if not start.secret or not start.header:
            raise ValueError("the identity needs a header and a secret")
        return start


@dataclass(frozen=True, slots=True)
class Identity:
    """Who a good token says is asking, and what of this module they may do."""

    user: str
    permissions: frozenset[str]

    def holds(self, name: str) -> bool:
        """Whether the person holds this module's declared permission ``name``."""
        return f"module:{MODULE}:{name}" in self.permissions


def _unbase64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify(token: str, start: AddonStart, now: float) -> Identity:
    """The identity a token from Elysium states.

    Raises:
        NotSignedInError: if it is not HS256, not signed with this run's
            secret, not for this module and issuer, expired (a few seconds'
            leeway), issued in the future, or names nobody.
    """
    try:
        header_part, body_part, signature_part = token.split(".")
        header = json.loads(_unbase64(header_part))
        claims = json.loads(_unbase64(body_part))
        signature = _unbase64(signature_part)
    except (ValueError, TypeError, binascii.Error, RecursionError) as exc:
        raise NotSignedInError("not a token") from exc
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise NotSignedInError("not signed with HS256")
    expected = hmac.new(
        start.secret.encode(), f"{header_part}.{body_part}".encode(), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(signature, expected):
        raise NotSignedInError("the signature does not match")
    if not isinstance(claims, dict):
        raise NotSignedInError("its claims are not an object")
    if claims.get("iss") != start.issuer:
        raise NotSignedInError("not issued by Elysium")
    if claims.get("aud") != start.audience:
        raise NotSignedInError("made for another add-on")
    expires, issued = claims.get("exp"), claims.get("iat")
    if isinstance(expires, bool) or not isinstance(expires, int | float):
        raise NotSignedInError("it has no expiry")
    if expires + LEEWAY_SECONDS < now:
        raise NotSignedInError("expired")
    if isinstance(issued, bool) or not isinstance(issued, int | float):
        raise NotSignedInError("it has no issue time")
    if issued - LEEWAY_SECONDS > now:
        raise NotSignedInError("issued in the future")
    user = claims.get("sub")
    if not isinstance(user, str) or not user:
        raise NotSignedInError("names nobody")
    held = claims.get("permissions") or []
    if not isinstance(held, list) or not all(isinstance(p, str) for p in held):
        raise NotSignedInError("its permissions are not a list of names")
    return Identity(user=user, permissions=frozenset(held))


def needed(method: str) -> str:
    """The module permission a request needs: reading takes ``use``, anything
    that changes something takes ``operate``."""
    return USE if method in ("GET", "HEAD") else OPERATE


class IdentityGuard:
    """ASGI middleware: no request reaches the API without a good token.

    Elysium checks the session and that the module is offered to the person
    before it forwards a request; this checks again, because the server must
    not take a proxy's word for what a signed token does not say. The one
    exception is ``GET`` of the health path, which the supervisor asks
    without a token; everything else, an unknown path included, is refused
    without one. WebSocket connections are refused outright: the engine has
    none, and Elysium's proxy passes none.
    """

    def __init__(self, app: ASGIApp, *, start: AddonStart, clock: Clock) -> None:
        self._app = app
        self._start = start
        self._clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if kind != "http":
            await self._app(scope, receive, send)
            return
        method, path = scope["method"], scope["path"]
        if method == "GET" and path == HEALTH:
            await self._app(scope, receive, send)
            return
        refusal = self._refusal(scope, method)
        if refusal is not None:
            await refusal(scope, receive, send)
            return
        await self._app(scope, receive, send)

    def _refusal(
        self, scope: Scope, method: str
    ) -> Callable[[Scope, Receive, Send], Awaitable[None]] | None:
        wanted = self._start.header.lower().encode("latin-1")
        token = next((v for k, v in scope["headers"] if k.lower() == wanted), None)
        if token is None:
            return JSONResponse({"error": f"no {self._start.header} header"}, status_code=401)
        now = self._clock.now() / 1_000_000_000
        try:
            who = verify(token.decode("latin-1"), self._start, now)
        except NotSignedInError as exc:
            return JSONResponse({"error": f"not signed in: {exc}"}, status_code=401)
        permission = needed(method)
        if not who.holds(permission):
            return JSONResponse(
                {"error": f"{who.user} lacks the {MODULE} permission {permission!r}"},
                status_code=403,
            )
        scope.setdefault("state", {})["user"] = who.user
        return None


def notice_name(run: str) -> str:
    """An outbox file name for a run's notice: the run's id when Elysium takes
    it as a name, else a cleaned and shortened id with a hash of the whole,
    so two runs never share a name and one run always has the same."""
    plain = f"backtest-{run}"
    if _NAME.fullmatch(plain):
        return plain
    digest = hashlib.sha256(run.encode()).hexdigest()[:12]
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", run)[:70]
    return f"backtest-{cleaned}-{digest}"


@dataclass(frozen=True, slots=True)
class Outbox:
    """Elysium's outbox folder for this add-on: a file in it is a notice for the
    Inbox, delivered to everyone the module is offered to, once per file name."""

    folder: Path

    def post(self, name: str, summary: str, detail: str | None = None) -> Path:
        """Write the notice ``name`` (written twice, delivered once) and give its path.

        Raises:
            ValueError: if ``name`` is not 1 to 100 letters, digits, ``_`` or ``-``.
        """
        if not _NAME.fullmatch(name):
            raise ValueError(f"an outbox name is 1 to 100 letters, digits, _ or -, not {name!r}")
        body: dict[str, Any] = {"to": "everyone", "summary": summary[:NOTICE_SUMMARY]}
        if detail is not None:
            body["detail"] = detail[:NOTICE_DETAIL]
        partial = self.folder / f".{name}.part"
        target = self.folder / f"{name}.json"
        partial.write_text(json.dumps(body), encoding="utf-8")
        os.replace(partial, target)
        return target

    def backtest_finished(self, run: str, error: str | None) -> None:
        """Tell the Inbox a backtest ended; ``run`` is the dedupe key."""
        if error is None:
            self.post(notice_name(run), f"Backtest {run} finished")
        else:
            self.post(notice_name(run), f"Backtest {run} failed", error)


def exit_when_elysium_does(
    on_exit: Callable[[], None], read: Callable[[int, int], bytes] = os.read
) -> threading.Thread:
    """Call ``on_exit`` when standard input closes.

    Elysium starts the server with a pipe as standard input and never writes
    to it; the pipe closes when Elysium goes, killed or not. It reads the
    descriptor itself, not ``sys.stdin``, whose lock a daemon thread blocked
    in it would hold at interpreter exit.
    """

    def watch() -> None:
        try:
            while read(0, 4096):
                pass
        except OSError:
            pass
        on_exit()

    thread = threading.Thread(target=watch, name="elysium-stdin", daemon=True)
    thread.start()
    return thread


def refuse_open_host(host: str) -> None:
    """Add-on mode listens on this computer only: a token is no defence for a
    server open to the network.

    Raises:
        ConfigError: if ``host`` is not a loopback address.
    """
    if host not in LOOPBACK:
        raise ConfigError(
            f"as an Elysium add-on the engine listens on this computer only, not {host!r}"
        )
