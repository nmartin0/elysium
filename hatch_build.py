"""Build hook: build the web UI so the wheel can carry it as elysium/ui_dist."""

import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class UiBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        if version == "editable":
            return
        root = Path(self.root)
        for directory in ("shell", "ui"):
            subprocess.run(["npm", "ci"], cwd=root / directory, check=True)  # noqa: S603, S607 -- fixed command
        subprocess.run(["npm", "run", "build"], cwd=root / "ui", check=True)  # noqa: S603, S607 -- fixed command
        if not (root / "ui" / "dist" / "index.html").is_file():
            raise RuntimeError("the UI build produced no ui/dist/index.html")
