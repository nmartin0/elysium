"""Tests for the JSON API silo.

What is worth pinning here is not that it serves JSON, but the four
conditions a consumer of a real small-business API has to survive:
pagination, bearer auth, rate limiting, and the service going away.
"""

import json
import urllib.error
import urllib.request

import pytest
from simulator.ports import PortRegistry
from simulator.silo import SiloError
from simulator.silos.rest import (
    API_PREFIX,
    RETRY_AFTER_SECONDS,
    RestSilo,
    _decode_cursor,
    _encode_cursor,
)


@pytest.fixture
def silo(tmp_path):
    registry = PortRegistry.allocate(tmp_path, ["square"])
    made = RestSilo(name="square", data_dir=tmp_path / "square",
                    port=registry.port("square"), page_size=10)
    made.create()
    made.start()
    try:
        yield made
    finally:
        made.stop()


def fetch(silo, path, *, token="sim-token"):
    """One request, returning (status, body, headers)."""
    request = urllib.request.Request(f"{silo.base_url}{path}")
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read()), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read()), dict(error.headers)


def drain(silo, collection, *, token="sim-token"):
    """Follow the cursor to the end, the way a correct consumer must."""
    records, path = [], f"{API_PREFIX}/{collection}"
    while True:
        status, body, _ = fetch(silo, path, token=token)
        assert status == 200
        records.extend(body["data"])
        if "cursor" not in body:
            return records
        path = f"{API_PREFIX}/{collection}?cursor={body['cursor']}"


# -- pagination ------------------------------------------------------

def test_a_collection_arrives_in_pages(silo):
    silo.publish("payments", [{"id": f"p{index}"} for index in range(25)])
    status, body, _ = fetch(silo, f"{API_PREFIX}/payments")
    assert status == 200
    assert len(body["data"]) == 10
    assert "cursor" in body


def test_following_the_cursor_yields_every_record_exactly_once(silo):
    published = [{"id": f"p{index}"} for index in range(25)]
    silo.publish("payments", published)
    assert drain(silo, "payments") == published


def test_a_consumer_that_ignores_the_cursor_silently_loses_data(silo):
    # THE most common integration bug against APIs of this shape, and
    # the reason pagination is simulated rather than skipped. It is
    # silent: the data looks fine, there is just less of it.
    silo.publish("payments", [{"id": f"p{index}"} for index in range(25)])
    _, first_page, _ = fetch(silo, f"{API_PREFIX}/payments")
    assert len(first_page["data"]) == 10
    assert len(drain(silo, "payments")) == 25


def test_the_last_page_carries_no_cursor(silo):
    silo.publish("payments", [{"id": "p1"}])
    _, body, _ = fetch(silo, f"{API_PREFIX}/payments")
    assert body["data"] == [{"id": "p1"}]
    assert "cursor" not in body


def test_an_empty_collection_is_an_empty_page_not_an_error(silo):
    silo.publish("payments", [])
    status, body, _ = fetch(silo, f"{API_PREFIX}/payments")
    assert status == 200
    assert body == {"data": []}


def test_a_collection_exactly_one_page_long_ends_cleanly(silo):
    # The off-by-one that produces an endless final page.
    silo.publish("payments", [{"id": f"p{index}"} for index in range(10)])
    _, body, _ = fetch(silo, f"{API_PREFIX}/payments")
    assert len(body["data"]) == 10
    assert "cursor" not in body


def test_cursors_are_opaque(silo):
    silo.publish("payments", [{"id": f"p{index}"} for index in range(25)])
    _, body, _ = fetch(silo, f"{API_PREFIX}/payments")
    # Not a readable offset. A consumer that cracks one open and does
    # arithmetic on it is writing a bug this should not make easy.
    assert body["cursor"] != "10"
    assert not body["cursor"].isdigit()
    assert _decode_cursor(body["cursor"]) == 10


def test_a_malformed_cursor_is_rejected_rather_than_ignored(silo):
    silo.publish("payments", [{"id": "p1"}])
    status, body, _ = fetch(silo, f"{API_PREFIX}/payments?cursor=not-a-cursor")
    assert status == 400
    assert body["errors"][0]["code"] == "INVALID_CURSOR"


