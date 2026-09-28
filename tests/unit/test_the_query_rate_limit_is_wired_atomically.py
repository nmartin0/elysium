"""
The query route uses the atomic rate-limit call (001's F-05).

THE SECURITY AGENT FIXED THIS AND COULD NOT LAND IT. They wrote
`try_record_query`, which checks and increments in ONE transaction,
covered it with seventeen tests, and then could not change the one
line that calls it -- `api/routes.py` is shared and not theirs to
edit. Their handover puts it first: "Three completed, tested fixes are
inert."

SO THE LIMITER WAS CORRECT AND THE PRODUCT WAS NOT. The route did:

    if query_rate_limiter.is_rate_limited(user_id):   # transaction 1
        raise HTTPException(429, ...)
    query_rate_limiter.record_query(user_id)          # transaction 2

Another caller checks between those two lines, sees the same count,
and is let through. Neither method is wrong; the SEQUENCE is. They
measured it: with the count at 19 of 20, two callers were both
admitted.

THIS IS THE THIRD TIME THIS WEEK a tested mechanism turned out to be
wired to nothing -- `RetryingLLMAdapter` built and never constructed
(AL-R1), a record nothing reads (NEW-7), a test nothing runs
(COORD-3). Each was green. None was doing anything.

WHAT THIS TEST IS, honestly: a WIRING check, not a behavioural one. It
reads the route's source. That is weaker than exercising two
concurrent requests through the API, and it is exactly the check that
was missing -- seventeen tests of the limiter could not tell anybody
that the route ignored it.
"""

from pathlib import Path

ROUTES = Path("api/routes.py").read_text()


class TestTheRouteCallsTheAtomicMethod:
    def test_it_uses_try_record_query(self):
        assert "try_record_query" in ROUTES

    def test_it_no_longer_checks_and_records_separately(self):
        """THE REGRESSION TEST. Either call reappearing in this file
        means the sequence is back, whatever the limiter can do."""
        assert "is_rate_limited(" not in ROUTES
        assert "record_query(" not in ROUTES.replace("try_record_query(", "")

    def test_a_refusal_is_still_a_429(self):
        """Atomicity must not have cost the status code somebody's
        client depends on."""
        window = ROUTES[ROUTES.index("try_record_query"):]
        assert "429" in window[:400]

    def test_the_refusal_still_says_what_to_do(self):
        window = ROUTES[ROUTES.index("try_record_query"):]
        assert "please wait" in window[:600]


class TestTheLimiterStillOffersBoth:
    """`is_rate_limited` and `record_query` are not deleted -- they
    are the honest pieces the atomic call is built from, and other
    callers may read one without writing. The defect was combining
    them across two transactions IN A ROUTE, not their existence."""

    def test_the_atomic_method_exists(self):
        from core.auth.query_rate_limiter import QueryRateLimiter

        assert hasattr(QueryRateLimiter, "try_record_query")

    def test_and_so_do_the_parts(self):
        from core.auth.query_rate_limiter import QueryRateLimiter

        assert hasattr(QueryRateLimiter, "is_rate_limited")
        assert hasattr(QueryRateLimiter, "record_query")
