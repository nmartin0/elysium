# SPDX-FileCopyrightText: 2026 Nicholas Martin
# SPDX-License-Identifier: LicenseRef-Proprietary

"""What Elysium does to an add-on, done the way Elysium does it.

Imports nothing from ``heliograph`` (tests/meta/test_suite_rules.py), so the
process tests can use it. ``sign_identity`` is Elysium's own algorithm
(``core/addons.py`` at 348414e0): an HS256 JWT over compact, key-sorted
JSON, the header fixed. ``tests/app/test_addon.py`` keeps a copy of the token
Elysium made for a fixed input, so a drift in either side shows.
"""

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SECRET = "test-secret-for-one-run"
HEADER = "X-Elysium-Identity"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign_identity(
    secret: str,
    *,
    audience: str,
    user_id: str,
    now: float | None = None,
    permissions: Iterable[str] = (),
    issuer: str = "elysium",
    expires_in: int = 60,
) -> str:
    """The token Elysium's proxy puts in ``X-Elysium-Identity``."""
    issued = int(time.time() if now is None else now)  # noqa: TID251 -- a test double of Elysium
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": user_id,
        "name": user_id,
        "iat": issued,
        "exp": issued + expires_in,
        "permissions": sorted(permissions),
    }
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(signature)}"


def write_start_file(
    folder: Path,
    *,
    port: int = 0,
    options: dict[str, Any] | None = None,
    module: str = "heliograph",
) -> Path:
    """The start file Elysium writes (``api/addon_servers.py``, ``spawn``), with an
    outbox and a data folder made beside it."""
    (folder / "outbox").mkdir(parents=True, exist_ok=True)
    (folder / "data").mkdir(exist_ok=True)
    path = folder / "start.json"
    path.write_text(
        json.dumps(
            {
                "contract": 1,
                "id": module,
                "port": port,
                "identity": {
                    "header": HEADER,
                    "secret": SECRET,
                    "issuer": "elysium",
                    "audience": module,
                },
                "options": options or {},
                "dataDir": str(folder / "data"),
                "outbox": str(folder / "outbox"),
            }
        )
    )
    return path


def token(
    *permissions: str, user: str = "alice", module: str = "heliograph", now: float | None = None
) -> str:
    """A good token for ``user`` holding the module's permissions ``permissions``."""
    return sign_identity(
        SECRET,
        audience=module,
        user_id=user,
        permissions=[f"module:{module}:{p}" for p in permissions],
        now=now,
    )
