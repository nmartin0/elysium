"""
core/modules.py: which sub-apps a deployment loads, and the feed each
person is given (BLOCKING.md item 3, shell/README.md).
"""

import json
import re
from pathlib import Path

import pytest
import yaml

from core.intermediate_layer.auth import UserRecord
from core.modules import (
    CONTRACT_VERSION,
    SHIPPED_HOME,
    SHIPPED_MODULES,
    SYSTEM_MODULES,
    ModuleError,
    arrangement,
    bundle_file,
    feed_for,
    load_modules,
    render_modules_yaml,
)

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
            Path(__file__).resolve().parents[2] / f for f in SHIPPED_MODULES + SYSTEM_MODULES]

    def test_modules_yaml_decides_which_and_in_what_order(self, tmp_path):
        two = _module(tmp_path / "two")
        one = _module(tmp_path / "one")

        modules = load_modules(_deployment(tmp_path, [two, one]))

        assert [m.id for m in modules.modules] == ["two", "one", "system"]
        assert modules.home == "/one"

    def test_a_module_listed_twice_is_refused(self, tmp_path):
        one = _module(tmp_path / "one")

        with pytest.raises(ModuleError, match="already listed"):
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
        assert len(load_modules(tmp_path).modules) == len(SHIPPED_MODULES) + len(SYSTEM_MODULES)


class TestAModuleThatMoved:
    """A shipped module whose folder moved (MOVED_MODULES): a modules.yaml
    naming the old folder -- one the module manager wrote -- still loads,
    says so, and is written with the new folder on the next save."""

    SAVED = {"home": "/query",
             "modules": ["ui/packages/app-query", "ui/src/inbox", "ui/packages/app-approvals",
                         "ui/packages/app-notifications", "ui/packages/app-identity"],
             "disabled": ["ui/src/inbox"]}

    def _saved(self, tmp_path: Path) -> Path:
        (tmp_path / "modules.yaml").write_text(json.dumps(self.SAVED))
        return tmp_path

    def test_the_old_folder_is_read_as_the_new_one_and_said(self, tmp_path, caplog):
        modules = load_modules(self._saved(tmp_path))

        inbox = next(m for m in modules.off if m.id == "inbox")
        assert inbox.listed_as == "ui/packages/app-inbox"
        assert "ui/src/inbox has moved to ui/packages/app-inbox" in caplog.text
        assert str(tmp_path / "modules.yaml") in caplog.text

    def test_the_next_save_writes_the_new_folder(self, tmp_path):
        modules = load_modules(self._saved(tmp_path))
        order = [(module_id, module_id != "inbox") for module_id in modules.order]

        written = yaml.safe_load(render_modules_yaml(modules, modules.home, order))

        assert "ui/packages/app-inbox" in written["modules"] and "ui/src/inbox" not in written["modules"]
        assert written["disabled"] == ["ui/packages/app-inbox"]


class TestTheSystemSubApps:
    """Always loaded, last, and pinned (step 1.4): safe mode exists for
    when a module breaks the page, and a module must not be able to take
    away the tool that fixes it."""

    def test_they_load_after_every_module_and_are_pinned(self, tmp_path):
        modules = load_modules(_deployment(tmp_path, [_module(tmp_path / "one")]))

        assert [(m.id, m.pinned) for m in modules.modules] == [("one", False), ("system", True)]

    def test_modules_yaml_cannot_list_one(self, tmp_path):
        """So no edit to that file -- the module manager's included --
        can drop it."""
        config = tmp_path / "config"
        config.mkdir()
        (config / "modules.yaml").write_text(json.dumps({"home": "/system/modules", "modules": list(SYSTEM_MODULES)}))

        with pytest.raises(ModuleError, match="system sub-app"):
            load_modules(config)

    def test_a_module_cannot_take_a_system_sub_apps_id(self, tmp_path):
        imposter = _module(tmp_path / "imposter", id="system")

        with pytest.raises(ModuleError, match="system sub-app"):
            load_modules(_deployment(tmp_path, [imposter], home="/imposter"))

    def test_a_module_cannot_pin_itself(self, tmp_path):
        folder = _module(tmp_path / "bold", pinned=True)

        with pytest.raises(ModuleError, match="does not understand"):
            load_modules(_deployment(tmp_path, [folder], home="/bold"))

    def test_the_feed_says_which_are_pinned_to_whoever_is_offered_them(self, tmp_path):
        roles = {"ops": {"allowed_actions": frozenset({"manage:deployment"})},
                 "reader": {"allowed_actions": frozenset()}}
        modules = load_modules(_deployment(tmp_path, [_module(tmp_path / "one")]))

        ops = feed_for(modules, _user("ops"), roles)["modules"]
        reader = feed_for(modules, _user("reader"), roles)["modules"]

        assert [(m["id"], m["pinned"]) for m in ops] == [("one", False), ("system", True)]
        assert [m["id"] for m in reader] == ["one"]


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
        assert set(feed["modules"][0]) == {"id", "name", "version", "contributes", "entry", "styles",
                                           "activationEvents", "pinned"}
        assert str(tmp_path) not in json.dumps(feed)


