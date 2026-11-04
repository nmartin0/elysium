"""The precedent's vendor and products are named nowhere (N62).

The names are not in this file either: tools/name_guard.py compares hashes of
words and word pairs, so a planted word here is a dummy the test registers.
"""

import hashlib
import re
import subprocess
from pathlib import Path

import name_guard as guard
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def digest(word: str) -> str:
    return hashlib.sha256(word.encode()).hexdigest()


@pytest.fixture
def planted(monkeypatch):
    """Register a harmless word as forbidden, so the guard can be shown to catch it."""
    monkeypatch.setattr(guard, "FORBIDDEN", guard.FORBIDDEN | {digest("planted"), digest("two words")})
    return "planted"


def test_no_tracked_file_or_path_names_the_vendor_or_its_products():
    hits = guard.unlisted(guard.scan(guard.tracked_paths(), from_index=False), guard.read_baseline())

    assert not hits, "\n".join(f"{h.path}:{h.line}" for h in hits)


def test_a_planted_word_in_a_file_is_found(planted):
    hits = guard.check_text("fine\nsome Planted text\n", "docs/x.md")

    assert [(h.line, h.digest) for h in hits] == [(2, digest("planted"))]


def test_a_planted_word_inside_an_identifier_is_found(planted):
    assert guard.check_text("class PlantedClient:\n    pass\n", "src/x.py")
    assert guard.check_text("def get_planted_thing(): pass\n", "src/x.py")


def test_a_planted_pair_is_found(planted):
    assert guard.check_text("these Two other Words", "docs/x.md") == []
    assert guard.check_text("these Two Words are one pair", "docs/x.md")


def test_a_planted_word_in_a_path_is_found(planted):
    assert guard.check_path("docs/planted-notes.md")
    assert not guard.check_path("docs/notes.md")


def test_a_planted_word_in_a_message_is_found(planted):
    assert guard.check_text("Fix the planted thing\n")


def test_the_hit_is_found_in_a_real_file(planted, tmp_path):
    (tmp_path / "x.txt").write_text("a planted word\n")

    assert guard.check_text((tmp_path / "x.txt").read_text(), "x.txt")


def test_the_list_holds_hashes_only():
    assert len(guard.FORBIDDEN) >= 5
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in guard.FORBIDDEN)


def test_allowlist_has_one_entry():
    assert len(guard.ALLOWED) == 1
    ((scope, places),) = guard.ALLOWED.items()
    assert scope in guard.FORBIDDEN
    assert places == ("ui/package.json", "ui/package-lock.json", "import:ui/**", "import:shell/**")


class TestTheAllowedScope:
    @pytest.fixture(autouse=True)
    def scope(self, monkeypatch):
        """The toolkit scope, with a dummy word standing in for it."""
        entry = digest("scopeword")
        monkeypatch.setattr(guard, "FORBIDDEN", guard.FORBIDDEN | {entry})
        monkeypatch.setattr(guard, "ALLOWED", {entry: ("ui/package.json", "import:ui/**", "import:shell/**")})

    def test_it_passes_in_the_package_file(self):
        assert not guard.check_text('  "scopeword/core": "^1"', "ui/package.json")

    def test_it_fails_in_another_package_file(self):
        assert guard.check_text('  "scopeword/core": "^1"', "shell/package.json")

    @pytest.mark.parametrize("line", [
        "import { Button } from 'scopeword/core'",
        "import 'scopeword/core/lib/css/x.css'",
        "export { Button } from 'scopeword/core'",
        "} from 'scopeword/core'",
    ])
    def test_it_passes_on_an_import_line_under_ui_and_shell(self, line):
        assert not guard.check_text(line, "ui/src/a.tsx")
        assert not guard.check_text(line, "shell/core/src/a.ts")

    def test_it_fails_on_a_comment_in_a_source_file(self):
        assert guard.check_text("// built on scopeword/core", "ui/src/a.tsx")

    def test_it_fails_on_an_import_line_outside_ui_and_shell(self):
        assert guard.check_text("import { Button } from 'scopeword/core'", "sim/panel/web/src/a.tsx")

    def test_it_fails_on_an_import_line_in_a_python_file(self):
        assert guard.check_text("import scopeword", "ui/x.py")

    def test_it_fails_in_a_document(self):
        assert guard.check_text("uses scopeword/core", "docs/ui/notes.md")

    def test_it_fails_in_a_message(self):
        assert guard.check_text("import { x } from 'scopeword/core'")


def test_the_baseline_is_only_allowed_scope_lines(monkeypatch, tmp_path):
    entry = digest("scopeword")
    monkeypatch.setattr(guard, "FORBIDDEN", guard.FORBIDDEN | {entry, digest("planted")})
    monkeypatch.setattr(guard, "ALLOWED", {entry: ()})
    scope_hit = guard.Hit("docs/a.md", 1, "scopeword here", entry)
    other_hit = guard.Hit("docs/a.md", 2, "planted here", digest("planted"))
    baseline = {scope_hit.key: 1, other_hit.key: 1}
    from collections import Counter

    assert guard.unlisted([scope_hit, other_hit], Counter(baseline)) == [other_hit]
    assert guard.unlisted([scope_hit, scope_hit], Counter(baseline)) == [scope_hit]


def test_the_two_files_named_after_the_toolkit_are_renamed():
    assert (ROOT / "ui/src/toolkit-smoke.test.tsx").exists()
    assert (ROOT / "ui/src/toolkitSurface.test.ts").exists()


def test_a_forbidden_word_in_a_staged_file_is_refused(planted, monkeypatch, tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607 -- fixed command
    (tmp_path / "a.md").write_text("a planted word\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.md"], check=True)  # noqa: S603, S607 -- fixed command
    monkeypatch.setattr(guard, "ROOT", tmp_path)

    hits = guard.scan(guard.staged_paths(), from_index=True)

    assert [h.path for h in hits] == ["a.md"]
