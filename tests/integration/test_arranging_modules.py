"""The module manager changing the deployment (BLOCKING.md item 3, step
1.4c): turning modules on and off, ordering the rail, setting home --
over HTTP, against a COPY of the fixture configuration, since these
tests write modules.yaml and the shared fixtures must never be the file
written (the fixtures come from test_editing_config_from_the_ui.py,
which checks exactly that)."""

import pytest
import yaml

from tests.conftest import read_audit_log, with_roles
from tests.integration.test_api import _csrf_headers, _login
from tests.integration.test_editing_config_from_the_ui import _grant, config_dir, deployer  # noqa: F401

ROUTE = "/api/shell/modules/arrangement"


def _arrangement(client) -> dict:
    response = client.get(ROUTE)
    assert response.status_code == 200, response.text
    return response.json()


def _order(shown: dict, off: "set[str]" = frozenset(), first: "str | None" = None) -> list:
    """Every arrangeable module, on unless named in `off`, `first` moved
    to the front."""
    ids = [m["id"] for m in shown["modules"] if not m["pinned"]]
    if first is not None:
        ids = [first] + [i for i in ids if i != first]
    return [[i, i not in off] for i in ids]


def _save(client, shown, order, home=None, digest=None):
    response = client.put(ROUTE, headers=_csrf_headers(client), json={
        "home": home or shown["home"], "modules": order, "digest": digest or shown["digest"]})
    # A REAL RELOAD drops the role the fixture added to the running
    # configuration only (with_roles); granted again for the next call.
    _grant(client)
    return response


def test_it_lists_every_module_on_and_off_with_the_system_one_pinned(deployer):  # noqa: F811
    shown = _arrangement(deployer)

    ids = [m["id"] for m in shown["modules"]]
    assert {"browse", "query", "schema", "inbox", "admin", "system"} <= set(ids)
    assert [m["id"] for m in shown["modules"] if m["pinned"]] == ["system"]
    assert all(m["enabled"] for m in shown["modules"])


def test_it_is_for_manage_deployment_only(client):
    with_roles(client.app, reader={"allowed_actions": frozenset()})
    client.app.state.user_directory.create_user("rita", "reader-pw-123", None, "reader")
    _login(client, "rita", "reader-pw-123")

    assert client.get(ROUTE).status_code == 403
    assert client.put(ROUTE, headers=_csrf_headers(client),
                      json={"home": "/query", "modules": [], "digest": "x"}).status_code == 403


def test_turning_one_off_and_reordering_writes_modules_yaml_and_changes_the_feed(deployer, config_dir):  # noqa: F811
    shown = _arrangement(deployer)

    # Inbox moved first: a module this role is OFFERED, so the feed shows
    # the order (Admin, for one, needs manage:users).
    response = _save(deployer, shown, _order(shown, off={"schema"}, first="inbox"))

    assert response.status_code == 200, response.text
    written = yaml.safe_load((config_dir / "modules.yaml").read_text())
    assert written["modules"][0] == "ui/packages/app-inbox" and "ui/packages/app-schema" in written["modules"]
    assert written["disabled"] == ["ui/packages/app-schema"]
    feed = [m["id"] for m in deployer.get("/api/shell/modules").json()["modules"]]
    assert feed == ["inbox", "browse", "query", "approvals", "notifications", "identity", "system"]
    # Off, and in its place: it comes back there when turned on.
    rows = [(m["id"], m["enabled"]) for m in response.json()["modules"]]
    assert rows == [("inbox", True), ("browse", True), ("query", True), ("schema", False),
                    ("approvals", True), ("notifications", True), ("identity", True), ("admin", True),
                    ("system", True)]


def test_one_turned_off_can_be_turned_on_again(deployer):  # noqa: F811
    shown = _arrangement(deployer)
    after_off = _save(deployer, shown, _order(shown, off={"schema"})).json()

    response = _save(deployer, after_off, _order(after_off))

    assert response.status_code == 200, response.text
    assert "schema" in [m["id"] for m in deployer.get("/api/shell/modules").json()["modules"]]


def test_it_is_audited(deployer):  # noqa: F811
    shown = _arrangement(deployer)
    _save(deployer, shown, _order(shown, off={"schema"}))

    entries = [e for e in read_audit_log(deployer.app.state.runtime_paths.log_dir)
               if e.get("stage") == "config_edit" and e.get("file") == "modules.yaml"]
    assert entries and entries[-1]["outcome"] == "applied"
    assert entries[-1]["changes"]["off"] == ["schema"]


def test_a_stale_arrangement_is_refused_rather_than_merged(deployer, config_dir):  # noqa: F811
    shown = _arrangement(deployer)
    _save(deployer, shown, _order(shown, off={"schema"}))
    before = (config_dir / "modules.yaml").read_text()

    response = _save(deployer, shown, _order(shown, off={"query"}))

    assert response.status_code == 409
    assert (config_dir / "modules.yaml").read_text() == before


def test_a_system_sub_app_cannot_be_arranged(deployer, config_dir):  # noqa: F811
    shown = _arrangement(deployer)

    response = _save(deployer, shown, _order(shown) + [["system", False]])

    assert response.status_code == 400
    assert "system sub-app" in response.json()["detail"]
    assert not (config_dir / "modules.yaml").exists()


def test_an_arrangement_that_would_not_load_writes_nothing(deployer, config_dir):  # noqa: F811
    """Home must open something: home on a module turned off is refused
    by the loader, run on the candidate before anything is written."""
    shown = _arrangement(deployer)

    response = _save(deployer, shown, _order(shown, off={"query"}), home="/query")

    assert response.status_code == 400
    assert "would not load" in response.json()["detail"]
    assert not (config_dir / "modules.yaml").exists()
    assert "query" in [m["id"] for m in deployer.get("/api/shell/modules").json()["modules"]]


@pytest.mark.parametrize("missing", ["csrf"])
def test_a_save_without_the_csrf_header_is_refused(deployer, missing):  # noqa: F811
    shown = _arrangement(deployer)

    response = deployer.put(ROUTE, json={"home": shown["home"], "modules": _order(shown), "digest": shown["digest"]})

    assert response.status_code == 403
