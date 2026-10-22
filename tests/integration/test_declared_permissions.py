"""A module's declared permissions in a running deployment (BLOCKING.md
item 3, step 2.3): in the role editor's registry, described; a role
holding one is offered the module; a misspelt one stops the load with
its name; and one from a module no longer listed is kept, inert, and
shown -- over HTTP, against a COPY of the fixture configuration."""

import json

import pytest
import yaml

from tests.integration.test_addon_proxy import ECHO, write_modules
from tests.integration.test_api import _login
from tests.integration.test_editing_config_from_the_ui import config_dir  # noqa: F401

PANEL = {"id": "panel", "name": "Panel", "version": "1", "permission": "module:panel:operate",
         "permissions": [{"id": "operate", "description": "Drive the world"}],
         "contributes": {"pages": [{"id": "main", "path": "/panel"}],
                         "nav": [{"title": "Panel", "path": "/panel"}]}}


def _roles(config_dir, **roles):  # noqa: F811
    path = config_dir / "policy.yaml"
    policy = yaml.safe_load(path.read_text())
    policy["roles"].update({name: {"allowed_actions": grants} for name, grants in roles.items()})
    path.write_text(yaml.safe_dump(policy, sort_keys=False))


@pytest.fixture
def deployment(config_dir, tmp_path, request):  # noqa: F811
    folder = tmp_path / "panel"
    folder.mkdir()
    (folder / "module.json").write_text(json.dumps(PANEL))
    write_modules(config_dir, ECHO, folder)
    _roles(config_dir, operator=["module:panel:operate", "module:gone:thing"],
           roler=["manage:roles"])
    client = request.getfixturevalue("client")
    directory = client.app.state.user_directory
    directory.create_user("olga", "correct-pw", None, "operator")
    directory.create_user("rolf", "correct-pw", None, "roler")
    directory.create_user("alice", "correct-pw", None, "customer_service")
    return client


def _rail(client) -> list[str]:
    return [m["id"] for m in client.get("/api/shell/modules").json()["modules"]]


def test_holding_the_declared_permission_is_what_offers_the_module(deployment):
    _login(deployment, "olga", "correct-pw")
    assert "panel" in _rail(deployment)

    _login(deployment, "alice", "correct-pw")
    assert "panel" not in _rail(deployment)


def test_the_role_editor_offers_it_described_and_shows_one_no_longer_listed(deployment):
    _login(deployment, "rolf", "correct-pw")

    shown = deployment.get("/api/roles").json()

    assert "module:panel:operate" in shown["grantable"]
    assert {"grant": "module:panel:operate", "module": "panel", "module_name": "Panel",
            "description": "Drive the world"} in shown["module_permissions"]
    assert shown["unlisted"] == ["module:gone:thing"]
    assert "module:gone:thing" not in shown["grantable"]


def test_a_misspelt_one_stops_the_load_with_its_name(config_dir, tmp_path, request):  # noqa: F811
    folder = tmp_path / "panel"
    folder.mkdir()
    (folder / "module.json").write_text(json.dumps(PANEL))
    write_modules(config_dir, folder)
    _roles(config_dir, operator=["module:panel:operat"])

    with pytest.raises(ValueError, match="module:panel:operat.*It declares: \\['operate'\\]"):
        request.getfixturevalue("client")
