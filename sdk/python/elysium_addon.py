"""
elysium_addon.py  (for an add-on's server written in Python: who is
asking, and the contract Elysium starts it under)

COPY THIS FILE INTO YOUR ADD-ON. It needs nothing but Python's standard
library and imports nothing of Elysium's, so an add-on that must not
depend on Elysium -- the simulator, whose rule is that it "does not
import [Elysium], depend on it, or know it exists" -- can carry it.
Elysium's own tests run their example add-on against this very file.

THE CONTRACT (BLOCKING.md item 3, step 2; Elysium's side in
core/addons.py and api/addon_servers.py):

  STARTED BY ELYSIUM, in the module's folder, with the command its
  `module.json` declares under `server`. The environment carries
  `PORT` -- listen on 127.0.0.1 at that port, the convention Heroku
  made ("the port to bind to is assigned by Heroku as the PORT
  environment variable") -- and `ELYSIUM_ADDON_START`, the path of a
  JSON file readable by its owner only:

      {"contract": 1, "id": "<module id>", "port": 8123,
       "identity": {"header": "X-Elysium-Identity", "secret": "...",
                    "issuer": "elysium", "audience": "<module id>"},
       "options": {... from the deployment's addons.yaml ...},
       "dataDir": "<a directory that is yours, kept across restarts>"}

  `start()` reads it.

  HEALTHY when GET on the manifest's `health` path (default /health)
  answers 200. Until it does the server is "starting"; three failures in
  a row once running and Elysium restarts it.

  STOPPED with SIGTERM, then SIGKILL after the manifest's `stopSeconds`
  (default 10) -- systemd's order. Tidy up on SIGTERM.

  STANDARD INPUT IS A PIPE FROM ELYSIUM, and it closes when Elysium
  goes -- even killed outright, when nothing gets to send SIGTERM.
  `exit_when_elysium_does()` watches it, so no server is left running
  with nobody to stop it.

  EVERY REQUEST CARRIES `X-Elysium-Identity`: a token saying who is
  asking. `identity(headers, start_info)` checks it and gives the
  claims, or raises NotSignedIn -- answer 401 then. Do NOT trust any
  other header to say who someone is; the proxy drops cookies and
  `Authorization` on the way in.
"""

import base64
import hashlib
import hmac
import json
import os
import threading
import time

#: The contract version this file speaks.
CONTRACT = 1
#: Seconds of clock difference tolerated on `exp` and `iat`.
LEEWAY_SECONDS = 5


class NotSignedIn(Exception):
    """No token, or one this add-on must not accept; answer 401."""


def start() -> dict:
    """What Elysium started this server with (see the module docstring)."""
    path = os.environ.get("ELYSIUM_ADDON_START")
    if not path:
        raise RuntimeError("ELYSIUM_ADDON_START is not set: this server is started by Elysium")
    with open(path, encoding="utf-8") as handle:
        info = json.load(handle)
    if info.get("contract") != CONTRACT:
        raise RuntimeError(f"started under contract {info.get('contract')!r}; this file speaks {CONTRACT}")
    return info


def exit_when_elysium_does(on_exit=None) -> threading.Thread:
    """Watch standard input; when it closes, call `on_exit` (default:
    leave at once, with status 0)."""

    def watch() -> None:
        # THE FILE DESCRIPTOR, NOT sys.stdin: a daemon thread blocked in
        # sys.stdin's buffered reader holds its lock, and a server leaving
        # normally then dies at interpreter shutdown -- "Fatal Python
        # error: _enter_buffered_busy: could not acquire lock for
        # <_io.BufferedReader name='<stdin>'> ... possibly due to daemon
        # threads", status -6 (SIGABRT) instead of 0. Seen in the first
        # run under real uvicorn workers; os.read takes no such lock.
        try:
            while os.read(0, 4096):
                pass
        except OSError:
            pass
        if on_exit is not None:
            on_exit()
        else:
            os._exit(0)

    thread = threading.Thread(target=watch, name="elysium-stdin", daemon=True)
    thread.start()
    return thread


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify(token: str, *, secret: str, audience: str, issuer: str = "elysium",
           now: "float | None" = None) -> dict:
    """The claims of an HS256 token from Elysium, or NotSignedIn.

    THE ALGORITHM IS FIXED, not read from the token (RFC 8725 §3.1,
    "Perform Algorithm Verification"): a token saying `"alg": "none"`
    is refused, not believed.
    """
    try:
        header_b64, body_b64, signature_b64 = token.split(".")
        header = json.loads(_unb64(header_b64))
        claims = json.loads(_unb64(body_b64))
        signature = _unb64(signature_b64)
    except (ValueError, TypeError) as error:
        raise NotSignedIn("not a token") from error
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise NotSignedIn("not signed with HS256")
    expected = hmac.new(secret.encode(), f"{header_b64}.{body_b64}".encode(), hashlib.sha256).digest()
    # A comparison taking the same time however much matches.
    if not hmac.compare_digest(signature, expected):
        raise NotSignedIn("the signature does not match")
    if not isinstance(claims, dict):
        raise NotSignedIn("its claims are not an object")
    moment = time.time() if now is None else now
    if claims.get("iss") != issuer:
        raise NotSignedIn("not issued by Elysium")
    if claims.get("aud") != audience:
        raise NotSignedIn("made for another add-on")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] + LEEWAY_SECONDS < moment:
        raise NotSignedIn("expired")
    if not isinstance(claims.get("iat"), (int, float)) or claims["iat"] - LEEWAY_SECONDS > moment:
        raise NotSignedIn("issued in the future")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise NotSignedIn("names nobody")
    return claims


def identity(headers, start_info: dict, *, now: "float | None" = None) -> dict:
    """Who is asking, from a request's headers (anything with `.get`)."""
    settings = start_info["identity"]
    token = headers.get(settings["header"])
    if not token:
        raise NotSignedIn(f"no {settings['header']} header")
    return verify(token, secret=settings["secret"], audience=settings["audience"],
                  issuer=settings["issuer"], now=now)
