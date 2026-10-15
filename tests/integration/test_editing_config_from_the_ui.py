"""Editing config.yaml from the UI, over HTTP, against a COPY of the
fixture configuration -- these tests write the file, and the shared
fixtures must never be the file written."""

import shutil
import sys
from pathlib import Path

import pytest
import yaml

import tests.integration.conftest as integration_conftest
from tests.conftest import read_audit_log, with_roles
from tests.integration.test_api import _csrf_headers, _login  # noqa: F401


@pytest.fixture
def config_dir(tmp_path, monkeypatch, request):
    copy = tmp_path / "config"
    shutil.copytree(integration_conftest.FIXTURES_DIR, copy)
    # EVERY LOADED COPY OF conftest.py: pytest imports it under its own
    # name, so the module this file imports is not the one the `client`
    # fixture reads FIXTURES_DIR from. The `deployer` fixture asserts the
    # result, because a patch that misses would write the shared fixtures.
    #
    # FROM PYTEST'S PLUGIN MANAGER AS WELL AS sys.modules. Every conftest
    # is registered as `conftest`, so when another directory's conftest
    # loads in the same session -- running these beside tests/unit --
    # sys.modules["conftest"] is a DIFFERENT file and the copy `client`
    # reads is reachable only through the plugin manager. Seen: the
    # assertion below refused all nine tests in a mixed run, and nothing
    # was written to the shared fixtures, which is what it is for.
    conftest_file = Path(integration_conftest.__file__).resolve()
    candidates = [*sys.modules.values(), *request.config.pluginmanager.get_plugins()]
    for module in {id(m): m for m in candidates}.values():
        if getattr(module, "__file__", None) and Path(module.__file__).resolve() == conftest_file:
            monkeypatch.setattr(module, "FIXTURES_DIR", copy)
    return copy


@pytest.fixture
def deployer(config_dir, request):
    client = request.getfixturevalue("client")
    assert client.app.state.runtime_paths.config_dir == config_dir
    _grant(client)
    client.app.state.user_directory.create_user("ops", "correct-pw", "us-west", "deployer")
    _login(client, "ops", "correct-pw")
    return client


def _grant(client):
    with_roles(client.app, deployer={"allowed_actions": frozenset(["manage:deployment"])})


def _settings(client):
    response = client.get("/api/admin/config/settings")
    assert response.status_code == 200, response.text
    return response.json()


def _apply(client, changes, digest=None):
    return client.put("/api/admin/config/settings", headers=_csrf_headers(client),
                      json={"digest": digest or _settings(client)["digest"], "changes": changes})


def test_the_form_shows_each_setting_present_or_absent(deployer):
    settings = {s["key"]: s for s in _settings(deployer)["settings"]}
    assert settings["agent.max_hops"]["present"] is True
    assert isinstance(settings["agent.max_hops"]["value"], int)
    assert settings["agent.filter_operators"]["present"] is False


def test_a_preview_shows_the_lines_and_writes_nothing(deployer, config_dir):
    before = (config_dir / "config.yaml").read_text()
    body = _settings(deployer)
    response = deployer.post("/api/admin/config/settings/preview", headers=_csrf_headers(deployer),
                             json={"digest": body["digest"], "changes": {"agent.max_hops": 11}})
    assert response.status_code == 200, response.text
    assert any(line.startswith("+") and "max_hops: 11" in line for line in response.json()["diff"])
    assert (config_dir / "config.yaml").read_text() == before


def test_an_applied_edit_reaches_the_file_and_the_running_deployment(deployer, config_dir):
    before = deployer.app.state.generation.generation
    response = _apply(deployer, {"agent.max_hops": 11})
    assert response.status_code == 200, response.text

    assert yaml.safe_load((config_dir / "config.yaml").read_text())["agent"]["max_hops"] == 11
    assert deployer.app.state.generation.generation > before
    assert deployer.app.state.generation.config.max_hops == 11


def test_every_comment_in_the_file_survives(deployer, config_dir):
    def comments():
        return [line for line in (config_dir / "config.yaml").read_text().splitlines()
                if line.strip().startswith("#")]
    before = comments()
    assert _apply(deployer, {"agent.max_hops": 11, "agent.filter_operators": True}).status_code == 200
    assert set(before) <= set(comments())


def test_a_change_since_it_was_read_is_refused_not_overwritten(deployer, config_dir):
    stale = _settings(deployer)["digest"]
    path = config_dir / "config.yaml"
    path.write_text(path.read_text() + "\n# an operator's hand edit\n")

    response = _apply(deployer, {"agent.max_hops": 11}, digest=stale)
    assert response.status_code == 409
    assert "an operator's hand edit" in path.read_text()


def test_a_file_that_would_not_load_never_reaches_the_disk(deployer, config_dir, monkeypatch):
    """The editor's own checks pass this; the LOADER refuses it. Forced
    here by making the loader refuse, so the test does not depend on
    which settings happen to have cross-checks."""
    import core.deployment_loader as loader

    path = config_dir / "config.yaml"
    before = path.read_text()
    original = loader.load_deployment

    def refuse(base_path):
        if base_path != config_dir:
            raise ValueError("config.yaml: agent.max_hops is too many for this model")
        return original(base_path)
    monkeypatch.setattr(loader, "load_deployment", refuse)

    response = _apply(deployer, {"agent.max_hops": 11})
    assert response.status_code == 400
    assert "would not load" in response.json()["detail"]
    assert path.read_text() == before


def test_a_reload_that_fails_puts_the_old_file_back(deployer, config_dir, monkeypatch):
    import api.routes as routes

    path = config_dir / "config.yaml"
    before = path.read_text()

    def failing_reload(app, requested_by="unknown", announce=True):
        raise RuntimeError("the silo is unreachable")
    monkeypatch.setattr(routes, "reload_generation", failing_reload)

    response = _apply(deployer, {"agent.max_hops": 11})
    assert response.status_code == 400
    assert path.read_text() == before


def test_it_is_audited_with_who_and_what(deployer, config_dir):
    assert _apply(deployer, {"agent.max_hops": 11}).status_code == 200
    entries = [entry for entry in read_audit_log(deployer.app.state.runtime_paths.log_dir)
               if entry.get("stage") == "config_edit"]
    assert entries[-1]["outcome"] == "applied"
    assert entries[-1]["changes"] == {"agent.max_hops": 11}
    assert entries[-1]["from_digest"] != entries[-1]["to_digest"]


def test_a_setting_not_on_the_list_is_refused(deployer, config_dir):
    before = (config_dir / "config.yaml").read_text()
    response = _apply(deployer, {"llm.connection.base_url": "http://attacker.example"})
    assert response.status_code == 400
    assert (config_dir / "config.yaml").read_text() == before


def test_someone_who_manages_users_but_not_the_deployment_may_not(config_dir, client):
    with_roles(client.app, admin_only={"allowed_actions": frozenset(["manage:users"])})
    client.app.state.user_directory.create_user("hr", "correct-pw", "us-west", "admin_only")
    _login(client, "hr", "correct-pw")
    assert client.get("/api/admin/config/settings").status_code == 403
    assert client.put("/api/admin/config/settings", headers=_csrf_headers(client),
                      json={"digest": "x", "changes": {"agent.max_hops": 11}}).status_code == 403
