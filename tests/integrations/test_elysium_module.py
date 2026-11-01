# SPDX-FileCopyrightText: 2026 Nicholas Martin
# SPDX-License-Identifier: LicenseRef-Proprietary

"""Heliograph's Elysium module (``integrations/elysium``): the manifest follows what
Elysium's loader accepts, and the page and the engine agree.

``MANIFEST_KEYS`` and the other rules below restate ``core/modules.py`` of Elysium
(``348414e0``), which Elysium refuses at load; they are the only copy of its rules this
repository keeps. ``docs/research/elysium-slice1.md`` says how it was also loaded by
Elysium's own loader."""

import json
import re
from pathlib import Path
from typing import Any

from heliograph.app import addon
from heliograph.app.server import STOP_DEADLINE, Backtests, Settings, make_app
from heliograph.core.clock import SimulatedClock
from heliograph.core.time import Timestamp

FOLDER = Path(__file__).resolve().parents[2] / "integrations" / "elysium"
MANIFEST: dict[str, Any] = json.loads((FOLDER / "module.json").read_text())

MANIFEST_KEYS = {
    "id", "name", "version", "permission", "contributes", "entry", "styles",
    "activationEvents", "server", "permissions", "api",
}  # fmt: skip
SERVER_KEYS = {"command", "health", "stopSeconds"}
CONTRIBUTION_KEYS = {"pages", "nav", "redirects", "slots", "into"}
PERMISSION_NAME = re.compile(r"[a-z][a-z0-9_-]{0,47}")
API_RANGE = re.compile(r"\^(0|[1-9]\d*)\.(0|[1-9]\d*)")
SHARED = {
    "react", "react/jsx-runtime", "react/jsx-dev-runtime", "react-dom", "react-dom/client",
    "react-router-dom", "react-router", "@blueprintjs/core", "echarts/core", "echarts/charts",
    "echarts/components", "echarts/renderers",
}  # fmt: skip
"""Elysium's shared libraries (``ui/packages/shell-api/src/sharedLibraries.ts``)."""


def bundle() -> str:
    entry: str = MANIFEST["entry"]
    return (FOLDER / entry).read_text()


def test_the_manifest_uses_only_keys_elysium_understands() -> None:
    assert set(MANIFEST) <= MANIFEST_KEYS
    assert {"id", "name", "version"} <= set(MANIFEST)
    assert set(MANIFEST["server"]) <= SERVER_KEYS
    assert set(MANIFEST["contributes"]) <= CONTRIBUTION_KEYS
    assert API_RANGE.fullmatch(MANIFEST["api"])


def test_the_module_is_the_one_the_engine_answers_as() -> None:
    assert MANIFEST["id"] == addon.MODULE


def test_the_permissions_are_declared_well_and_the_module_is_offered_to_one() -> None:
    declared = MANIFEST["permissions"]
    assert declared
    for item in declared:
        assert set(item) == {"id", "description"}
        assert PERMISSION_NAME.fullmatch(item["id"])
        assert item["description"].strip()
    names = [item["id"] for item in declared]
    assert len(set(names)) == len(names)
    assert {addon.USE, addon.OPERATE} <= set(names)  # what the engine's guard asks for
    assert MANIFEST["permission"] == f"module:{MANIFEST['id']}:{addon.USE}"


def test_each_rail_entry_leads_to_one_of_its_own_pages() -> None:
    pages = MANIFEST["contributes"]["pages"]
    paths = [page["path"] for page in pages]
    assert paths
    assert len(set(paths)) == len(paths)
    assert all(path.startswith("/heliograph") for path in paths)  # a path is the first claimer's
    nav = MANIFEST["contributes"]["nav"]
    assert nav
    assert all(entry["path"] in paths for entry in nav)


def test_the_server_command_is_the_engine_and_its_health_is_the_one_left_unsigned() -> None:
    server = MANIFEST["server"]
    assert server["command"] == ["heliograph", "serve"]
    assert server["health"] == addon.HEALTH


def test_elysiums_deadline_gives_the_engine_the_time_it_promises_to_stop_in() -> None:
    assert MANIFEST["server"]["stopSeconds"] > STOP_DEADLINE
    assert MANIFEST["server"]["stopSeconds"] <= 300


def test_the_bundle_and_its_styles_exist_beside_each_other() -> None:
    entry = FOLDER / MANIFEST["entry"]
    assert entry.is_file()
    assert MANIFEST["styles"]
    for style in MANIFEST["styles"]:
        assert (FOLDER / style).is_file()
        assert (FOLDER / style).parent == entry.parent  # the one directory Elysium serves


def test_the_bundle_imports_only_what_the_page_shares_or_the_module_api_names() -> None:
    imports = set(re.findall(r"""from\s+['"]([^'"]+)['"]""", bundle()))
    assert imports
    other = {i for i in imports if i not in SHARED}
    assert other <= {
        "@elysium/shell-api/api",
        "@elysium/shell-api/host",
        "@elysium/shell-api/components/Page",
    }


def test_the_bundle_gives_a_component_for_every_page_the_manifest_declares() -> None:
    source = bundle()
    assert re.search(r"export function activate\(", source)
    given = re.search(r"pages:\s*\{([^}]*)\}", source)
    assert given is not None
    ids = {part.split(":")[0].strip() for part in given.group(1).split(",") if part.strip()}
    assert ids == {page["id"] for page in MANIFEST["contributes"]["pages"]}


def test_every_rule_of_the_stylesheet_sits_in_the_components_layer() -> None:
    text = (FOLDER / MANIFEST["styles"][0]).read_text()
    css = re.sub(r"/\*.*?\*/", "", text, flags=re.S).strip()
    assert css.startswith("@layer components {")
    depth, closed = 0, -1
    for position, char in enumerate(css):
        depth += char == "{"
        depth -= char == "}"
        if depth == 0 and char == "}":
            closed = position
            break
    assert closed == len(css) - 1, "something follows the layer's closing brace"


def test_the_pages_calls_are_routes_the_engine_has() -> None:
    literals = re.findall(r"""['`](api/[^'`]*)['`]""", bundle())
    called = {"/" + re.sub(r"\$\{[^}]*\}", "{id}", literal) for literal in literals}
    clock = SimulatedClock(Timestamp(0))
    app = make_app(Settings(data=FOLDER), clock, Backtests(FOLDER / "unused", clock))
    served = {getattr(route, "path", "") for route in app.routes}
    assert called == {"/api/backtests", "/api/backtests/{id}/report"}
    assert called <= served