def test_cursor_round_trip():
    assert _decode_cursor(_encode_cursor(42)) == 42
    with pytest.raises(ValueError, match="malformed cursor"):
        _decode_cursor("!!!")


# -- authentication --------------------------------------------------

def test_a_missing_token_is_a_json_401_not_a_connection_failure(silo):
    # A different thing for a consumer to handle, and the thing that
    # really happens.
    status, body, _ = fetch(silo, f"{API_PREFIX}/payments", token=None)
    assert status == 401
    assert body["errors"][0]["code"] == "UNAUTHORIZED"


def test_a_wrong_token_is_also_401(silo):
    status, _, _ = fetch(silo, f"{API_PREFIX}/payments", token="wrong")
    assert status == 401


def test_authentication_can_be_turned_off(tmp_path):
    # Some small-business APIs really are open on a private network,
    # and a pack should be able to say so.
    registry = PortRegistry.allocate(tmp_path, ["open"])
    silo = RestSilo(name="open", data_dir=tmp_path / "open",
                    port=registry.port("open"), token=None)
    silo.create()
    silo.start()
    try:
        silo.publish("things", [{"id": "t1"}])
        status, body, _ = fetch(silo, f"{API_PREFIX}/things", token=None)
        assert status == 200
        assert body["data"] == [{"id": "t1"}]
        assert "token" not in silo.connection().details
    finally:
        silo.stop()


# -- rate limiting ---------------------------------------------------

def test_rate_limiting_returns_429_with_a_retry_after(tmp_path):
    registry = PortRegistry.allocate(tmp_path, ["limited"])
    silo = RestSilo(name="limited", data_dir=tmp_path / "limited",
                    port=registry.port("limited"), rate_limit=2, rate_window_seconds=None)
    silo.create()
    silo.start()
    try:
        silo.publish("payments", [{"id": "p1"}])
        assert fetch(silo, f"{API_PREFIX}/payments")[0] == 200
        assert fetch(silo, f"{API_PREFIX}/payments")[0] == 200
        status, body, headers = fetch(silo, f"{API_PREFIX}/payments")
        assert status == 429
        assert body["errors"][0]["code"] == "RATE_LIMITED"
        assert headers["Retry-After"] == str(RETRY_AFTER_SECONDS)

        silo.reset_rate_limit()
        assert fetch(silo, f"{API_PREFIX}/payments")[0] == 200
    finally:
        silo.stop()


def test_the_window_rolls_on_the_clock_and_says_how_long_is_left(tmp_path):
    """REAL_SOURCES.md R2: the window turned only when something called
    reset_rate_limit(), and nothing in a running world did -- so once on,
    the API refused for ever. Real APIs roll per minute (Xero: 60 calls a
    minute, 429 with Retry-After)."""
    registry = PortRegistry.allocate(tmp_path, ["limited"])
    silo = RestSilo(name="limited", data_dir=tmp_path / "limited",
                    port=registry.port("limited"), rate_limit=2)
    now = [1000.0]
    silo._clock = lambda: now[0]
    silo.reset_rate_limit()
    silo.create()
    silo.start()
    try:
        silo.publish("payments", [{"id": "p1"}])
        status, _, headers = fetch(silo, f"{API_PREFIX}/payments")
        assert status == 200 and headers["X-RateLimit-Remaining"] == "1"
        fetch(silo, f"{API_PREFIX}/payments")
        now[0] += 45
        status, _, headers = fetch(silo, f"{API_PREFIX}/payments")
        assert status == 429 and headers["Retry-After"] == "15"

        now[0] += 15                     # the minute is up
        assert fetch(silo, f"{API_PREFIX}/payments")[0] == 200
    finally:
        silo.stop()


def test_rate_limiting_is_off_by_default(silo):
    # On by default would make a consumer's first run fail for a reason
    # that has nothing to do with the data.
    silo.publish("payments", [{"id": "p1"}])
    for _ in range(50):
        assert fetch(silo, f"{API_PREFIX}/payments")[0] == 200