class TestActivationEvents:
    """When a module's code runs besides its pages opening (step 1.3:
    VS Code's activationEvents)."""

    def test_the_feed_carries_them(self, tmp_path):
        one = _module(tmp_path / "one", activationEvents=["onPalette"])
        feed = feed_for(load_modules(_deployment(tmp_path, [one])), _user("admin"), ROLES)

        assert feed["modules"][0]["activationEvents"] == ["onPalette"]

    def test_on_startup_is_one(self, tmp_path):
        """For a badge on the rail from the first screen (step 1.3c)."""
        one = _module(tmp_path / "one", activationEvents=["onStartup", "onPalette"])
        feed = feed_for(load_modules(_deployment(tmp_path, [one])), _user("admin"), ROLES)

        assert feed["modules"][0]["activationEvents"] == ["onStartup", "onPalette"]

    def test_a_module_naming_none_carries_an_empty_list(self, tmp_path):
        one = _module(tmp_path / "one")
        feed = feed_for(load_modules(_deployment(tmp_path, [one])), _user("admin"), ROLES)

        assert feed["modules"][0]["activationEvents"] == []

    @pytest.mark.parametrize("events", [["onPallete"], "onPalette", [3]])
    def test_a_misspelt_or_malformed_one_is_refused_at_load(self, tmp_path, events):
        """A typo in module.json is said when Elysium starts, rather than a
        module whose commands silently never appear."""
        folder = _module(tmp_path / "bad", activationEvents=events)

        with pytest.raises(ModuleError, match="activation"):
            load_modules(_deployment(tmp_path, [folder], home="/bad"))


class TestTheModuleApiItNeeds:
    """`api` in module.json (BLOCKING.md item 3, step 4): the module API
    version a module needs, "^1.0". Whether the page offers it is the
    shell's to decide (shell/core/src/contract.ts, apiRefusal); a version
    written wrong is said here, at load."""

    def test_the_feed_carries_it(self, tmp_path):
        one = _module(tmp_path / "one", api="^1.0")
        feed = feed_for(load_modules(_deployment(tmp_path, [one])), _user("admin"), ROLES)

        assert feed["modules"][0]["api"] == "^1.0"

    def test_one_naming_none_is_carried_without_it_for_the_shell_to_refuse(self, tmp_path):
        one = _module(tmp_path / "one")
        feed = feed_for(load_modules(_deployment(tmp_path, [one])), _user("admin"), ROLES)

        assert "api" not in feed["modules"][0]

    @pytest.mark.parametrize("api", ["1.0", "^1", ">=1.0", "^1.0.0", 1, ["^1.0"]])
    def test_one_written_wrong_is_refused_at_load(self, tmp_path, api):
        folder = _module(tmp_path / "bad", api=api)

        with pytest.raises(ModuleError, match=r"`api` must be the module API version it needs"):
            load_modules(_deployment(tmp_path, [folder], home="/bad"))

    def test_every_shipped_module_needs_1_0(self, tmp_path):
        # THE SAME NUMBER THE PAGE OFFERS (contract.ts MODULE_API_VERSION),
        # read rather than remembered, so the two cannot drift apart.
        contract = (Path(__file__).resolve().parents[2] / "shell" / "core" / "src" / "contract.ts").read_text()
        offered = re.search(r"MODULE_API_VERSION = '(\d+)\.(\d+)'", contract)
        assert offered is not None

        needs = {m.id: m.api for m in load_modules(tmp_path).modules}

        assert needs and set(needs.values()) == {f"^{offered[1]}.{offered[2]}"}, needs


