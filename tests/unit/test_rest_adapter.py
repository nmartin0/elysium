"""A REST/JSON API as a source (19 October).

adapters/rest_adapter.py has the precedent behind each rule. Tested two
ways: against the SIMULATOR'S OWN API server -- the bearer token, the
opaque cursor, its 429 with Retry-After, money as strings -- and against
a small stand-in for the paging styles and failures it does not simulate
(a Link header, page numbers, offsets, a next URL, 5xx, an HTTP-date
Retry-After, an API that repeats its page token).
"""

import json
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

import adapters.rest_adapter as rest
from adapters.rest_adapter import ApiRefused, RestAdapter, retry_after_seconds
from core.ontology.interface import StorageUnavailable

CONFIG = {"storage": {"table": "invoices", "id_column": "id"}}


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    waits = []
    monkeypatch.setattr(rest, "_sleep", waits.append)
    return waits


# ---- the simulator's API --------------------------------------------------

@pytest.fixture
def sim_api(tmp_path):
    from simulator.ports import PortRegistry
    from simulator.silos.rest import RestSilo

    port = PortRegistry.allocate(tmp_path, ["books"]).port("books")
    silo = RestSilo(name="books", data_dir=tmp_path / "books", port=port, page_size=10)
    silo.create()
    silo.start()
    silo.publish("invoices", [{"id": f"inv_{i:03}", "total": f"{i}.50", "paid": i % 2 == 0,
                               "issued_at": f"2026-01-{1 + i % 28:02}T09:00:00+00:00"}
                              for i in range(37)])
    try:
        yield silo
    finally:
        silo.stop()


def _sim_adapter(silo, **extra):
    return RestAdapter({"base_url": f"{silo.base_url}/v1",
                        "auth": {"type": "bearer", "token": "sim-token"},
                        "tables": {"invoices": {"path": "/invoices", "records": "data",
                                                "pagination": {"type": "cursor", "cursor_field": "cursor",
                                                               "cursor_param": "cursor"}}},
                        **extra})


class TestTheSimulatorsApi:
    def test_every_page_is_read_once(self, sim_api):
        rows = _sim_adapter(sim_api).read_all_rows("invoices", ["id", "total"], CONFIG)

        assert len(rows) == 37 and len({r["id"] for r in rows}) == 37

    def test_values_as_it_sends_them(self, sim_api):
        rows = _sim_adapter(sim_api).read_all_rows("invoices", ["id", "total", "paid", "issued_at"], CONFIG)
        first = next(r for r in rows if r["id"] == "inv_003")

        assert first == {"id": "inv_003", "total": "3.50", "paid": False,
                         "issued_at": "2026-01-04T09:00:00+00:00"}

    def test_a_wrong_token_stops_at_once_and_says_why(self, sim_api, no_waiting):
        adapter = RestAdapter({"base_url": f"{sim_api.base_url}/v1",
                               "auth": {"type": "bearer", "token": "wrong"},
                               "tables": {"invoices": {"path": "/invoices"}}})

        with pytest.raises(ApiRefused, match="HTTP 401 -- the API refused the credentials"):
            adapter.read_all_rows("invoices", ["id"], CONFIG)
        assert no_waiting == [], "a refused credential is not retried"

    def test_its_rate_limit_is_waited_out_as_it_says(self, sim_api, no_waiting):
        # The simulator's window rolls on its own clock now and Retry-After
        # says how long is left in it (sim REAL_SOURCES.md R2). Its clock is
        # driven by the adapter's waiting, so the test is the adapter doing
        # exactly what it was told: wait 2 s, and the window has rolled.
        now = [0.0]
        sim_api._clock = lambda: now[0]
        sim_api.rate_window_seconds = 2.0
        sim_api.reset_rate_limit()
        sim_api.rate_limit = 2
        adapter = _sim_adapter(sim_api, max_retries=1)
        rest._sleep = lambda s: (no_waiting.append(s), now.__setitem__(0, now[0] + s))

        rows = adapter.read_all_rows("invoices", ["id"], CONFIG)

        assert len(rows) == 37 and no_waiting[0] == 2.0, "Retry-After: 2, not the default 1"

    def test_columns_are_the_keys_the_records_carry(self, sim_api):
        assert _sim_adapter(sim_api).columns_present("invoices") == {"id", "total", "paid", "issued_at"}

    def test_health_is_the_first_page_answering(self, sim_api):
        _sim_adapter(sim_api).health_check()


