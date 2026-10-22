"""Permissions a module declares (BLOCKING.md item 3, step 2.3): read from
its module.json, granted as module:<id>:<name>, worked out into the
registry at each load (the owner's choice, 22 October), and checked in
roles as every other grant is -- except that one from a module no longer
listed is kept, inert, rather than stopping the load."""

import json
from pathlib import Path

import pytest

from core.intermediate_layer.policy_validation import grantable, validate_roles
from core.modules import (
    ModuleError,
    _load_manifest,
    declared_permissions,
    load_modules,
    module_grant,
    permissions_by_module,
)

SIMULATOR = {"id": "simulator", "name": "Simulator", "version": "1",
             "permission": "module:simulator:operate",
             "permissions": [{"id": "operate", "description": "Start, stop, pause and break the world"},
                             {"id": "watch", "description": "See the world's state"}]}


def _module(folder: Path, manifest: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "module.json").write_text(json.dumps(manifest))
    return folder


def _deployment(tmp_path: Path, manifest: dict) -> Path:
    config = tmp_path / "config"
    config.mkdir()
    folder = _module(tmp_path / "sim", manifest)
    (config / "modules.yaml").write_text(json.dumps({"home": "/system/modules", "modules": [str(folder)]}))
    return config


class TestTheManifest:
    def test_it_declares_permissions_each_with_a_description(self, tmp_path):
        module = _load_manifest(_module(tmp_path / "m", SIMULATOR))

        assert module.permissions == (("operate", "Start, stop, pause and break the world"),
                                      ("watch", "See the world's state"))
        assert module_grant("simulator", "operate") == "module:simulator:operate"

    @pytest.mark.parametrize("permissions, said", [
        ("operate", "must be a list"),
        ([{"id": "operate"}], "an `id` and a `description`"),
        ([{"id": "Operate", "description": "x"}], "lower case"),
        ([{"id": "op:erate", "description": "x"}], "lower case"),
        ([{"id": "operate", "description": "  "}], "needs a description"),
        ([{"id": "operate", "description": "a"}, {"id": "operate", "description": "b"}], "twice"),
    ])
    def test_a_mistake_is_said_with_the_file(self, tmp_path, permissions, said):
        with pytest.raises(ModuleError, match="module.json") as refused:
            _load_manifest(_module(tmp_path / "m", {**SIMULATOR, "permissions": permissions}))
        assert said in str(refused.value)

    def test_a_module_offered_to_an_undeclared_module_permission_is_refused(self, tmp_path):
        # A TYPO THERE would offer the module to nobody, and say nothing.
        config = _deployment(tmp_path, {**SIMULATOR, "permission": "module:simulator:operat"})

        with pytest.raises(ModuleError, match="module:simulator:operat, which no listed module declares"):
            load_modules(config)


class TestTheRegistry:
    def test_it_holds_each_listed_modules_permissions_described_on_and_off(self, tmp_path):
        modules = load_modules(_deployment(tmp_path, SIMULATOR))

        assert declared_permissions(modules) == [
            {"grant": "module:simulator:operate", "module": "simulator", "module_name": "Simulator",
             "description": "Start, stop, pause and break the world"},
            {"grant": "module:simulator:watch", "module": "simulator", "module_name": "Simulator",
             "description": "See the world's state"},
        ]
        assert permissions_by_module(modules)["simulator"] == {"operate", "watch"}
        # A module with none is known, and declares nothing.
        assert permissions_by_module(modules)["system"] == frozenset()

    def test_the_role_editor_is_offered_them_after_elysiums_own(self):
        offered = grantable({}, {}, [], module_grants=["module:simulator:operate"])

        assert offered.index("module:simulator:operate") > offered.index("manage:deployment")


def _role(*grants: str) -> dict:
    return {"r": {"allowed_actions": list(grants)}}


KNOWN = {"simulator": frozenset({"operate"}), "query": frozenset()}


class TestCheckingARole:
    def test_a_declared_permission_is_a_grant_like_any(self):
        validate_roles(_role("module:simulator:operate"), {}, {}, [], KNOWN)

    def test_a_permission_a_listed_module_does_not_declare_is_refused(self):
        with pytest.raises(ValueError, match="does not declare. It declares: \\['operate'\\]"):
            validate_roles(_role("module:simulator:operat"), {}, {}, [], KNOWN)
        with pytest.raises(ValueError, match="It declares: none"):
            validate_roles(_role("module:query:run"), {}, {}, [], KNOWN)

    def test_one_from_a_module_no_longer_listed_is_kept_not_refused(self):
        # REMOVING A MODULE MUST NOT STOP THE DEPLOYMENT LOADING: the
        # grant is inert until a module of that id is listed again.
        validate_roles(_role("module:heliograph:trade"), {}, {}, [], KNOWN)

    @pytest.mark.parametrize("grant", ["module:simulator", "module::operate", "module:simulator:",
                                       "module:simulator:Operate", "module:a b:operate"])
    def test_a_malformed_one_is_refused(self, grant):
        with pytest.raises(ValueError, match="is not module:<module id>:<permission>"):
            validate_roles(_role(grant), {}, {}, [], KNOWN)
