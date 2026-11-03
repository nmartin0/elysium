"""
Times each request and records it, for the RED metrics.

WHY MIDDLEWARE. A request-duration record is the one measurement that
yields Rate, Errors and Duration together -- "a single request-duration
histogram covers latency, traffic, and explicit errors" -- and the only
place that sees every request's start, end and status is here.

THE ROUTE TEMPLATE, NOT THE PATH. Starlette resolves the matched route
and puts it on the scope, so `/objects/{object_type}` is recorded
rather than `/objects/Customer`. A per-value row would make the table
unbounded in cardinality while answering no question anyone asks.

FAILURE HERE DOES NOT FAIL THE REQUEST. Losing a metric costs a
dashboard one point; failing the request costs the person their answer.
The same trade bronze makes, for the same reason.

WHAT THIS DOES NOT MEASURE is saturation -- the fourth golden signal --
because that is a property of the HOST, and answering it from inside
the process would mean guessing at limits we do not know.
"""

import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class RequestMetricsMiddleware:
    """Records one row per HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def _store(scope: Scope):
        """The metrics store, read at REQUEST time off app.state.

        NOT PASSED AT REGISTRATION, because middleware is registered
        before runtime_paths is resolved -- a store handed over then
        would be None forever, and a middleware that silently recorded
        nothing is worse than none: the dashboard would show an idle
        server.
        """
        app = scope.get("app")
        return getattr(getattr(app, "state", None), "request_metrics", None)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        metrics = self._store(scope) if scope["type"] == "http" else None
        if scope["type"] != "http" or metrics is None:
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status = {"code": 0}

        async def send_recording_status(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_recording_status)
        finally:
            # IN `finally`, so a request that raised is still recorded.
            # An exception is exactly the kind of slow, failing request
            # a dashboard exists to show, and recording only the happy
            # path would hide it.
            duration_ms = (time.perf_counter() - started) * 1000
            self._record(metrics, scope, status["code"], duration_ms)

    def _record(self, metrics, scope: Scope, status: int, duration_ms: float) -> None:
        try:
            route = scope.get("route")
            # THE TEMPLATE WHERE STARLETTE RESOLVED ONE, and the raw
            # path only when it did not -- a 404 has no matched route,
            # and recording it as its literal path is right there,
            # because what someone wants to know is which unmatched
            # path was asked for.
            label = getattr(route, "path", None) or scope.get("path", "unknown")
            metrics.record(
                label, scope.get("method", "?"), status, duration_ms,
            )
        except Exception as e:  # noqa: BLE001 - see the module docstring
            logger.warning(f"request metric not recorded ({e})")
