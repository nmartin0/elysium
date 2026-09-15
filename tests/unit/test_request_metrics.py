"""
Rate, errors and duration -- the RED method.

WHY THESE THREE. RED is the canonical starting point for a
request-driven service precisely because a single request-duration
record yields all of them: rate is how many rows fell in a window,
duration is their distribution, errors are the share whose status said
so.

SATURATION IS ABSENT ON PURPOSE. It is the fourth golden signal and a
property of the HOST -- CPU, memory, queue depth -- so answering it
from inside the process would mean guessing at limits we do not know.
A made-up number is worse than an admitted gap.

PERSISTED, NOT COUNTED IN MEMORY. In-memory counters reset on every
restart, and uvicorn --reload restarts on any file change: a p99 that
resets when someone saves a file describes nothing. Measured before
choosing -- one committed row costs 0.105 ms against a query path of
several hundred, and ten thousand rows are 192 KB.
"""

import time

import pytest

from core.request_metrics import RequestMetrics


@pytest.fixture
def metrics(tmp_path):
    return RequestMetrics(tmp_path / "metrics.db")


class TestRate:
    def test_it_counts_what_happened(self, metrics):
        for _ in range(3):
            metrics.record("/api/query", "POST", 200, 10.0)

        assert metrics.summary()["requests"] == 3

    def test_rate_is_per_second_not_a_raw_count(self, metrics):
        # A raw count over an arbitrary window cannot be compared with
        # anything, including itself over a different window.
        for _ in range(60):
            metrics.record("/api/query", "POST", 200, 10.0)

        assert metrics.summary(window_seconds=60)["rate_per_second"] == 1.0

    def test_older_requests_fall_out_of_the_window(self, metrics):
        with metrics._connection() as conn:
            conn.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
                (time.time() - 7200, "/api/query", "POST", 200, 10.0),
            )
            conn.commit()
        metrics.record("/api/query", "POST", 200, 10.0)

        assert metrics.summary(window_seconds=3600)["requests"] == 1


class TestErrors:
    def test_errors_are_a_ratio_not_a_count(self, metrics):
        """"Express errors as a ratio, not a raw count."

        Ten failures means nothing without knowing whether there were
        twelve requests or twelve thousand.
        """
        for _ in range(9):
            metrics.record("/api/query", "POST", 200, 10.0)
        metrics.record("/api/query", "POST", 500, 10.0)

        assert metrics.summary()["error_ratio"] == 0.1

    def test_client_errors_count_as_errors(self, metrics):
        # A 400 is a failed request from the caller's point of view,
        # and a dashboard counting only 5xx would show a healthy server
        # to a user who cannot get an answer.
        metrics.record("/api/query", "POST", 400, 10.0)

        assert metrics.summary()["error_ratio"] == 1.0

    def test_no_requests_gives_zero_rather_than_a_missing_key(self, metrics):
        # "No requests in the last hour" is a real and interesting
        # answer; a missing key is one a caller has to guess at.
        summary = metrics.summary()

        assert summary["requests"] == 0
        assert summary["error_ratio"] == 0.0


class TestDuration:
    def test_percentiles_describe_the_distribution(self, metrics):
        for ms in range(1, 101):
            metrics.record("/api/query", "POST", 200, float(ms))

        summary = metrics.summary()
        assert summary["p50_ms"] < summary["p99_ms"]

    def test_latency_excludes_failures(self, metrics):
        """THE SUBTLE ONE, and the reason it is tested.

        "A fast error is still an error, and if you fold failed
        requests into your latency numbers, a flood of instant 500s
        will make your dashboard look healthier than it is."
        """
        for _ in range(99):
            metrics.record("/api/query", "POST", 500, 0.1)
        metrics.record("/api/query", "POST", 200, 900.0)

        summary = metrics.summary()
        assert summary["p50_ms"] == 900.0, "the one success is the whole latency picture"
        assert summary["error_ratio"] == 0.99

    def test_a_percentile_over_nothing_is_none_not_zero(self, metrics):
        # Zero would read as "instantaneous", which is the opposite of
        # "we do not know" and much more alarming to be wrong about.
        metrics.record("/api/query", "POST", 500, 5.0)

        assert metrics.summary()["p50_ms"] is None


class TestSlowestRoutes:
    def test_it_ranks_by_the_tail_not_the_mean(self, metrics):
        """A mean hides the thing you are looking for.

        A route fast a thousand times and catastrophic twice has a
        healthy mean and an unhealthy tail, and the tail is what people
        actually experience.
        """
        # CHOSEN SO THE TWO MEASURES DISAGREE, which a first version
        # did not: it had the spiky route winning on mean as well, so
        # ranking by mean passed the test and a control could not fire.
        #
        #   /api/steady : 200 requests at 100ms -> mean 100, p99 100
        #   /api/spiky  : 95 at 1ms + 5 at 500ms -> mean 26, p99 500
        #
        # FIVE OUTLIERS IN A HUNDRED, not one in a thousand. A first
        # version used the latter and failed at baseline, which was the
        # TEST being wrong rather than the code: one value in a
        # thousand is the 99.9th percentile, and p99 correctly ignored
        # it. A p99 that moved for a one-in-a-thousand event would not
        # be a p99.
        for _ in range(200):
            metrics.record("/api/steady", "GET", 200, 100.0)
        for _ in range(95):
            metrics.record("/api/spiky", "GET", 200, 1.0)
        for _ in range(5):
            metrics.record("/api/spiky", "GET", 200, 500.0)

        worst = metrics.slowest_routes()[0]
        assert worst["route"] == "/api/spiky"

    def test_it_reports_how_many_requests_each_summarises(self, metrics):
        # A p99 over three requests is not a p99, and a reader needs to
        # know that before acting on it.
        metrics.record("/api/query", "POST", 200, 10.0)

        assert metrics.slowest_routes()[0]["requests"] == 1


class TestRetention:
    def test_old_rows_can_be_dropped(self, metrics):
        """SAFE TO DELETE, unlike the changelog.

        Metrics describe what the server DID, not what the data was.
        Nothing references them, so losing an old row costs a graph its
        left-hand edge rather than a record its history.
        """
        with metrics._connection() as conn:
            conn.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
                (time.time() - 100000, "/api/query", "POST", 200, 10.0),
            )
            conn.commit()
        metrics.record("/api/query", "POST", 200, 10.0)

        dropped = metrics.forget_older_than(3600)

        assert dropped == 1
        assert metrics.summary()["requests"] == 1


class TestTheRetentionWindow:
    """Thirty days, and why deleting is safe here.

    Metrics describe what the server DID, not what the data WAS.
    Nothing references them, so losing an old row costs a graph its
    left-hand edge rather than a record its history -- exactly the
    distinction that made the changelog need durable storage first and
    lets this expire freely.
    """

    def test_the_window_is_long_enough_to_answer_recent_questions(self):
        from core.request_metrics import RETENTION_SECONDS

        # The questions this table answers are all recent: "is it slow
        # now", "did the reload make it worse", "what changed this
        # week". A window under a week could not answer the third.
        assert RETENTION_SECONDS >= 7 * 24 * 60 * 60

    def test_a_sweep_keeps_what_is_inside_the_window(self, metrics):
        # THE CONTROL. A sweep that dropped everything would make the
        # dashboard permanently empty, which looks exactly like an idle
        # server.
        from core.request_metrics import RETENTION_SECONDS

        metrics.record("/api/query", "POST", 200, 10.0)

        metrics.forget_older_than(RETENTION_SECONDS)

        assert metrics.summary()["requests"] == 1
