"""The `elysium` command: a stub until the real command line lands.

docs/archive/planning-history.md section 8.4, "Converge on precedent", step S16 replaces the scripts with
`elysium <group> <verb>`. Until then this prints its help and lists the
scripts that exist, each run as `python -m elysium.scripts.<name>`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HELP = """usage: elysium [--help]

The command line is not built yet. The operator scripts are run as
`python -m elysium.scripts.<name>`; the ones that exist are listed below.
"""


def script_names() -> list[str]:
    """The modules under elysium/scripts, by name, sorted."""
    folder = Path(__file__).resolve().parent / "scripts"
    return sorted(p.stem for p in folder.glob("*.py") if p.stem != "__init__")


def main(argv: list[str] | None = None) -> int:
    """Print the help and the scripts that exist; exit 0 for --help, 2 otherwise."""
    args = sys.argv[1:] if argv is None else argv
    print(_HELP)
    for name in script_names():
        print(f"  python -m elysium.scripts.{name}")
    return 0 if not args or args == ["--help"] or args == ["-h"] else 2


if __name__ == "__main__":
    sys.exit(main())
