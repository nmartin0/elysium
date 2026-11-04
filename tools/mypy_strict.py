#!/usr/bin/env python3
"""mypy_strict.py -- legacy modules made strict, a list that only grows.

New packages are strict from their first commit through the module globs
in pyproject.toml. The older `elysium.core.*` and `elysium.api.*` (v1)
modules are strict one by one: quality/strict-modules.txt lists them, and
the generated block of pyproject.toml gives them the same options.

    mypy_strict.py --write    add every legacy module that is clean under the
                              strict options to the list; rewrite the block
    mypy_strict.py --check    exit 1 when the block is not the list, or a
                              listed module is not clean any more

A card never edits the list: the check tells it which module it broke.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
LIST = ROOT / "quality" / "strict-modules.txt"
BEGIN = "# BEGIN GENERATED strict modules (tools/mypy_strict.py --write)\n"
END = "# END GENERATED strict modules\n"
LEGACY_DIRS = ("src/elysium/core", "src/elysium/api")
#: What `mypy --strict` turns on that a module section may carry (the options of
#: the glob block in pyproject.toml; a test holds the two together).
STRICT_OPTIONS = (
    "disallow_any_generics", "disallow_untyped_calls", "disallow_untyped_defs",
    "disallow_incomplete_defs", "check_untyped_defs", "warn_unused_ignores",
    "warn_return_any", "no_implicit_reexport", "strict_equality", "extra_checks",
)
HEADER = "# Modules made strict. This list only grows (tools/mypy_strict.py --write).\n"


def module_of(path: str) -> str:
    dotted = re.sub(r"\.py$", "", path[len("src/"):]).replace("/", ".")
    return dotted[: -len(".__init__")] if dotted.endswith(".__init__") else dotted


def legacy_modules() -> dict[str, str]:
    found = {}
    for directory in LEGACY_DIRS:
        for file in sorted((ROOT / directory).rglob("*.py")):
            relative = str(file.relative_to(ROOT))
            module = module_of(relative)
            if not module.startswith("elysium.api.v2"):  # strict already, by glob
                found[module] = relative
    return found


def listed() -> list[str]:
    if not LIST.exists():
        return []
    return [line.strip() for line in LIST.read_text().splitlines()
            if line.strip() and not line.startswith("#")]


def block(modules: list[str]) -> str:
    options = "".join(f"{name} = true\n" for name in STRICT_OPTIONS)
    if not modules:
        return ""
    names = ",\n".join(f'          "{m}"' for m in modules)
    return f"[[tool.mypy.overrides]]\nmodule = [\n{names},\n]\n{options}"


def _split(text: str) -> tuple[str, str, str]:
    start = text.index(BEGIN) + len(BEGIN)
    return text[:start], text[start:text.index(END)], text[text.index(END):]


def errors_with(modules: list[str], config_text: str) -> set[str]:
    """Files of `modules` with mypy errors under `config_text` (a pyproject copy)."""
    paths = legacy_modules()
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / "pyproject.toml"
        config.write_text(config_text)
        result = subprocess.run(  # noqa: S603, S607 -- fixed argument list, no shell
            ["mypy", "--config-file", str(config), "--no-error-summary", "--show-error-codes",  # noqa: S607 -- fixed command
             *[paths[m] for m in modules]],
            capture_output=True, text=True, check=False, cwd=ROOT)
    bad = {line.split(":", 1)[0] for line in result.stdout.splitlines() if ": error:" in line}
    return {m for m in modules if paths[m] in bad}


def _strict_everywhere(text: str) -> str:
    """The config with the strict options global, to find modules clean under them."""
    head, _, tail = _split(text)
    return (head + tail).replace("[tool.mypy]\n", "[tool.mypy]\n" + "".join(
        f"{name} = true\n" for name in STRICT_OPTIONS), 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    text = PYPROJECT.read_text()
    known = listed()
    if args.write:
        candidates = sorted(set(legacy_modules()) | set(known))
        clean = [m for m in candidates if m in set(known)
                 or m not in errors_with(candidates, _strict_everywhere(text))]
        head, _, tail = _split(text)
        modules = sorted(set(clean) | set(known))
        LIST.parent.mkdir(exist_ok=True)
        LIST.write_text(HEADER + "".join(m + "\n" for m in modules))
        PYPROJECT.write_text(head + block(modules) + tail)
        print(f"{len(modules)} strict module(s), {len(modules) - len(known)} added")
        return 0

    problems = []
    _, current, _ = _split(text)
    if current != block(known):
        problems.append("the generated block in pyproject.toml is not quality/strict-modules.txt; "
                        "run tools/mypy_strict.py --write")
    if known:
        for module in sorted(errors_with(known, text)):
            problems.append(f"{module} is on the strict list and has mypy errors")
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
