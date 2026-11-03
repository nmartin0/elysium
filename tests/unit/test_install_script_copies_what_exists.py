"""
install/install.sh copies only what exists, and everything the server imports.

It named a `tools/` directory that does not exist, under `set -e`, so a
fresh install stopped at step 3; and it never copied `functions/`,
which core/functions/registry.py imports, so an install that got past
that would have started a server that could not import.

It also installed without the lockfiles. INSTALL.md says
`pip install --require-hashes -r requirements.lock`, and AGENTS.md says
`npm ci`, never `npm install`.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
INSTALLER = (ROOT / "install" / "install.sh").read_text()


def _cp_sources():
    """Every `$SOURCE_DIR/...` argument of every cp command (continuations joined)."""
    joined = INSTALLER.replace("\\\n", " ")
    sources = []
    for line in joined.splitlines():
        line = line.strip()
        if not line.startswith(("cp ", "cp\t")):
            continue
        for argument in re.findall(r'"\$SOURCE_DIR/([^"]*)"', line):
            sources.append(argument)
    return sources


def test_the_parser_finds_the_copies():
    # Its own control: a parser that found nothing would make the
    # existence check below pass for ever.
    sources = _cp_sources()
    assert "src" in sources


def test_every_path_the_installer_copies_exists_in_the_repository():
    missing = [s for s in _cp_sources() if not (ROOT / s.rstrip("/.")).exists()]
    assert not missing, f"install.sh copies paths that do not exist: {missing}"


def test_every_top_level_package_the_server_imports_is_copied():
    copied = {s.split("/")[0] for s in _cp_sources()}
    repo_packages = {p.name for p in ROOT.iterdir()
                     if p.is_dir() and (p / "__init__.py").exists()}
    repo_packages |= {p.name for p in (ROOT / "src").iterdir() if (p / "__init__.py").exists()}
    imported = set()
    for folder in ("api", "core", "adapters", "functions"):
        for path in (ROOT / "src" / "elysium" / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    imported |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    imported.add(node.module.split(".")[0])
    needed = imported & repo_packages
    assert "elysium" in needed
    # `elysium` is the one package under src/, so copying src/ copies it.
    assert "src" in copied, f"imported by the server but not copied: {sorted(needed)}"


def test_python_dependencies_come_from_the_hashed_lock_when_there_is_one():
    assert (ROOT / "requirements.lock").exists()
    assert 'cp "$SOURCE_DIR/requirements.lock"' in INSTALLER
    assert '--require-hashes -r "$OPT_DIR/requirements.lock"' in INSTALLER


def test_the_ui_is_installed_with_npm_ci_and_never_npm_install():
    assert "npm ci" in INSTALLER
    assert not re.search(r"^[^#\n]*npm install", INSTALLER, re.M)
