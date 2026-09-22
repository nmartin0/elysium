"""
Every SOURCE is checked -- at startup, by /api/silos and by /api/health
-- and never the mirror in its place (E-13).

MEASURED BEFORE: nothing checked at startup; and with read_from_mirror
on (the default) both routes checked the mediator's adapters, which are
the mirror's. With the source database DELETED, /api/silos reported it
healthy and /api/health said "reachable".
"""

import logging

import pytest
from fastapi.testclient import TestClient

from core.source_health import source_failures

PW = "a-long-and-unremarkable-passphrase"


def _app(paths, monkeypatch):
    monkeypatch.setenv("ELYSIUM_DATA_DIR", str(paths.data_dir))
    monkeypatch.setenv("ELYSIUM_LOG_DIR", str(paths.log_dir))
    from api.app import create_app
    return create_app(paths)


@pytest.fixture
def served(synced_deployment, monkeypatch):
    app = _app(synced_deployment, monkeypatch)
    app.state.user_directory.create_user("dana", PW, "us-west", "debug")
    client = TestClient(app, base_url="https://testserver")  # the session cookie is Secure
    client.post("/api/login", json={"username": "dana", "password": PW})
    return client, synced_deployment


def _delete_source(paths):
    (paths.data_dir / "dev_fixtures" / "mediator.db").unlink()


class TestTheSiloStatus:
    def _failures(self, client):
        return {s["name"]: s.get("failure") for s in client.get("/api/silos").json()}

    def test_a_present_source_is_healthy(self, served):
        client, _ = served
        assert self._failures(client) == {"primary_sql": None}

    def test_a_deleted_source_is_reported_by_name(self, served):
        """THE REPRODUCTION: it read healthy, from the mirror."""
        client, paths = served
        _delete_source(paths)

        assert self._failures(client) == {"primary_sql": "FileNotFoundError"}


class TestTheHealthEndpoint:
    def test_all_reachable(self, served):
        client, _ = served
        body = client.get("/api/health").json()

        assert body["checks"]["silos"] == "reachable"
        assert body["checks"]["mirror"] == "reachable"
        assert body["status"] == "ok"

    def test_a_deleted_source_is_unreachable_while_the_mirror_is_not(self, served):
        """THE REPRODUCTION: it read "reachable". The two are reported
        apart -- the mirror still serves its last synced contents."""
        client, paths = served
        _delete_source(paths)

        body = client.get("/api/health").json()

        assert body["checks"]["silos"] == "unreachable"
        assert body["checks"]["mirror"] == "reachable"
        assert body["status"] == "degraded"

    def test_and_says_nothing_about_why(self, served):
        """UNAUTHENTICATED: a connection error carries paths and hosts."""
        client, paths = served
        _delete_source(paths)

        text = client.get("/api/health").text

        assert "FileNotFoundError" not in text and "mediator.db" not in text


class TestAtStartup:
    def test_a_missing_source_is_named_and_the_service_still_starts(self, synced_deployment, monkeypatch, caplog):
        _delete_source(synced_deployment)

        with caplog.at_level(logging.WARNING, logger="api.app"):
            app = _app(synced_deployment, monkeypatch)

        assert app is not None
        named = [r.getMessage() for r in caplog.records if "startup check" in r.getMessage()]
        assert len(named) == 1 and "'primary_sql'" in named[0] and "FileNotFoundError" in named[0]

    def test_a_healthy_start_warns_about_nothing(self, synced_deployment, monkeypatch, caplog):
        with caplog.at_level(logging.WARNING, logger="api.app"):
            _app(synced_deployment, monkeypatch)

        assert not [r for r in caplog.records if "startup check" in r.getMessage()]


def test_the_source_adapters_are_built_once_per_generation(served):
    """/health may be polled; building adapters per request would cost."""
    client, _ = served
    client.get("/api/health")
    first = client.app.state.live_source_adapters[1]
    client.get("/api/health")

    assert client.app.state.live_source_adapters[1] is first


class TestSourceFailures:
    class Healthy:
        def health_check(self):
            return None

    class Broken:
        def health_check(self):
            raise ConnectionRefusedError("host 10.0.0.5 refused")

    def test_a_healthy_source_is_absent(self):
        assert source_failures(["a"], {"a": self.Healthy()}) == {}

    def test_a_failing_one_is_named_by_what_failed(self):
        assert source_failures(["a"], {"a": self.Broken()}) == {"a": "ConnectionRefusedError"}

    def test_one_without_an_adapter_is_not_configured(self):
        assert source_failures(["a"], {}) == {"a": "NotConfigured"}