class TestBundles:
    """A module with its own bundle (BLOCKING.md item 3, step 1.2)."""

    def _bundled(self, tmp_path, **manifest):
        folder = _module(tmp_path / "graph", entry="dist/index.js", styles=["dist/index.css"], **manifest)
        (folder / "dist").mkdir()
        (folder / "dist" / "index.js").write_text("export function activate() {}")
        (folder / "dist" / "index.css").write_text("@layer components {}")
        return folder

    def test_the_feed_gives_addresses_elysium_serves_never_the_folder(self, tmp_path):
        modules = load_modules(_deployment(tmp_path, [self._bundled(tmp_path)], home="/graph"))

        entry = feed_for(modules, _user("reader"), ROLES)["modules"][0]

        assert re.fullmatch(r"/api/modules/graph/files/dist/index\.js\?v=[0-9a-f]{12}", entry["entry"])
        assert re.fullmatch(r"/api/modules/graph/files/dist/index\.css\?v=[0-9a-f]{12}", entry["styles"][0])
        assert str(tmp_path) not in json.dumps(entry)

    def test_a_rebuilt_bundle_comes_at_a_new_address(self, tmp_path):
        """The browser imports an address once per page; a rebuilt bundle
        at the old one would be the old code."""
        folder = self._bundled(tmp_path)
        modules = load_modules(_deployment(tmp_path, [folder], home="/graph"))
        before = feed_for(modules, _user("reader"), ROLES)["modules"][0]["entry"]

        (folder / "dist" / "index.js").write_text("export function activate() { /* rebuilt */ }")
        after = feed_for(modules, _user("reader"), ROLES)["modules"][0]["entry"]

        assert before != after
        assert before.split("?")[0] == after.split("?")[0]

    def test_a_bundle_not_built_has_an_address_without_a_fingerprint(self, tmp_path):
        folder = _module(tmp_path / "graph", entry="dist/index.js")
        modules = load_modules(_deployment(tmp_path, [folder], home="/graph"))

        assert feed_for(modules, _user("reader"), ROLES)["modules"][0]["entry"] == \
            "/api/modules/graph/files/dist/index.js"

    def test_a_name_no_file_can_have_is_absent_not_an_error(self, tmp_path):
        graph = load_modules(_deployment(tmp_path, [self._bundled(tmp_path)], home="/graph")).modules[0]

        assert bundle_file(graph, "dist/a\x00.js") is None

    def test_a_module_built_into_the_page_has_no_entry_and_no_styles(self, tmp_path):
        modules = load_modules(_deployment(tmp_path, [_module(tmp_path / "one")]))

        entry = feed_for(modules, _user("reader"), ROLES)["modules"][0]

        assert entry["entry"] is None
        assert entry["styles"] == []

    @pytest.mark.parametrize("entry", ["../escape.js", "/etc/passwd", "dist/../../x.js", "dist\\\\index.js", ""])
    def test_an_entry_leaving_the_folder_is_refused(self, tmp_path, entry):
        folder = _module(tmp_path / "bad", entry=entry)

        with pytest.raises(ModuleError, match="entry"):
            load_modules(_deployment(tmp_path, [folder], home="/bad"))

    def test_styles_without_a_bundle_are_refused(self, tmp_path):
        folder = _module(tmp_path / "bad", styles=["dist/index.css"])

        with pytest.raises(ModuleError, match="no `entry`"):
            load_modules(_deployment(tmp_path, [folder], home="/bad"))

    def test_styles_outside_the_bundles_directory_are_refused(self, tmp_path):
        """The bundle's directory is all Elysium serves of a folder."""
        folder = _module(tmp_path / "bad", entry="dist/index.js", styles=["styles/index.css"])

        with pytest.raises(ModuleError, match="beside `entry`"):
            load_modules(_deployment(tmp_path, [folder], home="/bad"))

    def test_a_bundle_not_yet_built_still_loads(self, tmp_path):
        """Startup comes before `npm run build` in development and in the
        suite; the shell says so when the page is opened."""
        folder = _module(tmp_path / "graph", entry="dist/index.js")

        assert load_modules(_deployment(tmp_path, [folder], home="/graph")).modules[0].entry == "dist/index.js"

    def test_bundle_file_serves_only_the_bundles_directory(self, tmp_path):
        modules = load_modules(_deployment(tmp_path, [self._bundled(tmp_path)], home="/graph"))
        graph = modules.modules[0]

        assert bundle_file(graph, "dist/index.js") == (tmp_path / "graph" / "dist" / "index.js").resolve()
        assert bundle_file(graph, "module.json") is None
        assert bundle_file(graph, "dist/../module.json") is None
        assert bundle_file(graph, "dist/missing.js") is None
        assert bundle_file(graph, "/etc/passwd") is None

    def test_bundle_file_refuses_a_link_leading_out_of_the_directory(self, tmp_path):
        folder = self._bundled(tmp_path)
        (folder / "dist" / "escape.js").symlink_to(folder / "module.json")
        graph = load_modules(_deployment(tmp_path, [folder], home="/graph")).modules[0]

        assert bundle_file(graph, "dist/escape.js") is None

    def test_a_module_built_into_the_page_serves_nothing(self, tmp_path):
        one = load_modules(_deployment(tmp_path, [_module(tmp_path / "one")])).modules[0]

        assert bundle_file(one, "module.json") is None

    def test_the_schema_graph_ships_as_a_bundle(self, tmp_path):
        schema = next(m for m in load_modules(tmp_path).modules if m.id == "schema")

        assert schema.entry == "dist/index.js"
        assert schema.styles == ("dist/index.css",)