# ---- a stand-in for what the simulator does not do ------------------------

class _Api:
    """Serves RECORDS under whatever paging a test sets; can fail first."""

    def __init__(self):
        self.records = [{"id": f"r{i}", "amount": i + 0.1} for i in range(23)]
        self.failures: list[tuple[int, dict]] = []
        self.calls = 0
        self.mode = "link_header"
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                api.calls += 1
                if api.failures:
                    status, headers = api.failures.pop(0)
                    self.send_response(status)
                    for k, v in headers.items():
                        self.send_header(k, v)
                    self.end_headers()
                    self.wfile.write(b'{"error": "nope"}')
                    return
                query = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                body, headers = api.page(query)
                payload = json.dumps(body).encode()
                self.send_response(200)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def page(self, q):
        size = 5
        if self.mode == "link_header":
            start = int(q.get("from", 0))
            chunk = self.records[start:start + size]
            nxt = start + size
            link = {"Link": f'</items?from={nxt}>; rel="next"'} if nxt < len(self.records) else {}
            return {"items": chunk}, link
        if self.mode == "page":
            p = int(q["page"])
            return {"items": self.records[(p - 1) * size:p * size]}, {}
        if self.mode == "offset":
            o = int(q["offset"])
            return {"items": self.records[o:o + size]}, {}
        if self.mode == "next_url":
            start = int(q.get("from", 0))
            nxt = start + size
            return {"items": self.records[start:start + size],
                    "links": {"next": f"/items?from={nxt}" if nxt < len(self.records) else None}}, {}
        if self.mode == "stuck":
            return {"items": self.records[:size], "next": "same"}, {}
        if self.mode == "root":
            return self.records, {}
        raise AssertionError(self.mode)


@pytest.fixture
def api():
    made = _Api()
    yield made
    made.server.shutdown()


def _adapter(api, pagination, records="items", **extra):
    return RestAdapter({"base_url": api.base, "tables": {"invoices": {
        "path": "/items", "records": records, "pagination": pagination}}, **extra})


class TestPaging:
    @pytest.mark.parametrize("mode, pagination", [
        ("link_header", {"type": "link_header"}),
        ("page", {"type": "page", "page_param": "page", "page_size": 5}),
        ("offset", {"type": "offset", "offset_param": "offset", "page_size": 5}),
        ("next_url", {"type": "next_url", "next_field": "links.next"}),
    ])
    def test_each_declared_style_reads_every_record_once(self, api, mode, pagination):
        api.mode = mode

        rows = _adapter(api, pagination).read_all_rows("invoices", ["id"], CONFIG)

        assert [r["id"] for r in rows] == [f"r{i}" for i in range(23)]

    def test_a_root_list(self, api):
        api.mode = "root"

        assert len(_adapter(api, {"type": "none"}, records="").read_all_rows("invoices", ["id"], CONFIG)) == 23

    def test_a_repeated_page_token_is_refused_not_followed_forever(self, api, monkeypatch):
        api.mode = "stuck"
        # The page ceiling lowered, so that without the repeat check this
        # fails in fifty requests rather than a hundred thousand.
        monkeypatch.setattr(rest, "MAX_PAGES", 50)

        with pytest.raises(ApiRefused, match="same page token twice"):
            _adapter(api, {"type": "cursor", "cursor_field": "next"}).read_all_rows("invoices", ["id"], CONFIG)

    def test_numbers_stay_exact(self, api):
        api.mode = "root"

        rows = _adapter(api, {"type": "none"}, records="").read_all_rows("invoices", ["amount"], CONFIG)

        assert rows[1]["amount"] == Decimal("1.1")


