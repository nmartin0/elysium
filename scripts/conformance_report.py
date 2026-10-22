"""
conformance_report.py -- what every module is excused from, and why.

    python -m scripts.conformance_report

BLOCKING.md item 3: every module is held to the conformance suite
(ui/packages/testing/src/conformance.tsx) unless its
module.conformance.json says otherwise, with a reason. Those files are
DATA so that this can list them all without running a test: one place
to see how far each module is from the default, and the reasons, which
are what a reviewer weighs.

A `todo` here is a known failure the module has committed to fixing --
the suite fails it once it passes, so this list only shrinks. A
`replaced` names the module's own stronger test. An `off` is a check
that does not apply, and its reason should say why not.

Exits 1 if a shipped module with a bundle has no conformance test at
all, which is the one thing a report alone should refuse.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    from core.modules import SHIPPED_MODULES

    unheld: list[str] = []
    for folder in SHIPPED_MODULES:
        manifest = json.loads((ROOT / folder / "module.json").read_text())
        if not manifest.get("entry"):
            print(f"{manifest['id']:16} built into the page; held by the page's own tests")
            continue
        callers = [p for p in (ROOT / folder / "src").rglob("*.test.ts*") if "describeModule(" in p.read_text()]
        if not callers:
            unheld.append(manifest["id"])
            print(f"{manifest['id']:16} NO CONFORMANCE TEST")
            continue
        path = ROOT / folder / "module.conformance.json"
        checks = json.loads(path.read_text()).get("checks", {}) if path.is_file() else {}
        print(f"{manifest['id']:16} held to every check" + (f", except {len(checks)}:" if checks else ""))
        for key, override in sorted(checks.items()):
            by = f" (by {override['by']})" if override.get("by") else ""
            print(f"    {key:28} {override['level']:9} {override['reason']}{by}")
    if unheld:
        print(f"\nNot held to the suite: {', '.join(unheld)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
