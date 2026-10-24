"""ui/MODULE_API.md, the module API's guide (BLOCKING.md item 3, step 4.3),
held to the code it describes.

A GUIDE DRIFTS where a generated report does not, which is why the owner
chose both: the report for signatures, the guide for the rest. This keeps
the guide's LISTS honest -- the manifest's keys, what it may contribute,
the activation events, what `activate` returns, the host values, the
shared libraries, the version -- against the places they are decided,
read from the source rather than remembered. Its prose is still a
person's to keep right; its inventories are not."""

import re
from pathlib import Path

from core.modules import _ACTIVATION_EVENTS, _CONTRIBUTION_KEYS, _MANIFEST_KEYS

ROOT = Path(__file__).resolve().parents[2]
GUIDE = (ROOT / "ui" / "MODULE_API.md").read_text()


def _section(heading: str) -> str:
    """The text under one heading, to the next heading of any depth: its
    own table, not its subsections' (the manifest's, not `contributes`)."""
    lines = GUIDE.split("\n")
    for at, line in enumerate(lines):
        level = len(line) - len(line.lstrip("#"))
        if level and line[level:].strip() == heading:
            body = []
            for following in lines[at + 1:]:
                deeper = len(following) - len(following.lstrip("#"))
                if deeper and following[deeper:deeper + 1] == " ":
                    break
                body.append(following)
            return "\n".join(body)
    raise AssertionError(f"the guide has no section {heading!r}")


def _table_keys(section: str) -> set[str]:
    """The first column of a section's table, where it is a `code` name."""
    return set(re.findall(r"^\| `([\w$-]+)` +\|", section, re.MULTILINE))


def _interface_fields(path: Path, interface: str) -> set[str]:
    body = re.search(rf"export interface {interface}\b[^{{]*\{{(.*?)\n\}}", path.read_text(), re.DOTALL)
    assert body is not None, f"{path.name} declares no {interface}"
    return set(re.findall(r"^\s+(\w+)\??:", body[1], re.MULTILINE))


def test_it_lists_every_manifest_key_and_no_other():
    assert _table_keys(_section("The manifest: `module.json`")) == set(_MANIFEST_KEYS)


def test_it_lists_everything_a_module_may_contribute():
    assert _table_keys(_section("`contributes`")) == set(_CONTRIBUTION_KEYS)


def test_it_lists_every_activation_event():
    assert _table_keys(_section("`activationEvents`")) == set(_ACTIVATION_EVENTS)


def test_it_lists_what_activate_may_return():
    shell = ROOT / "shell" / "core" / "src"
    returned = _interface_fields(shell / "activation.ts", "ModuleCode") \
        | _interface_fields(shell / "moduleLoader.tsx", "ModuleActivation")

    assert _table_keys(_section("The bundle: `activate()`")) == returned


def test_it_lists_every_host_value():
    host = ROOT / "ui" / "packages" / "shell-api" / "src" / "host.ts"

    assert _table_keys(_section("What the page gives a module: host values")) == _interface_fields(host, "HostValues")


def test_it_lists_every_shared_library():
    source = (ROOT / "ui" / "packages" / "shell-api" / "src" / "sharedLibraries.ts").read_text()
    shared = set()
    for name in ("SHARED_LIBRARIES", "SHARED_PACKAGES"):
        array = re.search(rf"export const {name} = \[(.*?)\]", source, re.DOTALL)
        assert array is not None, name
        # COMMENTS OUT FIRST: one says "the page's router", whose quote
        # would otherwise open a string.
        shared |= set(re.findall(r"'([^']+)'", re.sub(r"//[^\n]*", "", array[1])))

    listed = set(re.findall(r"`([@\w][\w@/.-]*)`", _section("Shared libraries")))

    assert shared and shared <= listed, f"the guide leaves out {sorted(shared - listed)}"


def test_it_says_the_version_the_page_offers():
    contract = (ROOT / "shell" / "core" / "src" / "contract.ts").read_text()
    offered = re.search(r"export const MODULE_API_VERSION = '([\d.]+)'", contract)
    assert offered is not None

    assert f"**Version {offered[1]}.**" in GUIDE
    assert f"**module API {offered[1]}**" in _section("The version")


def test_every_file_it_names_exists():
    named = set(re.findall(r"`((?:ui|shell|sdk|sim|tests|core|api)/[\w./-]+\.\w+)`", GUIDE))
    named |= {f"ui/{name}" for name in re.findall(r"\]\(([\w.-]+\.md)\)", GUIDE)}

    assert named, "the probe found no file names at all"
    assert sorted(name for name in named if not (ROOT / name).exists()) == []
