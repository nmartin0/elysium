"""
check_lockfiles.py  (lint.sh -- lock files match their requirements)

A lock file that has drifted from the requirements it was generated
from is worse than no lock file: it reads as a guarantee and is not
one. This is the check that keeps "regenerate when requirements
change" from being a habit nobody remembers.

Deliberately checks the DIRECT dependencies only, not the whole
resolved tree. Re-resolving here would need network access and would
turn a lint run into a package download; comparing what
requirements.txt declares against what the lock actually pins catches
the failure that occurs in practice -- a dependency added, removed or
re-bounded without regenerating.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAIRS = (
    (("requirements.txt",), "requirements.lock"),
    (("requirements.txt", "requirements-dev.txt"), "requirements-dev.lock"),
)


def _normalised(name: str) -> str:
    """PEP 503's normal form: runs of "-", "_" and "." are one "-".

    THE DOT WAS MISSED. The first rule here folded "_" only, which was
    enough until a name with a dot arrived: requirements.txt says
    `ruamel.yaml` and uv writes `ruamel-yaml==`, the same package, and
    the check reported it unpinned in a lock that pinned it."""
    return re.sub(r"[-_.]+", "-", name).lower()


def declared_names(paths: tuple[str, ...]) -> set[str]:
    names = set()
    for path in paths:
        for line in (ROOT / path).read_text().splitlines():
            line = line.split("#")[0].strip()
            if not line:
                continue
            # Strip extras and any version specifier: "pyiceberg[a,b]<1.0"
            # and "starlette>=1.0.1,<2.0" are both just their name here.
            name = re.split(r"[<>=!\[]", line)[0].strip()
            if name:
                names.add(_normalised(name))
    return names


def locked_names(path: str) -> set[str]:
    names = set()
    for line in (ROOT / path).read_text().splitlines():
        match = re.match(r"^([a-zA-Z0-9_.-]+)==", line)
        if match:
            names.add(_normalised(match.group(1)))
    return names


def main() -> int:
    failed = False
    for sources, lock in PAIRS:
        if not (ROOT / lock).exists():
            print(f"{lock} is missing -- regenerate it (see its own header).")
            failed = True
            continue
        declared = declared_names(sources)
        locked = locked_names(lock)
        missing = declared - locked
        if missing:
            print(
                f"{lock} does not pin {sorted(missing)}, declared in "
                f"{' + '.join(sources)}. Regenerate it (see its own header)."
            )
            failed = True
    if not failed:
        print("Lock files match their requirements.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
