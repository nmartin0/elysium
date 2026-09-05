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

Two real, separate classes -- QueryRateLimitReader(InternalReadAdapter)
and QueryRateLimitWriter(InternalWriteAdapter) -- not one, combined
class, matching the real, direct request worked through in core/
internal_storage.py's own module docstring: "we need a Python abstract
class or parent class that defines external reads, external writes,
internal reads, and internal writes." QueryRateLimiter is the FIRST
real internal store to actually extend that hierarchy, not just declare
it -- see core/internal_storage.py's own docstring for the fuller
design reasoning (CQRS, Python's own typeshed precedent) already
settled before this file was rewritten.

QueryRateLimitReader's own is_rate_limited() now runs through a REAL,
structurally read-only connection (InternalReadAdapter's own
_connection(), using core/sqlite_connection.py's own
open_connection(read_only=True) -- confirmed directly, empirically,
before relying on it: a real, isolated test proved SELECT succeeds
while INSERT/UPDATE/DROP are all genuinely denied at the SQLite engine
level itself). A REAL, LOAD-BEARING CONSEQUENCE of this, confirmed
directly while building this: a read-only connection can never run
CREATE TABLE either (a write-type operation the authorizer denies same
as any other), so the query_rate_limits table's own schema must
already exist by the time a Reader is ever constructed -- it can never
create it lazily itself the way core/auth/database.py's own
connection() helper does for a write-capable caller. See api/app.py's
own explicit, real schema-creation step, run once at real app startup,
before either half of this (or any other internal store) is
constructed.

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

from core.auth.database import connection
from core.internal_storage import InternalReadAdapter, InternalWriteAdapter

MAX_QUERIES_PER_WINDOW = 20
WINDOW = timedelta(minutes=5)


class QueryRateLimitReader(InternalReadAdapter):
    def is_rate_limited(self, user_id: str) -> bool:
        with self._connection() as conn:
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
            # surprising side effect, and this is now a STRUCTURALLY
            # read-only connection besides -- it couldn't delete even
            # if it tried); record_query() below is what actually
            # resets it, the next time this user queries at all.
            return False

        return row["query_count"] >= MAX_QUERIES_PER_WINDOW


class QueryRateLimitWriter(InternalWriteAdapter):
    def record_query(self, user_id: str) -> None:
        # NOT self._connection() here -- deliberately still uses
        # core.auth.database's own schema-aware connection(), not
        # InternalWriteAdapter's own plain open_connection(). A real,
        # necessary correction, not an oversight: this table's own
        # schema needs to genuinely exist before any write to it
        # succeeds, and connection()'s own lazy, idempotent CREATE
        # TABLE IF NOT EXISTS is exactly the mechanism that already,
        # correctly guarantees that -- the same real mechanism this
        # method always used, before this file's own Reader/Writer
        # split. InternalWriteAdapter's own, simpler _connection() is
        # reserved for a table whose schema is ALREADY guaranteed to
        # exist by some other, earlier step (see api/app.py's own
        # explicit startup schema-creation step, added specifically so
        # THIS reasoning doesn't quietly become the only thing keeping
        # every internal store's own schema alive).
        with connection(self.db_path) as conn:
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