# -- unknown routes --------------------------------------------------

def test_an_unknown_collection_is_404(silo):
    status, body, _ = fetch(silo, f"{API_PREFIX}/nope")
    assert status == 404
    assert "nope" in body["errors"][0]["detail"]


def test_a_path_outside_the_api_prefix_is_404(silo):
    assert fetch(silo, "/admin")[0] == 404


# -- lifecycle -------------------------------------------------------

def test_it_needs_a_port(tmp_path):
    assert RestSilo.requires_port is True
    silo = RestSilo(name="square", data_dir=tmp_path, port=0)
    registry = PortRegistry.allocate_for(tmp_path, [silo])
    assert set(registry.ports) == {"square"}


def test_the_descriptor_carries_the_base_url_and_token(silo):
    descriptor = silo.connection()
    assert descriptor.kind == "rest"
    assert descriptor.details["base_url"] == silo.base_url
    assert descriptor.details["auth"] == "bearer"
    assert descriptor.details["token"] == "sim-token"


def test_starting_twice_is_quiet(silo):
    silo.start()
    assert silo.is_reachable()


def test_stopping_twice_is_quiet(silo):
    silo.stop()
    silo.stop()
    assert silo.is_reachable() is False


def test_a_taken_port_fails_loudly(tmp_path):
    registry = PortRegistry.allocate(tmp_path, ["a"])
    first = RestSilo(name="a", data_dir=tmp_path / "a", port=registry.port("a"))
    first.create()
    first.start()
    second = RestSilo(name="b", data_dir=tmp_path / "b", port=registry.port("a"))
    second.create()
    try:
        with pytest.raises(SiloError, match="cannot listen"):
            second.start()
    finally:
        first.stop()


# -- reachability and outage -----------------------------------------

def test_a_401_still_counts_as_reachable(tmp_path):
    # The service is up and refusing this request, which is a different
    # condition from the service being down. Conflating them is how a
    # health check reports an outage during a rate-limit window.
    registry = PortRegistry.allocate(tmp_path, ["auth"])
    silo = RestSilo(name="auth", data_dir=tmp_path / "auth",
                    port=registry.port("auth"), token="secret")
    silo.create()
    silo.start()
    try:
        assert fetch(silo, f"{API_PREFIX}/", token=None)[0] == 401
        assert silo.is_reachable() is True
    finally:
        silo.stop()


def test_a_rate_limited_silo_is_still_reachable(tmp_path):
    registry = PortRegistry.allocate(tmp_path, ["limited"])
    silo = RestSilo(name="limited", data_dir=tmp_path / "limited",
                    port=registry.port("limited"), rate_limit=0)
    silo.create()
    silo.start()
    try:
        assert fetch(silo, f"{API_PREFIX}/anything")[0] == 429
        assert silo.is_reachable() is True
    finally:
        silo.stop()


def test_terminate_makes_the_api_stop_answering(silo):
    silo.publish("payments", [{"id": "p1"}])
    assert silo.is_reachable()
    silo.terminate()
    assert silo.is_reachable() is False


def test_stopping_after_a_terminate_is_quiet(silo):
    silo.terminate()
    silo.stop()
    assert silo.is_reachable() is False


# -- publishing ------------------------------------------------------

def test_publish_replaces_and_append_adds(silo):
    silo.publish("payments", [{"id": "p1"}])
    silo.append("payments", {"id": "p2"})
    assert drain(silo, "payments") == [{"id": "p1"}, {"id": "p2"}]
    silo.publish("payments", [{"id": "p9"}])
    assert drain(silo, "payments") == [{"id": "p9"}]


def test_published_records_are_copied_not_referenced(silo):
    # A pack holding its own dict must not be able to change what the
    # API already served by mutating it afterwards.
    record = {"id": "p1", "amount": 100}
    silo.publish("payments", [record])
    record["amount"] = 999
    assert drain(silo, "payments") == [{"id": "p1", "amount": 100}]