class TestFailures:
    def test_server_errors_are_retried_with_growing_waits(self, api, no_waiting):
        api.mode = "root"
        api.failures = [(503, {}), (500, {}), (502, {})]

        rows = _adapter(api, {"type": "none"}, records="").read_all_rows("invoices", ["id"], CONFIG)

        assert len(rows) == 23 and no_waiting == [1.0, 2.0, 4.0]

    def test_retry_after_as_a_date_wins(self, api, no_waiting):
        import email.utils
        import time

        api.mode = "root"
        api.failures = [(429, {"Retry-After": email.utils.formatdate(time.time() + 30, usegmt=True)})]

        _adapter(api, {"type": "none"}, records="").read_all_rows("invoices", ["id"], CONFIG)

        assert 25 < no_waiting[0] <= 31

    def test_it_gives_up_after_its_retries(self, api, no_waiting):
        api.mode = "root"
        api.failures = [(503, {})] * 3

        with pytest.raises(StorageUnavailable, match="HTTP 503, still after 2 retries"):
            _adapter(api, {"type": "none"}, records="", max_retries=2).read_all_rows("invoices", ["id"], CONFIG)

    def test_a_client_error_is_not_retried(self, api, no_waiting):
        api.failures = [(404, {})]

        with pytest.raises(ApiRefused, match="HTTP 404"):
            _adapter(api, {"type": "none"}, records="").read_all_rows("invoices", ["id"], CONFIG)
        assert no_waiting == [] and api.calls == 1

    def test_an_unreachable_api_is_unavailable(self, no_waiting):
        adapter = RestAdapter({"base_url": "http://127.0.0.1:9", "max_retries": 1,
                               "tables": {"invoices": {"path": "/x"}}})

        with pytest.raises(StorageUnavailable, match="ConnectionError"):
            adapter.read_all_rows("invoices", ["id"], CONFIG)

    def test_the_credential_never_appears_in_an_error(self, api):
        class Echo(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(403)
                self.end_headers()
                self.wfile.write(f"bad key {self.headers.get('X-Key')}".encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            adapter = RestAdapter({"base_url": f"http://127.0.0.1:{server.server_address[1]}",
                                   "auth": {"type": "api_key", "name": "X-Key", "api_key": "s3cret"},
                                   "tables": {"t": {"path": "/"}}})
            with pytest.raises(ApiRefused) as refused:
                adapter.read_all_rows("t", ["id"], CONFIG)
        finally:
            server.shutdown()
        assert "s3cret" not in str(refused.value) and "***" in str(refused.value)


class TestOneReadPerSync:
    def test_columns_and_rows_come_from_one_read(self, api):
        api.mode = "root"
        adapter = _adapter(api, {"type": "none"}, records="")

        with adapter.consistent_read() as snapshot:
            adapter.columns_present("invoices")
            adapter.read_all_rows("invoices", ["id"], CONFIG)

        assert api.calls == 1 and snapshot is False, "one read; and no claim of a snapshot"


def test_retry_after_forms():
    assert retry_after_seconds("120") == 120.0
    assert retry_after_seconds("Thu, 01 Jan 2026 00:00:30 GMT", now=1767225600.0) == 30.0
    assert retry_after_seconds("soon") is None and retry_after_seconds(None) is None


@pytest.mark.parametrize("connection, error", [
    ({"tables": {"t": {"path": "/"}}}, "base_url"),
    ({"base_url": "ftp://x", "tables": {"t": {"path": "/"}}}, "base_url"),
    ({"base_url": "http://x"}, "tables"),
    ({"base_url": "http://x", "tables": {"t": {}}}, "needs `path`"),
    ({"base_url": "http://x", "tables": {"t": {"path": "/", "pagination": {"type": "magic"}}}}, "pagination.type"),
    ({"base_url": "http://x", "tables": {"t": {"path": "/", "pagination": {"type": "cursor"}}}}, "cursor_field"),
    ({"base_url": "http://x", "auth": {"type": "oauth"}, "tables": {"t": {"path": "/"}}}, "auth must be"),
])
def test_a_wrong_declaration_is_refused_at_load(connection, error):
    with pytest.raises(ValueError, match=error):
        RestAdapter(connection)


def test_a_frozen_declaration_is_accepted(api):
    """As the loader hands it over -- the CSV adapter's first live run
    failed on exactly this."""
    from core.immutable import deep_freeze

    api.mode = "root"
    frozen = deep_freeze({"base_url": api.base, "tables": {"invoices": {
        "path": "/items", "records": "", "pagination": {"type": "none"}}}})

    assert len(RestAdapter(frozen).read_all_rows("invoices", ["id"], CONFIG)) == 23


def test_it_is_registered():
    from core.deployment_loader import _READ_ADAPTER_REGISTRY

    assert _READ_ADAPTER_REGISTRY["rest"] is RestAdapter


class TestFoundInReview:
    """Each from an independent review of this adapter (19 October), each
    reproduced before it was fixed."""

    def _serve(self, handler_body):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                status, body, headers = handler_body(self)
                payload = json.dumps(body).encode() if not isinstance(body, bytes) else body
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(payload)

        server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, f"http://127.0.0.1:{server.server_address[1]}"

    def test_a_bearer_token_echoed_alone_is_masked(self):
        server, base = self._serve(lambda h: (401, b"token s3cr3tTOKEN is expired", {}))
        try:
            adapter = RestAdapter({"base_url": base, "auth": {"type": "bearer", "token": "s3cr3tTOKEN"},
                                   "tables": {"t": {"path": "/"}}})
            with pytest.raises(ApiRefused) as refused:
                adapter.read_all_rows("t", ["id"], CONFIG)
        finally:
            server.shutdown()
        assert "s3cr3tTOKEN" not in str(refused.value)

    def test_a_next_page_on_another_host_is_not_sent_the_login(self):
        server, base = self._serve(lambda h: (200, {"items": [{"id": 1}],
                                                    "next": "https://evil.example/steal"}, {}))
        try:
            adapter = RestAdapter({"base_url": base, "auth": {"type": "api_key", "name": "key",
                                                              "api_key": "K123", "in": "query"},
                                   "tables": {"t": {"path": "/", "records": "items",
                                                    "pagination": {"type": "next_url", "next_field": "next"}}}})
            with pytest.raises(ApiRefused, match="not .* the credential is not sent there"):
                adapter.read_all_rows("t", ["id"], CONFIG)
        finally:
            server.shutdown()

    def test_an_api_ignoring_the_page_parameter_is_refused_quickly(self):
        calls = []
        server, base = self._serve(lambda h: (calls.append(1), (200, {"items": [{"id": 1}, {"id": 2}]}, {}))[1])
        try:
            adapter = RestAdapter({"base_url": base, "tables": {"t": {"path": "/", "records": "items",
                                   "pagination": {"type": "page", "page_param": "pg"}}}})
            with pytest.raises(ApiRefused, match="same page twice"):
                adapter.read_all_rows("t", ["id"], CONFIG)
        finally:
            server.shutdown()
        assert len(calls) == 2

    def test_a_server_capping_the_page_size_is_still_read_to_the_end(self):
        rows = [{"id": i} for i in range(300)]

        def page(h):
            offset = int(parse_qs(urlparse(h.path).query).get("offset", ["0"])[0])
            return 200, {"items": rows[offset:offset + 100]}, {}     # caps at 100

        server, base = self._serve(page)
        try:
            adapter = RestAdapter({"base_url": base, "tables": {"t": {"path": "/", "records": "items",
                                   "pagination": {"type": "offset", "offset_param": "offset",
                                                  "page_size": 500, "page_size_param": "limit"}}}})
            read = adapter.read_all_rows("t", ["id"], CONFIG)
        finally:
            server.shutdown()
        assert len(read) == 300

    def test_the_health_check_does_not_wait_out_retries(self, no_waiting):
        server, base = self._serve(lambda h: (503, {"e": 1}, {"Retry-After": "300"}))
        try:
            adapter = RestAdapter({"base_url": base, "tables": {"t": {"path": "/"}}})
            with pytest.raises(StorageUnavailable):
                adapter.health_check()
        finally:
            server.shutdown()
        assert no_waiting == []

    def test_a_page_token_that_is_not_a_value_is_refused_by_name(self):
        server, base = self._serve(lambda h: (200, {"items": [{"id": 1}], "next": {"a": 1}}, {}))
        try:
            adapter = RestAdapter({"base_url": base, "tables": {"t": {"path": "/", "records": "items",
                                   "pagination": {"type": "cursor", "cursor_field": "next"}}}})
            with pytest.raises(ApiRefused, match="not a string or number"):
                adapter.read_all_rows("t", ["id"], CONFIG)
        finally:
            server.shutdown()
