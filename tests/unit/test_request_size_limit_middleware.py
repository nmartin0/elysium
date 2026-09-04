"""
Tests for request_size_limit_middleware.py -- exercised directly at
the raw ASGI level (real scope/receive/send, not through TestClient),
deliberately: this is the only way to construct a request with a
missing or deliberately WRONG Content-Length header while still
sending a genuinely large real body -- exactly the case this
middleware's own real value depends on catching, and something a
real HTTP client library would never let a test construct by
accident (they compute Content-Length correctly for you).

Plain, synchronous `def test_...` functions throughout, each driving
the real, async middleware via asyncio.run() -- deliberately, not
`async def test_...` with a pytest-asyncio marker: this project has
no existing pytest-asyncio dependency anywhere (confirmed directly, a
real grep found none), and every other async code in this whole
project is already tested this same way, indirectly, through a
sync-facing interface (TestClient). asyncio.run() here is the
identical idea applied to a raw ASGI callable specifically, not a new
pattern -- no new dependency needed for one file.
"""

import asyncio
import json

from api.request_size_limit_middleware import RequestSizeLimitMiddleware


def _http_scope(headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": "/api/query",
        "headers": headers or [],
    }


def _make_receive(chunks: list[bytes]):
    # Replays real chunks as real, separate "http.request" ASGI
    # messages, more_body True until the LAST one -- the same real
    # shape a genuine, streaming client body arrives as.
    remaining = list(chunks)

    async def receive():
        chunk = remaining.pop(0)
        return {"type": "http.request", "body": chunk, "more_body": bool(remaining)}

    return receive


class _RecordingApp:
    """A minimal downstream ASGI app -- records whether it was ever invoked
    at all, and (if so) what real body it actually received."""

    def __init__(self):
        self.was_called = False
        self.received_body = b""

    async def __call__(self, scope, receive, send):
        self.was_called = True
        if scope["type"] != "http":
            # A real, minimal, honest non-http app -- no "http.request"
            # message will ever arrive for a lifespan/websocket scope,
            # so a real app wouldn't try to read one either.
            return
        while True:
            message = await receive()
            if message["type"] == "http.request":
                self.received_body += message.get("body", b"")
                if not message.get("more_body", False):
                    break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


class _RecordingSend:
    """Captures every real message sent back, in order."""

    def __init__(self):
        self.messages: list[dict] = []

    async def __call__(self, message):
        self.messages.append(message)

    @property
    def status(self) -> int | None:
        for message in self.messages:
            if message["type"] == "http.response.start":
                return message["status"]
        return None

    @property
    def body(self) -> bytes:
        return b"".join(
            message.get("body", b"") for message in self.messages if message["type"] == "http.response.body"
        )


def _run(middleware: RequestSizeLimitMiddleware, scope: dict, receive) -> _RecordingSend:
    send = _RecordingSend()
    asyncio.run(middleware(scope, receive, send))
    return send


def test_a_real_body_within_the_limit_passes_through_unchanged():
    app = _RecordingApp()
    middleware = RequestSizeLimitMiddleware(app, max_body_bytes=100)
    receive = _make_receive([b'{"query": "small"}'])

    send = _run(middleware, _http_scope(), receive)

    assert app.was_called
    assert app.received_body == b'{"query": "small"}'
    assert send.status == 200


def test_a_declared_content_length_over_the_limit_is_rejected_without_reading_any_body():
    # The real, fast-path check -- a receive() that would raise if
    # ever actually called proves the middleware genuinely never reads
    # a single byte once the DECLARED size alone already exceeds the
    # limit.
    app = _RecordingApp()
    middleware = RequestSizeLimitMiddleware(app, max_body_bytes=100)

    async def receive_that_must_never_be_called():
        raise AssertionError("receive() should never be called once Content-Length alone already exceeds the limit")

    scope = _http_scope(headers=[(b"content-length", b"999999")])

    send = _run(middleware, scope, receive_that_must_never_be_called)

    assert not app.was_called
    assert send.status == 413
    assert json.loads(send.body) == {"detail": "Request body too large"}


def test_a_missing_content_length_does_not_bypass_the_limit():
    # THE real, critical case this middleware exists for -- confirmed
    # directly, not assumed, that a real client CAN omit or under-
    # report this header while still streaming a genuinely large
    # body. No content-length header at all here; the real, streamed
    # body is what must be caught.
    app = _RecordingApp()
    middleware = RequestSizeLimitMiddleware(app, max_body_bytes=10)
    receive = _make_receive([b"x" * 5, b"x" * 5, b"x" * 5])  # 15 real bytes, limit is 10

    send = _run(middleware, _http_scope(), receive)

    assert not app.was_called
    assert send.status == 413
    assert json.loads(send.body) == {"detail": "Request body too large"}


def test_a_lying_content_length_does_not_bypass_the_limit_either():
    # Same real case as above, but with an explicit header claiming a
    # SMALL, well-within-limit size while the real, streamed body is
    # actually much larger -- the fast-path check alone would have
    # been fooled; the real, byte-counted check is what actually
    # catches this.
    app = _RecordingApp()
    middleware = RequestSizeLimitMiddleware(app, max_body_bytes=10)
    receive = _make_receive([b"x" * 5, b"x" * 5, b"x" * 5])  # 15 real bytes
    scope = _http_scope(headers=[(b"content-length", b"1")])  # lies: claims 1 byte

    send = _run(middleware, scope, receive)

    assert not app.was_called
    assert send.status == 413


def test_a_body_exactly_at_the_limit_is_allowed_not_rejected():
    # A real, deliberate boundary check -- "over the limit" must mean
    # strictly over, not "at or over," otherwise the documented,
    # configured limit would silently be one byte smaller than stated.
    app = _RecordingApp()
    middleware = RequestSizeLimitMiddleware(app, max_body_bytes=10)
    receive = _make_receive([b"x" * 10])

    send = _run(middleware, _http_scope(), receive)

    assert app.was_called
    assert app.received_body == b"x" * 10
    assert send.status == 200


def test_non_http_scopes_are_never_touched():
    # A real websocket/lifespan scope must pass straight through,
    # completely unaffected -- this middleware's own real concern
    # (a request BODY) has no meaning for either.
    app = _RecordingApp()
    middleware = RequestSizeLimitMiddleware(app, max_body_bytes=1)

    async def receive():
        raise AssertionError("receive() should never be called for a non-http scope")

    _run(middleware, {"type": "lifespan"}, receive)

    assert app.was_called
