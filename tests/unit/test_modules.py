"""
core/modules.py: which sub-apps a deployment loads, and the feed each
person is given (BLOCKING.md item 3, shell/README.md).
"""

import json
from pathlib import Path

import pytest

from core.intermediate_layer.auth import UserRecord
from core.modules import CONTRACT_VERSION, SHIPPED_HOME, SHIPPED_MODULES, ModuleError, feed_for, load_modules

ROLES = {"admin": {"allowed_actions": frozenset({"manage:users"})}, "reader": {"allowed_actions": frozenset()}}


def _user(role: str) -> UserRecord:
    return UserRecord(user_id=f"a_{role}", security_value="all", role_name=role)


def _module(folder: Path, **manifest) -> Path:
    folder.mkdir(parents=True)
    body = {"id": folder.name, "name": folder.name.title(), "version": "1",
            "contributes": {"pages": [{"id": "main", "path": f"/{folder.name}"}]}}
    body.update(manifest)
    (folder / "module.json").write_text(json.dumps(body))
    return folder


def _deployment(tmp_path: Path, folders, home="/one") -> Path:
    config = tmp_path / "config"
    config.mkdir()
    (config / "modules.yaml").write_text(json.dumps({"home": home, "modules": [str(f) for f in folders]}))
    return config


class TestWhatLoads:
    def test_no_modules_yaml_loads_what_elysium_ships_in_rail_order(self, tmp_path):
        """A deployment written before modules existed is unchanged."""
        modules = load_modules(tmp_path)

        assert modules.home == SHIPPED_HOME
        assert [m.folder for m in modules.modules] == [
            Path(__file__).resolve().parents[2] / f for f in SHIPPED_MODULES]

    def test_modules_yaml_decides_which_and_in_what_order(self, tmp_path):
        two = _module(tmp_path / "two")
        one = _module(tmp_path / "one")

        modules = load_modules(_deployment(tmp_path, [two, one]))

        assert [m.id for m in modules.modules] == ["two", "one"]
        assert modules.home == "/one"

    def test_a_module_listed_twice_is_refused(self, tmp_path):
        one = _module(tmp_path / "one")

        with pytest.raises(ModuleError, match="already loaded"):
            load_modules(_deployment(tmp_path, [one, one]))

    def test_a_folder_without_a_manifest_is_refused_by_name(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()

        with pytest.raises(ModuleError, match="has no module.json"):
            load_modules(_deployment(tmp_path, [empty]))

    def test_an_unknown_key_is_refused_rather_than_ignored(self, tmp_path):
        """A misspelt `permision` would otherwise offer an admin module to
        everyone, silently."""
        odd = _module(tmp_path / "odd", permision="manage:users")

        with pytest.raises(ModuleError, match="permision"):
            load_modules(_deployment(tmp_path, [odd]))

    def test_a_rail_entry_leading_nowhere_is_refused(self, tmp_path):
        stray = _module(tmp_path / "stray", contributes={
            "pages": [{"id": "main", "path": "/stray"}],
            "nav": [{"title": "Stray", "path": "/elsewhere"}]})

        with pytest.raises(ModuleError, match="rail entry"):
            load_modules(_deployment(tmp_path, [stray]))

    def test_a_page_declared_twice_is_refused(self, tmp_path):
        twice = _module(tmp_path / "twice", contributes={
            "pages": [{"id": "main", "path": "/a"}, {"id": "main", "path": "/b"}]})

        with pytest.raises(ModuleError, match="declared twice"):
            load_modules(_deployment(tmp_path, [twice]))

    def test_home_must_be_a_path(self, tmp_path):
        one = _module(tmp_path / "one")

        with pytest.raises(ModuleError, match="home"):
            load_modules(_deployment(tmp_path, [one], home="query"))

    def test_home_must_be_a_page_some_module_mounts(self, tmp_path):
        """Every stray address is sent home; a home nothing opens would
        send them all nowhere."""
        one = _module(tmp_path / "one")

        with pytest.raises(ModuleError, match="no loaded module's page"):
            load_modules(_deployment(tmp_path, [one], home="/query"))

    def test_every_shipped_manifest_loads(self, tmp_path):
        """THE MANIFESTS IN THIS REPOSITORY pass their own checks."""
        assert len(load_modules(tmp_path).modules) == len(SHIPPED_MODULES)


class TestTheFeed:
    def test_a_permission_module_is_offered_only_to_whoever_holds_it(self, tmp_path):
        open_ = _module(tmp_path / "open")
        gated = _module(tmp_path / "gated", permission="manage:users")
        modules = load_modules(_deployment(tmp_path, [open_, gated], home="/open"))

        assert [m["id"] for m in feed_for(modules, _user("reader"), ROLES)["modules"]] == ["open"]
        assert [m["id"] for m in feed_for(modules, _user("admin"), ROLES)["modules"]] == ["open", "gated"]

    def test_the_feed_is_the_contracts_shape_and_carries_no_permission_or_folder(self, tmp_path):
        """Names, never contents: the folder is a path on the server, and
        the permission is the server's business."""
        one = _module(tmp_path / "one", permission="manage:users")
        modules = load_modules(_deployment(tmp_path, [one]))

        feed = feed_for(modules, _user("admin"), ROLES)

        assert feed["contract"] == CONTRACT_VERSION
        assert feed["home"] == "/one"
        assert set(feed["modules"][0]) == {"id", "name", "version", "contributes", "entry"}
        assert str(tmp_path) not in json.dumps(feed)