class TestTheArrangement:
    """What the module manager reads and writes (step 1.4c)."""

    def _config(self, tmp_path, on, off=(), home="/one"):
        config = tmp_path / "config"
        config.mkdir()
        (config / "modules.yaml").write_text(json.dumps(
            {"home": home, "modules": [str(f) for f in [*on, *off]], "disabled": [str(f) for f in off]}))
        return config

    def test_an_off_module_is_checked_known_and_loaded_nowhere(self, tmp_path):
        one, two = _module(tmp_path / "one"), _module(tmp_path / "two")
        modules = load_modules(self._config(tmp_path, [one], [two]))

        assert [m.id for m in modules.modules] == ["one", "system"]
        assert [m.id for m in modules.off] == ["two"]

    def test_a_broken_off_module_is_refused_like_any_other(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(ModuleError, match="has no module.json"):
            load_modules(self._config(tmp_path, [_module(tmp_path / "one")], [empty]))

    def test_disabled_names_only_modules_the_list_holds(self, tmp_path):
        """`disabled` marks; `modules` places. A folder only in `disabled`
        would have no place on the rail to come back to."""
        one, two = _module(tmp_path / "one"), _module(tmp_path / "two")
        config = tmp_path / "config"
        config.mkdir()
        (config / "modules.yaml").write_text(json.dumps(
            {"home": "/one", "modules": [str(one)], "disabled": [str(two)]}))
        with pytest.raises(ModuleError, match="does not list"):
            load_modules(config)

    def test_a_module_turned_off_keeps_its_place(self, tmp_path):
        one, two, three = (_module(tmp_path / n) for n in ("one", "two", "three"))
        config = tmp_path / "config"
        config.mkdir()
        (config / "modules.yaml").write_text(json.dumps(
            {"home": "/one", "modules": [str(one), str(two), str(three)], "disabled": [str(two)]}))
        modules = load_modules(config)

        assert [m.id for m in modules.modules] == ["one", "three", "system"]
        assert [(m["id"], m["enabled"]) for m in arrangement(modules)["modules"]] == [
            ("one", True), ("two", False), ("three", True), ("system", True)]

    def test_the_arrangement_lists_on_in_order_then_off_and_carries_no_folder(self, tmp_path):
        one, two = _module(tmp_path / "one"), _module(tmp_path / "two")
        shown = arrangement(load_modules(self._config(tmp_path, [one], [two])))

        assert [(m["id"], m["enabled"], m["pinned"]) for m in shown["modules"]] == [
            ("one", True, False), ("two", False, False), ("system", True, True)]
        assert shown["modules"][0]["pages"] == ["/one"]
        assert str(tmp_path) not in json.dumps(shown)

    def test_a_rendered_arrangement_loads_back_as_it_was_asked(self, tmp_path):
        one, two, three = (_module(tmp_path / n) for n in ("one", "two", "three"))
        config = self._config(tmp_path, [one, two], [three])
        modules = load_modules(config)

        (config / "modules.yaml").write_text(
            render_modules_yaml(modules, "/three", [("three", True), ("one", False), ("two", True)]))
        again = load_modules(config)

        assert [m.id for m in again.modules] == ["three", "two", "system"]
        assert [m.id for m in again.off] == ["one"]
        assert again.home == "/three"

    def test_the_folders_are_written_back_as_they_were_written(self, tmp_path):
        """A relative folder stays relative: the file must still mean the
        same thing on another machine."""
        modules = load_modules(tmp_path)
        text = render_modules_yaml(modules, "/query", [(m.id, True) for m in modules.modules if not m.pinned])
        assert '"ui/packages/app-browse"' in text
        assert str(Path(__file__).resolve().parents[2]) not in text

    @pytest.mark.parametrize("order,refusal", [
        ([("one", True), ("two", True), ("system", True)], "system sub-apps"),
        ([("one", True), ("two", True), ("ghost", True)], "no module called"),
        ([("one", True), ("one", False), ("two", True)], "listed twice"),
        ([("one", True)], "leaves out"),
    ])
    def test_it_refuses_rather_than_guesses(self, tmp_path, order, refusal):
        one, two = _module(tmp_path / "one"), _module(tmp_path / "two")
        modules = load_modules(self._config(tmp_path, [one, two]))

        with pytest.raises(ModuleError, match=refusal):
            render_modules_yaml(modules, "/one", order)

    def test_a_hand_written_off_key_is_refused_not_misread(self, tmp_path):
        """YAML 1.1 reads `off:` as false; refused by name rather than
        ignored."""
        config = tmp_path / "config"
        config.mkdir()
        (config / "modules.yaml").write_text("home: /query\noff:\n  - ui/packages/app-schema\n")
        with pytest.raises(ModuleError, match="does not understand"):
            load_modules(config)

    def test_an_off_module_is_written_in_its_place_and_marked(self, tmp_path):
        one, two = _module(tmp_path / "one"), _module(tmp_path / "two")
        modules = load_modules(self._config(tmp_path, [one, two]))

        written = yaml.safe_load(render_modules_yaml(modules, "/two", [("one", False), ("two", True)]))

        assert written["modules"] == [str(one), str(two)]
        assert written["disabled"] == [str(one)]


class TestSlots:
    """A place a module's page offers to others (step 1.5)."""

    def _owner(self, tmp_path, slots=None):
        return _module(tmp_path / "owner", contributes={
            "pages": [{"id": "main", "path": "/owner"}],
            "slots": slots if slots is not None else [{"id": "owner.tabs", "order": ["b", "a"]}]})

    def _contributor(self, tmp_path, name, into):
        return _module(tmp_path / name, contributes={"into": into})

    def test_a_contribution_to_a_declared_slot_loads_and_reaches_the_feed(self, tmp_path):
        owner = self._owner(tmp_path)
        giver = self._contributor(tmp_path, "giver", [{"slot": "owner.tabs", "id": "a", "title": "A"}])
        modules = load_modules(_deployment(tmp_path, [owner, giver], home="/owner"))

        feed = feed_for(modules, _user("admin"), ROLES)
        by_id = {m["id"]: m for m in feed["modules"]}
        assert by_id["owner"]["contributes"]["slots"] == [{"id": "owner.tabs", "order": ["b", "a"]}]
        assert by_id["giver"]["contributes"]["into"] == [{"slot": "owner.tabs", "id": "a", "title": "A"}]

    def test_a_contribution_to_a_slot_nobody_declares_is_refused_at_load(self, tmp_path):
        """A typo in `into` is said at startup, not as a tab that never appears."""
        owner = self._owner(tmp_path)
        giver = self._contributor(tmp_path, "giver", [{"slot": "owner.tab", "id": "a", "title": "A"}])
        with pytest.raises(ModuleError, match="no module declares"):
            load_modules(_deployment(tmp_path, [owner, giver], home="/owner"))

    def test_a_slot_declared_twice_is_refused(self, tmp_path):
        owner = self._owner(tmp_path)
        other = _module(tmp_path / "other", contributes={"slots": [{"id": "owner.tabs"}]})
        with pytest.raises(ModuleError, match="declared by both"):
            load_modules(_deployment(tmp_path, [owner, other], home="/owner"))

    def test_a_contribution_needs_a_slot_an_id_and_a_title(self, tmp_path):
        owner = self._owner(tmp_path)
        giver = self._contributor(tmp_path, "giver", [{"slot": "owner.tabs", "id": "a"}])
        with pytest.raises(ModuleError, match="needs a `slot`, an `id` and a `title`"):
            load_modules(_deployment(tmp_path, [owner, giver], home="/owner"))

    def test_one_module_cannot_declare_a_contribution_id_twice(self, tmp_path):
        owner = self._owner(tmp_path)
        giver = self._contributor(tmp_path, "giver", [{"slot": "owner.tabs", "id": "a", "title": "A"},
                                                      {"slot": "owner.tabs", "id": "a", "title": "Again"}])
        with pytest.raises(ModuleError, match="declared twice"):
            load_modules(_deployment(tmp_path, [owner, giver], home="/owner"))

    def test_a_slot_whose_owner_is_turned_off_still_takes_contributions(self, tmp_path):
        """Known, not shown: they wait for the owner to come back."""
        owner = self._owner(tmp_path)
        home = _module(tmp_path / "home")
        giver = self._contributor(tmp_path, "giver", [{"slot": "owner.tabs", "id": "a", "title": "A"}])
        config = tmp_path / "config"
        config.mkdir()
        (config / "modules.yaml").write_text(json.dumps(
            {"home": "/home", "modules": [str(home), str(owner), str(giver)], "disabled": [str(owner)]}))

        modules = load_modules(config)

        assert [m.id for m in modules.off] == ["owner"]
