"""An add-on posting to the Inbox through its outbox (BLOCKING.md item 3,
step 2.4; core/addons.py and api/addon_servers.deliver_outbox): delivered
to the people named who are offered the module, or to all of them; a
file it cannot take moved aside with the reason in the add-on's log; a
file read twice delivered once; and delivered whether or not the
add-on's server is up -- a notice left while Elysium was offline arrives
when it is back."""

import json
import sys
import time
from pathlib import Path

import pytest

from api.addon_servers import OUTBOX, START_FILENAME, addon_directory, read_state
from core.notifications import NotificationStore
from tests.integration.test_addon_lifecycle import World, _wait, echo_module, quick_back_off  # noqa: F401
from tests.integration.test_addon_proxy import ECHO, guarded_module, write_modules
from tests.integration.test_api import _login
from tests.integration.test_editing_config_from_the_ui import config_dir  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk" / "python"))
import elysium_addon  # noqa: E402


@pytest.fixture
def posting(tmp_path):
    world = World(tmp_path)
    store = NotificationStore(tmp_path / "notifications.db")
    world.wanted = [(echo_module(tmp_path), {})]
    supervisor = world.supervisor()
    supervisor._offered_to = lambda _module: {"ada", "bob"}
    supervisor._store = store
    world.until(lambda: world.state().get("state") == "running")
    start = json.loads((addon_directory(world.data, "echo") / START_FILENAME).read_text())
    yield world, store, start
    supervisor.close()


def _summaries(store, user):
    return [(n.kind, n.summary) for n in store.for_user(user)]


def test_to_everyone_reaches_each_person_offered_it_and_the_file_goes(posting):
    world, store, start = posting

    name = elysium_addon.post(start, "World ready", detail="probe, at 3600x")
    world.until(lambda: _summaries(store, "bob"))

    assert _summaries(store, "ada") == _summaries(store, "bob") == [("module:echo", "World ready")]
    assert store.for_user("ada")[0].detail == "probe, at 3600x"
    assert not (Path(start["outbox"]) / name).exists()


def test_a_name_not_offered_the_module_is_dropped_and_counted_not_named(posting):
    world, store, start = posting

    elysium_addon.post(start, "For two", to=["ada", "eve"])
    world.until(lambda: _summaries(store, "ada"))

    assert _summaries(store, "eve") == [] and _summaries(store, "bob") == []
    assert "1 named are not offered this module" in world.log() and "eve" not in world.log()


def test_a_file_it_cannot_take_is_moved_aside_with_the_reason_logged(posting):
    world, store, start = posting
    (Path(start["outbox"]) / "bad.json").write_text('{"to": "all", "summary": "x"}')

    world.until(lambda: (Path(start["outbox"]) / "refused" / "bad.json").exists())

    assert 'outbox: bad.json refused, moved to outbox/refused/: `to` must be "everyone"' in world.log()
    assert _summaries(store, "ada") == []


def test_a_file_read_twice_is_delivered_once(posting):
    # ELYSIUM STOPPED BETWEEN DELIVERING AND REMOVING: the same file again.
    world, store, start = posting
    elysium_addon.post(start, "Once", name="same")
    world.until(lambda: _summaries(store, "ada"))

    elysium_addon.post(start, "Once", name="same")
    world.until(lambda: not (Path(start["outbox"]) / "same.json").exists())

    assert _summaries(store, "ada") == [("module:echo", "Once")]


def test_a_notice_left_while_the_server_is_down_is_still_delivered(tmp_path):
    world = World(tmp_path)
    store = NotificationStore(tmp_path / "notifications.db")
    world.wanted = [(echo_module(tmp_path, command=["./no-such-program"]), {})]
    supervisor = world.supervisor()
    supervisor._offered_to = lambda _module: {"ada"}
    supervisor._store = store
    try:
        world.until(lambda: world.state().get("restarts", 0) >= 1)
        outbox = addon_directory(world.data, "echo") / OUTBOX
        elysium_addon.post({"outbox": str(outbox)}, "Left behind")

        world.until(lambda: _summaries(store, "ada"))
    finally:
        supervisor.close()

    assert _summaries(store, "ada") == [("module:echo", "Left behind")]


# --- in a running Elysium ---------------------------------------------------


@pytest.fixture
def deployment(config_dir, tmp_path, request):  # noqa: F811
    import yaml

    write_modules(config_dir, ECHO, guarded_module(tmp_path))
    policy = yaml.safe_load((config_dir / "policy.yaml").read_text())
    policy["roles"]["user_of_guarded"] = {"allowed_actions": ["module:guarded:use"]}
    (config_dir / "policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False))
    client = request.getfixturevalue("client")
    client.app.state.user_directory.create_user("olga", "correct-pw", None, "user_of_guarded")
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    return client


def _inbox(client, user):
    client.cookies.clear()
    _login(client, user, "correct-pw")
    return [(n["label"], n["summary"]) for n in client.get("/api/notifications").json()["notifications"]]


def test_in_elysium_everyone_means_those_offered_it_and_the_inbox_names_the_module(deployment):
    with deployment:
        data_dir = deployment.app.state.runtime_paths.data_dir
        _wait(lambda: (read_state(data_dir, "guarded") or {}).get("state") == "running")
        start = json.loads((addon_directory(data_dir, "guarded") / START_FILENAME).read_text())
        name = elysium_addon.post(start, "Guarded news")
        _wait(lambda: not (Path(start["outbox"]) / name).exists())
        time.sleep(0.2)

        assert _inbox(deployment, "olga") == [("Guarded", "Guarded news")]
        assert _inbox(deployment, "alice") == []
