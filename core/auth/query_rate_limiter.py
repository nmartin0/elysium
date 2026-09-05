"""
query_rate_limiter.py  (rate-limit repeated /query calls, per
authenticated user)

A real, found gap this project shipped without: POST /query invokes a
real LLM on every call -- a genuinely more expensive operation than
almost anything else this app does, both in real compute and, for a
paid LLM backend, real money -- with no backend-enforced slowdown at
all. A single authenticated user (or a compromised session) could
script unlimited queries with no real cost to themselves. Closed here,
matching the SAME class/db_path/one-shared-instance, fixed-window
pattern login_attempt_tracker.py's own docstring already establishes
and explains in full -- this file only calls out what's genuinely
DIFFERENT about this specific case, not the shared reasoning.

Keyed by user_id, not username or IP -- this app is authenticated
throughout (there is no meaningful anonymous traffic to rate-limit at
all, unlike login_attempt_tracker.py's own pre-authentication case),
and a real user_id is a stable, correct identity to key by regardless
of which IP or device a person happens to be using; an IP-based limit
would be both too loose (multiple real users sharing one IP behind
NAT would throttle each other) and too permissive (one real user
switching networks would reset their own limit for free).

MAX_QUERIES_PER_WINDOW/WINDOW chosen as a reasonable, generous default
for genuine, interactive, human usage (asking a question, reading the
real answer, asking a follow-up) while still closing the real gap for
scripted/runaway abuse -- not tuned against this specific deployment's
own real traffic; revisit if real, observed usage patterns ever call
for something stricter or looser, same as login_attempt_tracker.py's
own MAX_ATTEMPTS/WINDOW.

Deliberately NOT shared infrastructure with login_attempt_tracker.py
itself, despite the identical shape -- these are two, genuinely
different real concerns (pre-auth brute-force lockout vs. authenticated
resource-cost protection), with their own, independent, real reasons to
change independently of each other later (this project's own
established "one clear reason to change" principle, not merged just
because the code happens to look similar today).

Used by: api/routes.py's own query() route, the only caller.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.auth.database import connection

MAX_QUERIES_PER_WINDOW = 20
WINDOW = timedelta(minutes=5)


class QueryRateLimiter:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def is_rate_limited(self, user_id: str) -> bool:
        with connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT query_count, window_started_at FROM query_rate_limits WHERE user_id = ?", (user_id,)
            ).fetchone()

        if row is None:
            return False

        window_started_at = datetime.fromisoformat(row["window_started_at"])
        if datetime.now(UTC) - window_started_at >= WINDOW:
            # The window itself has expired -- a stale record, not a
            # real, current limit. Left in place rather than deleted
            # here (a read-only method deleting rows would be a real,
            # surprising side effect); record_query() below is what
            # actually resets it, the next time this user queries at
            # all.
            return False

        return row["query_count"] >= MAX_QUERIES_PER_WINDOW

    def record_query(self, user_id: str) -> None:
        with connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT query_count, window_started_at FROM query_rate_limits WHERE user_id = ?", (user_id,)
            ).fetchone()

            now = datetime.now(UTC)
            if row is None or now - datetime.fromisoformat(row["window_started_at"]) >= WINDOW:
                # No record yet, or the previous window has fully
                # expired -- start a genuinely fresh one, not an
                # ever-growing count from a much earlier, unrelated
                # burst of queries.
                conn.execute(
                    """
                    INSERT INTO query_rate_limits (user_id, query_count, window_started_at)
                    VALUES (?, 1, ?)
                    ON CONFLICT(user_id) DO UPDATE SET query_count = 1, window_started_at = excluded.window_started_at
                    """,
                    (user_id, now.isoformat()),
                )
            else:
                conn.execute(
                    "UPDATE query_rate_limits SET query_count = query_count + 1 WHERE user_id = ?", (user_id,)
                )
            conn.commit()
