"""
The UI's tokens, checked against DEV_UI.md.

WHY THIS EXISTS. DEV_UI.md was deleted in patch 99e721d after being
"consumed" into a BLOCKING item that kept its DIAGNOSIS and dropped its
ANSWERS. Three weeks later a session read the surviving item, found a
problem statement with no solution, and researched the same questions
from scratch -- producing a type scale wrong at every step, no typeface
where IBM Plex was specified, and a table density declared "measured
and fine" where three densities with a user preference were specified.

Nothing caught it, because nothing connected the stylesheet to the
decisions it was supposed to implement. This is that connection.

IT COMPARES, IT DOES NOT PRESCRIBE. If a token and the document
disagree, one of them is wrong and a person has to decide which. The
failure message says so rather than naming a winner -- a test that
silently assumed the document was right would make the document
unchangeable, and a design decision that cannot be revisited is as bad
as one that was never written down.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
DESIGN = (ROOT / "DEV_UI.md").read_text(encoding="utf-8")
TOKENS = (ROOT / "ui/packages/shell-api/src/tokens.css").read_text(encoding="utf-8")


def token(name: str) -> str | None:
    found = re.search(rf"--{re.escape(name)}:\s*([^;]+);", TOKENS)
    return found.group(1).strip() if found else None


class TestTheTypeScaleMatchesSection92:
    """9.2: a 1.2 scale on a 14px base, capped at 28px."""

    @pytest.mark.parametrize("step, size", [
        ("title", "28px"),
        ("section", "20px"),
        ("heading", "17px"),
        ("body", "14px"),
        ("dense", "13px"),
        ("label", "11px"),
    ])
    def test_each_step_is_the_documented_size(self, step, size):
        assert f"{size}" in DESIGN, f"DEV_UI.md 9.2 no longer lists {size}"
        assert token(f"type-{step}-size") == size, (
            f"--type-{step}-size is {token(f'type-{step}-size')}, "
            f"DEV_UI.md 9.2 says {size}. One of them is wrong.")

    def test_nothing_is_larger_than_the_cap(self):
        """"Capped deliberately: nothing above 28px. A tool that shows
        tables does not need display type, and every heading step costs
        rows." """
        sizes = [int(m) for m in re.findall(r"--type-\w+-size:\s*(\d+)px", TOKENS)]

        assert sizes, "no type sizes found at all"
        assert max(sizes) <= 28

    def test_a_label_is_semibold_and_small(self):
        assert token("type-label-weight") == "600"
        assert token("type-label-size") == "11px"


class TestTheTypefaceMatchesSection91:
    def test_plex_is_named_first(self):
        """"It separates 1 / l / I and 0 / O at 13px, which is the size
        our tables actually run at." """
        sans = token("font-sans") or ""
        mono = token("font-mono") or ""

        assert sans.lstrip().startswith("'IBM Plex Sans'"), sans[:60]
        assert "IBM Plex Mono" in mono, mono[:60]

    def test_no_font_is_fetched_from_a_network(self):
        """"A CDN font is an external dependency AND a privacy leak on
        every page load", on a product that runs inside customer
        infrastructure "sometimes with no outbound internet"."""
        css_files = list((ROOT / "ui").rglob("*.css"))
        css_files = [p for p in css_files if "node_modules" not in str(p)]

        assert css_files, "no stylesheets found -- the walk is broken"
        for path in css_files:
            text = path.read_text(encoding="utf-8")
            assert "fonts.googleapis.com" not in text, str(path)
            assert "@import url(http" not in text, str(path)


class TestTheSpacingScaleMatchesSection95:
    """9.5: "one 4px scale -- 4, 8, 12, 16, 24, 32, 48 -- used for
    padding, margin and gap alike. No value outside it; a 13px padding
    is not a decision, it is a slip." """

    def test_every_spacing_token_is_on_the_scale(self):
        allowed = {"4px", "8px", "12px", "16px", "24px", "32px", "48px"}
        declared = dict(re.findall(r"--(space-\w+):\s*([^;]+);", TOKENS))

        assert declared, "no spacing tokens found"
        for name, value in declared.items():
            assert value.strip() in allowed, f"--{name} is {value}"


class TestTheDocumentIsStillHere:
    def test_it_was_not_consumed_again(self):
        """The failure this whole file exists to prevent. If DEV_UI.md
        is deleted, every test above passes vacuously -- `DESIGN` would
        raise on read, so this is really a guard on the header's
        instruction rather than on the file's existence."""
        assert "RESTORED, AND NOT TO BE CONSUMED AGAIN" in DESIGN
        assert len(DESIGN.splitlines()) > 1_000