def test_append_creates_a_collection(silo):
    silo.append("refunds", {"id": "r1"})
    assert drain(silo, "refunds") == [{"id": "r1"}]


def test_timestamps_are_served_as_iso_strings(silo):
    # These APIs emit ISO 8601 with an offset, not epoch integers, and
    # parsing them is a real source of off-by-one-day errors.
    silo.publish("payments", [{"id": "p1", "created_at": "2026-03-02T10:15:00+00:00"}])
    record = drain(silo, "payments")[0]
    assert record["created_at"] == "2026-03-02T10:15:00+00:00"


# -- registration ----------------------------------------------------

def test_it_is_registered_as_a_kind():
    from simulator.silos import SILO_TYPES

    assert SILO_TYPES["rest"] is RestSilo


# -- realism options (REAL_SOURCES.md R1, R3, R7) ----------------------

@pytest.fixture
def make(tmp_path):
    """A silo with options, started, and stopped afterwards."""
    made = []

    def build(**options):
        name = f"api{len(made)}"
        registry = PortRegistry.allocate(tmp_path / name, [name])
        silo = RestSilo(name=name, data_dir=tmp_path / name, port=registry.port(name),
                        page_size=10, **options)
        silo.create()
        silo.start()
        made.append(silo)
        return silo

    yield build
    for silo in made:
        silo.stop()


def _token_request(silo, *, basic=True, secret="sim-token", grant="client_credentials"):
    import base64

    form = f"grant_type={grant}"
    request = urllib.request.Request(f"{silo.base_url}/oauth/token", method="POST")
    if basic:
        pair = base64.b64encode(f"{silo.client_id}:{secret}".encode()).decode()
        request.add_header("Authorization", f"Basic {pair}")
    else:
        form += f"&client_id={silo.client_id}&client_secret={secret}"
    request.data = form.encode()
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_options_are_off_by_default(silo):
    assert (silo.token_lifetime_seconds, silo.fault_rate, silo.latency_ms,
            silo.modified_since_field) == (None, 0.0, 0.0, None)
    silo.publish("p", [{"id": "1"}])
    assert all(fetch(silo, f"{API_PREFIX}/p")[0] == 200 for _ in range(50))


def test_every_request_can_fail_with_a_server_error(make):
    silo = make(fault_rate=1.0, fault_statuses=[502])
    silo.publish("p", [{"id": "1"}])

    status, body, _ = fetch(silo, f"{API_PREFIX}/p")

    assert status == 502 and body["errors"][0]["code"] == "SERVER_ERROR"


def test_a_share_of_requests_fail_and_the_rest_answer(make):
    silo = make(fault_rate=0.2)
    silo.publish("p", [{"id": "1"}])

    statuses = [fetch(silo, f"{API_PREFIX}/p")[0] for _ in range(300)]

    failed = [status for status in statuses if status != 200]
    # 300 draws at 0.2: a band about four standard deviations wide.
    assert 33 <= len(failed) <= 87, len(failed)
    assert set(failed) <= {500, 502, 503, 504} and len(set(failed)) > 1


def test_replies_are_delayed_by_latency_plus_or_minus_jitter(make):
    silo = make(latency_ms=200, latency_jitter_ms=50)
    waited = []
    silo._sleep = waited.append
    silo.publish("p", [{"id": "1"}])

    for _ in range(40):
        fetch(silo, f"{API_PREFIX}/p")

    assert len(waited) == 40
    assert all(0.150 <= seconds <= 0.250 for seconds in waited)
    assert max(waited) - min(waited) > 0.05, "jitter varies the delay"


def test_an_expiring_token_is_given_by_the_token_endpoint_not_the_descriptor(make):
    silo = make(token_lifetime_seconds=1800)

    details = silo.connection().details

    assert details["auth"] == "oauth_client_credentials"
    assert details["token_url"] == f"{silo.base_url}/oauth/token"
    assert "token" not in details
    assert fetch(silo, f"{API_PREFIX}/p", token="sim-token")[0] == 401


