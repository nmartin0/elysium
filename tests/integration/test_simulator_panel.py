"""The simulator's control panel as a module of a running Elysium
(BLOCKING.md item 3, step 2.3): listed in modules.yaml, offered to holders
of the permission it declares, its server started by Elysium and reached
through the proxy, saying who is asking. A WORLD IS NOT STARTED HERE --
PostgreSQL refuses to run as root, and the simulator's own suite
(sim/tests/test_panel.py) drives a real one as an ordinary user."""

import pytest
import yaml

from api.addon_servers import read_state
from core.modules import ELYSIUM_ROOT
from tests.integration.test_addon_lifecycle import _wait
from tests.integration.test_addon_proxy import write_modules
from tests.integration.test_api import _csrf_headers, _login
from tests.integration.test_editing_config_from_the_ui import config_dir  # noqa: F401

PANEL = ELYSIUM_ROOT / "sim" / "panel"


@pytest.fixture
def deployment(config_dir, tmp_path, request):  # noqa: F811
    write_modules(config_dir, PANEL)
    (config_dir / "addons.yaml").write_text(yaml.safe_dump(
        {"simulator": {"options": {"directory": str(tmp_path / "world")}}}))
    policy = yaml.safe_load((config_dir / "policy.yaml").read_text())
    policy["roles"]["operator"] = {"allowed_actions": ["module:simulator:operate"]}
    (config_dir / "policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False))
    client = request.getfixturevalue("client")
    client.app.state.user_directory.create_user("olga", "correct-pw", None, "operator")
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    return client


def _running(client) -> bool:
    return (read_state(client.app.state.runtime_paths.data_dir, "simulator") or {}).get("state") == "running"


def test_an_operator_is_offered_the_panel_and_its_server_answers_through_elysium(deployment, tmp_path):
    with deployment:
        _wait(lambda: _running(deployment))
        _login(deployment, "olga", "correct-pw")

        feed = {m["id"]: m for m in deployment.get("/api/shell/modules").json()["modules"]}
        assert feed["simulator"]["contributes"]["nav"] == [
            {"title": "Simulator", "path": "/simulator", "subject": "Testing"}]
        shown = deployment.get("/api/addons/simulator/state").json()

        assert shown["phase"] == "stopped" and shown["may_operate"] is True
        assert shown["directory"] == str(tmp_path / "world")
        assert {"probe", "retail", "field_service"} <= {p["name"] for p in shown["packs"]}
        # A refusal of the panel's own comes back as its own words.
        refused = deployment.post("/api/addons/simulator/start", json={"pack": "nonsense"},
                                  headers=_csrf_headers(deployment))
        assert refused.status_code == 409 and "no pack 'nonsense'" in refused.json()["detail"]


def test_someone_without_the_permission_is_not_offered_it_at_all(deployment):
    _login(deployment, "alice", "correct-pw")

    assert "simulator" not in [m["id"] for m in deployment.get("/api/shell/modules").json()["modules"]]
    assert deployment.get("/api/addons/simulator/state").status_code == 404
