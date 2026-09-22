"""
Production never relies on AuditLog's default -- and the default is
never the developer's audit trail.

E-08b. A bare AuditLog() wrote to deployment/var/log/audit.log, and the
DataMediator and PendingWriteStore built by unit tests defaulted one,
so the unit suite wrote into the developer's own audit trail. The
default is now a private temporary file per instance. That is right for
a test and would be wrong for a deployment -- an audit trail silently
kept in /tmp and deleted at exit -- so production must always pass one.
"""

import ast
from pathlib import Path

from core.intermediate_layer.audit import AuditLog

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = ("core", "api", "scripts", "adapters")

# The keyword each constructor takes its audit log (or path) by.
NEEDS = {"DataMediator": "audit_log", "PendingWriteStore": "audit_log", "AuditLog": "log_path"}


# THE TWO FALLBACKS THEMSELVES -- `audit_log if ... else AuditLog()` in
# the constructors whose default this is. They are what the rest of this
# file protects, not callers relying on them.
THE_FALLBACKS = {"core/ontology/mediator.py", "core/pending_write_store.py"}


def _relying_on_the_default(path: Path, root: Path = ROOT) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        keyword = NEEDS.get(name or "")
        if keyword is None:
            continue
        # AuditLog takes its path first, positionally, everywhere it is built.
        passed = any(k.arg == keyword for k in node.keywords) or (name == "AuditLog" and bool(node.args))
        if not passed:
            found.append(f"{path.relative_to(root)}:{node.lineno} {name}(...) without {keyword}")
    return found


def test_every_production_construction_passes_one():
    offenders = [
        call for package in PRODUCTION for path in sorted((ROOT / package).rglob("*.py"))
        if str(path.relative_to(ROOT)) not in THE_FALLBACKS
        for call in _relying_on_the_default(path)
    ]

    assert offenders == [], offenders


def test_the_fallbacks_are_the_only_bare_ones():
    """THE EXEMPTION, KEPT HONEST: each exempt file holds exactly one bare
    AuditLog() -- its fallback -- and nothing else relying on a default."""
    for name in sorted(THE_FALLBACKS):
        found = _relying_on_the_default(ROOT / name)
        assert len(found) == 1 and "AuditLog(...)" in found[0], (name, found)


def test_the_check_can_see_one(tmp_path):
    """THE CONTROL INSIDE THE TEST -- a check that finds nothing looks the
    same as one that cannot see."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "a = DataMediator(schema, adapters)\n"
        "b = DataMediator(schema, adapters, audit_log=log)\n"
        "c = AuditLog()\n"
        "d = AuditLog(log_dir / 'audit.log')\n"
        "e = PendingWriteStore(ttl=t)\n"
    )

    found = [entry.split(" ")[1] for entry in _relying_on_the_default(probe, tmp_path)]

    assert found == ["DataMediator(...)", "AuditLog(...)", "PendingWriteStore(...)"]


class TestTheDefault:
    def test_is_never_the_repositorys(self):
        path = Path(AuditLog()._log_path).resolve()

        assert ROOT not in path.parents

    def test_is_never_another_instances(self):
        """A test counting entries in its log sees only its own."""
        assert AuditLog()._log_path != AuditLog()._log_path
