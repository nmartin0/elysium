"""
No unit test reaches the developer's deployment -- reading or writing.

E-08. Thirty unit tests built on resolve_runtime_paths() and passed only
where a server had seeded that directory. Five more passed WITHOUT data
and wrote into it as they ran: credentials.db, triggers.db,
write_log.db, a mirror. A CI job on an unseeded checkout (E-09) catches
the first kind. Nothing behavioural catches the second: those tests
PASS.

So the calls are found where they are made. Each of these, called with
no arguments, falls back to the developer's own directories:
"""

import ast
from pathlib import Path

UNIT = Path(__file__).resolve().parent

FALLS_BACK = {"resolve_runtime_paths", "run_sync", "build_live_read_adapters"}


def _bare_calls(path: Path) -> list[str]:
    """Every call to one of FALLS_BACK with no arguments -- parsed, so a
    docstring or comment NAMING one (as this file's does) is not a call."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if not isinstance(node, ast.Call) or node.args or node.keywords:
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name in FALLS_BACK:
            found.append(f"{path.name}:{node.lineno} {name}()")
    return found


# THE ONE EXEMPTION, by name and for a reason: these test
# resolve_runtime_paths() ITSELF, and redirect all three ELYSIUM_*
# variables to a temporary directory before each call.
TESTS_THE_RESOLVER = {"test_deployment_loader.py"}


def test_no_unit_test_falls_back_to_the_developers_deployment():
    offenders = [
        call for path in sorted(UNIT.glob("*.py")) if path.name not in TESTS_THE_RESOLVER
        for call in _bare_calls(path)
    ]

    assert offenders == [], (
        "use the synced_deployment or private_deployment fixture "
        f"(tests/unit/conftest.py): {offenders}"
    )


def test_the_check_finds_a_bare_call(tmp_path):
    """THE CONTROL INSIDE THE TEST -- a check that finds nothing looks the
    same as one that cannot see."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        '"""resolve_runtime_paths() in prose is not a call."""\n'
        "paths = resolve_runtime_paths()\n"
        "run_sync.run_sync()\n"
        "fine = build_live_read_adapters(paths)\n"
    )

    assert _bare_calls(probe) == ["probe.py:2 resolve_runtime_paths()", "probe.py:3 run_sync()"]
