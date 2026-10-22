"""
The page's import map is allowed by the Content-Security-Policy, by its
hash and nothing wider (api/app.py, import_map_script_src).

An import map is an inline script; Elysium's policy forbids inline
scripts, so without this the browser ignores the map and no module can
load. A browser test against the real server found it.
"""

import base64
import hashlib

from api.app import import_map_script_src

MAP = '{\n  "imports": {\n    "react": "/shared/react.js"\n  }\n}'


def _page(tmp_path, body: str):
    page = tmp_path / "index.html"
    page.write_text(f"<html><head><script type=\"importmap\">{body}</script>"
                    f"<script type=\"module\" src=\"/assets/index.js\"></script></head></html>")
    return page


def _hash(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def test_the_map_is_allowed_by_the_hash_of_its_exact_text(tmp_path):
    assert import_map_script_src(_page(tmp_path, MAP)) == f"; script-src 'self' {_hash(MAP)}"


def test_never_unsafe_inline(tmp_path):
    assert "unsafe-inline" not in import_map_script_src(_page(tmp_path, MAP))


def test_a_rebuilt_page_is_allowed_without_a_restart(tmp_path):
    """Static files are read per request; so is the hash."""
    page = _page(tmp_path, MAP)
    import_map_script_src(page)
    changed = MAP.replace("react.js", "react2.js") + "\n"
    _page(tmp_path, changed)

    assert _hash(changed) in import_map_script_src(page)


def test_no_page_built_means_no_script_src(tmp_path):
    """Nothing to allow; default-src 'self' still governs scripts."""
    assert import_map_script_src(tmp_path / "index.html") == ""


def test_a_page_without_a_map_adds_nothing(tmp_path):
    page = tmp_path / "index.html"
    page.write_text("<html><script type=\"module\" src=\"/a.js\"></script></html>")

    assert import_map_script_src(page) == ""
