"""The wheel carries the built UI as elysium/ui_dist/ (marker: live)."""

import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.live
def test_wheel_contains_the_built_ui(tmp_path):
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path)], cwd=ROOT, check=True)

    (wheel,) = tmp_path.glob("elysium-*.whl")
    names = zipfile.ZipFile(wheel).namelist()
    assert "elysium/ui_dist/index.html" in names
    assert "elysium/api/app.py" in names
