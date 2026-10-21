"""
A sub-app is declared in five places. They must agree.

    ui/packages/app-*/            the package exists on disk
    ui/package.json               the shell DEPENDS on it
    module.json                   its pages and rail entries, which the
                                  module feed serves (core/modules.py)
    ui/src/App.tsx                BUILT_IN_PAGES: the code for each page
    appIcons.ts                   an icon for its rail path

THE MODULES ARE THE ONES ELYSIUM SHIPS (core/modules.SHIPPED_MODULES):
a deployment's modules.yaml may drop some, and a module from outside
brings its own code, so only the shipped set can be checked against
this page's code.

THE SAME CLASS AS test_step_vocabulary_consistency.py and
test_filter_vocabulary_consistency.py: a vocabulary spread across
files, each side individually correct, nothing asserting they describe
the same thing.

THIS ONE HAS A DEMONSTRATED FAILURE BEHIND IT. Adding the approvals
sub-app, every check passed and the site rendered a blank white page.
The workspaces glob picked the package up, so Vite resolved it at build
time and vitest resolved it in tests -- but ui/package.json's
dependencies list is explicit and had not been updated, so a real
`npm install` created no symlink and the lazy import resolved to
nothing at runtime.

A blank page, because a failed lazy import rejects during render and
React unmounts the tree. Nothing in the suite could see it: the build
succeeded, the tests passed, and only an install produced the
node_modules the browser actually loads.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "ui"


def _packages_on_disk() -> set[str]:
    return {path.name.removeprefix("app-") for path in (UI / "packages").glob("app-*")}


def _shell_dependencies() -> set[str]:
    manifest = json.loads((UI / "package.json").read_text())
    return {
        name.removeprefix("@elysium/app-")
        for name in manifest.get("dependencies", {})
        if name.startswith("@elysium/app-")
    }


def _manifests() -> list[dict]:
    from core.modules import SHIPPED_MODULES
    return [json.loads((ROOT / folder / "module.json").read_text()) for folder in SHIPPED_MODULES]


def _manifest_pages() -> set[str]:
    """Every page the shipped modules contribute, as `module:page`."""
    return {f"{m['id']}:{page['id']}" for m in _manifests() for page in m["contributes"].get("pages", [])}


def _resolved_pages() -> set[str]:
    """The `module:page` keys App.tsx has code for (BUILT_IN_PAGES)."""
    source = (UI / "src" / "App.tsx").read_text()
    table = source[source.index("const BUILT_IN_PAGES"):]
    table = table[:table.index("}")]
    return set(re.findall(r"'([a-z-]+:[a-z-]+)':", table))


def _rail_paths() -> set[str]:
    return {entry["path"].removeprefix("/") for m in _manifests() for entry in m["contributes"].get("nav", [])}


def _iconed_paths() -> set[str]:
    # [a-z-]+ rather than [a-z]+ throughout: a path may contain a
    # hyphen, and the narrower pattern made such a path INVISIBLE to
    # these checks rather than absent from them. Found by a control
    # that should have failed and did not.
    source = (UI / "packages" / "shell-api" / "src" / "appIcons.ts").read_text()
    return set(re.findall(r"'/([a-z-]+)':", source))


def test_every_package_is_a_shell_dependency():
    """THE ONE THAT WOULD HAVE CAUGHT THE WHITE SCREEN.

    The workspaces glob is `packages/*`, so a new package is picked up
    for the build and for tests whether or not anything depends on it.
    Only a real install needs the explicit dependency, and only a
    browser loads the result.
    """
    missing = _packages_on_disk() - _shell_dependencies()

    assert not missing, (
        f"{sorted(missing)} exist as packages and are not in ui/package.json's "
        f"dependencies. The build and the tests will pass; a real npm install "
        f"will create no symlink and the lazy import will resolve to nothing, "
        f"rendering a blank page."
    )


def test_every_shell_dependency_exists_on_disk():
    # The reverse: a dependency on a package that was renamed or
    # removed fails at install rather than at runtime, which is louder
    # -- but it fails for everyone, so it is worth catching here.
    missing = _shell_dependencies() - _packages_on_disk()

    assert not missing, f"ui/package.json depends on {sorted(missing)}, which do not exist"


def test_every_shipped_page_has_code():
    """A rail entry opening "nothing loaded opens this page".

    The manifests decide what the sidebar OFFERS and where each page is
    mounted. A page there with no entry in App.tsx's BUILT_IN_PAGES
    mounts the shell's "nothing opens this" in place of the sub-app --
    for a shipped module, a broken install that looks like a missing one.
    """
    missing = _manifest_pages() - _resolved_pages()

    assert not missing, f"the modules contribute {sorted(missing)}, which App.tsx has no code for"


def test_no_page_code_is_left_for_a_page_no_module_contributes():
    # The reverse: code kept for a page whose manifest entry was renamed
    # or removed is dead, and says the table was not kept with them.
    orphaned = _resolved_pages() - _manifest_pages()

    assert not orphaned, f"App.tsx has code for {sorted(orphaned)}, which no module contributes"


def test_every_rail_entry_has_an_icon():
    # appIcons.ts maps path to icon. A missing entry is cosmetic rather
    # than broken, which is exactly why it would survive review.
    missing = _rail_paths() - _iconed_paths()

    assert not missing, f"the rail offers {sorted(missing)} with no icon declared"


def test_no_icon_is_declared_for_a_path_the_rail_never_offers():
    # THE CONTROL, and a real sign of drift: an icon left behind after
    # a sub-app was renamed or removed says the map was not maintained
    # with the list.
    orphaned = _iconed_paths() - _rail_paths()

    assert not orphaned, f"appIcons.ts declares {sorted(orphaned)}, which the rail never offers"


@pytest.mark.parametrize("name", sorted(_packages_on_disk()))
def test_each_package_exports_what_the_shell_imports(name):
    """A subpath the shell imports must be in the package's exports map.

    Node refuses an unlisted subpath outright, so this fails loudly at
    build rather than silently -- but it cost a round when LoadingState
    was added, and the failure names a module rather than a mistake.
    """
    manifest = json.loads((UI / "packages" / f"app-{name}" / "package.json").read_text())
    exported = set(manifest.get("exports", {}))

    # App.tsx AND InboxPanel.tsx: the three inbox panels are lazy-loaded
    # by the Inbox, one per tab (14 Oct), so reading App.tsx alone would
    # check nothing about them.
    shell = "\n".join((UI / "src" / name_).read_text() for name_ in ("App.tsx", "InboxPanel.tsx"))
    imported = set(re.findall(rf"from '@elysium/app-{name}/([A-Za-z]+)'", shell))
    imported |= set(re.findall(rf"import\('@elysium/app-{name}/([A-Za-z]+)'\)", shell))

    missing = {f"./{entry}" for entry in imported} - exported

    assert not missing, f"App.tsx imports {sorted(missing)} from app-{name}, which does not export it"