@pytest.mark.parametrize("basic", [True, False], ids=["basic", "form"])
def test_a_token_works_until_it_expires_and_then_says_so(make, basic):
    now = [0.0]
    silo = make(token_lifetime_seconds=1800)
    silo._clock = lambda: now[0]
    silo.publish("p", [{"id": "1"}])

    status, issued = _token_request(silo, basic=basic)
    assert status == 200 and issued["token_type"] == "Bearer" and issued["expires_in"] == 1800
    assert fetch(silo, f"{API_PREFIX}/p", token=issued["access_token"])[0] == 200

    now[0] = 1800.0
    status, body, headers = fetch(silo, f"{API_PREFIX}/p", token=issued["access_token"])

    assert status == 401 and body["errors"][0]["detail"] == "The access token expired"
    assert 'error="invalid_token"' in headers["WWW-Authenticate"]


def test_the_token_endpoint_refuses_a_wrong_secret_and_a_wrong_grant(make):
    silo = make(token_lifetime_seconds=60)

    assert _token_request(silo, secret="guess") == (401, {"error": "invalid_client"})
    assert _token_request(silo, grant="password") == (400, {"error": "unsupported_grant_type"})


def test_if_modified_since_returns_only_what_changed(make):
    silo = make(modified_since_field="updated_at")
    silo.publish("p", [{"id": "a", "updated_at": "2026-10-01T09:00:00+00:00"},
                       {"id": "b", "updated_at": "2026-10-05T09:00:00+00:00"},
                       {"id": "c", "updated_at": None}])

    def since(value):
        request = urllib.request.Request(f"{silo.base_url}{API_PREFIX}/p",
                                         headers={"Authorization": "Bearer sim-token",
                                                  "If-Modified-Since": value})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, [r["id"] for r in json.loads(response.read())["data"]]
        except urllib.error.HTTPError as error:
            return error.code, None

    assert since("2026-10-03T00:00:00") == (200, ["b"])
    assert since("Thu, 01 Oct 2026 09:00:00 GMT") == (200, ["a", "b"])
    assert since("last tuesday")[0] == 400


def test_if_modified_since_is_ignored_unless_switched_on(silo):
    silo.publish("p", [{"id": "a", "updated_at": "2020-01-01T00:00:00+00:00"}])
    request = urllib.request.Request(f"{silo.base_url}{API_PREFIX}/p",
                                     headers={"Authorization": "Bearer sim-token",
                                              "If-Modified-Since": "2026-01-01T00:00:00"})
    with urllib.request.urlopen(request, timeout=5) as response:
        assert len(json.loads(response.read())["data"]) == 1


@pytest.mark.parametrize("options", [
    {"fault_rate": 1.5}, {"fault_statuses": [404]}, {"latency_ms": 10, "latency_jitter_ms": 20},
    {"token_lifetime_seconds": 0}, {"token_lifetime_seconds": 60, "token": None},
    {"fault_statuses": []},
], ids=["rate", "status", "jitter", "lifetime", "no-secret", "no-statuses"])
def test_nonsense_options_are_refused(tmp_path, options):
    with pytest.raises(SiloError):
        RestSilo(name="x", data_dir=tmp_path, port=1, **options)


def test_a_record_whose_time_cannot_be_read_is_served_not_blamed_on_the_caller(make):
    silo = make(modified_since_field="updated_at")
    silo.publish("p", [{"id": "a", "updated_at": "20/10/2026"},
                       {"id": "b", "updated_at": "2020-01-01T00:00:00+00:00"}])
    request = urllib.request.Request(f"{silo.base_url}{API_PREFIX}/p",
                                     headers={"Authorization": "Bearer sim-token",
                                              "If-Modified-Since": "2026-01-01T00:00:00"})

    with urllib.request.urlopen(request, timeout=5) as response:
        assert [r["id"] for r in json.loads(response.read())["data"]] == ["a"]


def test_a_slow_api_is_slow_not_down(make):
    silo = make(latency_ms=2500)

    assert silo.is_reachable()
