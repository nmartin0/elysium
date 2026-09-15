"""
request_metrics.py  (what the server did, and how long it took)

WHY THESE FOUR NUMBERS AND NOT OTHERS. The RED method -- Rate, Errors,
Duration -- is the canonical starting point for a request-driven
service, and it is "usually the practical starting point" precisely
because a single request-duration record yields all three. Rate is how
many rows fell in a window; duration is their distribution; errors are
the share whose status said so.

RED RATHER THAN THE FULL FOUR GOLDEN SIGNALS, deliberately. The fourth,
saturation, is a property of the HOST -- CPU, memory, queue depth --
and answering it from inside the process would mean guessing at limits
we do not know. It belongs to whatever watches the machine. Recorded as
a gap rather than approximated.

PERSISTED, NOT COUNTED IN MEMORY. In-memory counters reset on every
restart, and uvicorn --reload restarts on any file change: a p99 that
resets when someone saves a file describes nothing. Measured before
choosing: one committed row costs 0.105 ms against a query path of
several hundred, and ten thousand rows are 192 KB.

COMMITTED PER REQUEST, NOT BATCHED. Batching is 100x cheaper again --
0.0009 ms -- and loses whatever is buffered when the process dies. The
requests most worth having are the ones immediately before a crash.

ERRORS AS A RATIO, NOT A COUNT, when read back: "express errors as a
ratio, not a raw count", because ten failures means nothing without
knowing whether there were twelve requests or twelve thousand.

AND LATENCY EXCLUDES FAILURES, which is the subtle one: "a fast error
is still an error, and if you fold failed requests into your latency
numbers, a flood of instant 500s will make your dashboard look
healthier than it is".
"""

import time
from pathlib import Path
from typing import Any

from core.sqlite_connection import connection_with_schema

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    at REAL NOT NULL,
    route TEXT NOT NULL,
    method TEXT NOT NULL,
    status INTEGER NOT NULL,
    duration_ms REAL NOT NULL
);
-- Every read is "what happened recently", so time is the only index
-- worth carrying. One more would cost a write per request to answer a
-- question nobody has asked.
CREATE INDEX IF NOT EXISTS requests_at ON requests (at);
"""


class RequestMetrics:
    """Records one row per request, and answers RED over a window."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def record(self, route: str, method: str, status: int, duration_ms: float) -> None:
        """One request, as it completed.

        THE ROUTE TEMPLATE, NOT THE PATH. `/objects/{object_type}` and
        not `/objects/Customer` -- a per-object-id row would make the
        table unbounded in cardinality and answer no question, since
        nobody asks how slow one customer was.
        """
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO requests (at, route, method, status, duration_ms) "
                "VALUES (?, ?, ?, ?, ?)",
                (time.time(), route, method, status, duration_ms),
            )
            conn.commit()

    def summary(self, window_seconds: int = 3600) -> dict[str, Any]:
        """Rate, errors and duration over the last window.

        LATENCY FROM SUCCESSES ONLY. A flood of instant 500s would
        otherwise drag the average down and make a failing server look
        fast -- the dashboard equivalent of good news.

        A WINDOW WITH NO REQUESTS RETURNS ZEROS AND NULLS, not an
        absence. "No requests in the last hour" is a real and
        interesting answer; a missing key is one a caller has to guess
        at.
        """
        since = time.time() - window_seconds
        with self._connection() as conn:
            total, errors = conn.execute(
                "SELECT count(*), coalesce(sum(status >= 400), 0) "
                "FROM requests WHERE at >= ?",
                (since,),
            ).fetchone()

            durations = [
                row[0] for row in conn.execute(
                    "SELECT duration_ms FROM requests "
                    "WHERE at >= ? AND status < 400 ORDER BY duration_ms",
                    (since,),
                )
            ]

        return {
            "window_seconds": window_seconds,
            "requests": total,
            # PER SECOND, because a raw count over an arbitrary window
            # cannot be compared with anything.
            "rate_per_second": round(total / window_seconds, 4) if window_seconds else 0.0,
            # A RATIO, not a count.
            "error_ratio": round(errors / total, 4) if total else 0.0,
            "p50_ms": _percentile(durations, 0.50),
            "p99_ms": _percentile(durations, 0.99),
        }

    def slowest_routes(self, window_seconds: int = 3600, limit: int = 5) -> list[dict]:
        """Which routes are worst, by p99 rather than by mean.

        BY p99 BECAUSE A MEAN HIDES THE THING YOU ARE LOOKING FOR. A
        route that is fast a thousand times and catastrophic twice has
        a healthy mean and an unhealthy tail, and it is the tail people
        actually experience.
        """
        since = time.time() - window_seconds
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT route, duration_ms FROM requests "
                "WHERE at >= ? AND status < 400",
                (since,),
            ).fetchall()

        by_route: dict[str, list[float]] = {}
        for route, duration in rows:
            by_route.setdefault(route, []).append(duration)

        summaries = [
            {
                "route": route,
                "requests": len(durations),
                "p99_ms": _percentile(sorted(durations), 0.99),
            }
            for route, durations in by_route.items()
        ]
        summaries.sort(key=lambda entry: entry["p99_ms"] or 0, reverse=True)
        return summaries[:limit]

    def forget_older_than(self, seconds: int) -> int:
        """Drops rows beyond the retention window, returning how many.

        SAFE TO DELETE, unlike the changelog. Metrics describe what the
        server did, not what the data was -- nothing references them,
        and losing an old row costs a graph its left-hand edge rather
        than a record its history.
        """
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM requests WHERE at < ?", (time.time() - seconds,))
            conn.commit()
            return cursor.rowcount


def _percentile(sorted_values: list[float], fraction: float) -> "float | None":
    """None rather than zero when there is nothing to measure.

    Zero would read as "instantaneous", which is the opposite of "we do
    not know" and much more alarming to be wrong about.
    """
    if not sorted_values:
        return None
    index = min(int(len(sorted_values) * fraction), len(sorted_values) - 1)
    return round(sorted_values[index], 2)
