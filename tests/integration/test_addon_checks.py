"""The add-on contract checks (sdk/python/elysium_addon_checks.py), which
an add-on runs against its own server in its own repository (BLOCKING.md
item 3, step 2): the example add-on keeps the contract, and -- THE SUITE
TESTED ITSELF, as the design asks -- each check fails an add-on broken
in the one way it checks for, so none of them can pass everything."""

import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / "sdk" / "python"
ECHO = ROOT / "tests" / "addons" / "echo"
sys.path.insert(0, str(SDK))

from elysium_addon_checks import AddonContract  # noqa: E402


class TestTheExampleAddonKeepsTheContract(AddonContract):
    manifest = ECHO / "module.json"
    protected = ["/whoami"]


CHECKS = {
    "health": "test_health_answers_200_once_started",
    "identity": "test_a_protected_path_refuses_who_it_cannot_verify_and_takes_who_it_can",
    "loopback": "test_it_listens_on_loopback_only",
    "stop": "test_sigterm_ends_it_within_its_deadline_cleanly",
    "stdin": "test_it_leaves_when_elysium_does",
}


def _outcomes(tmp_path: Path, options: dict) -> dict[str, str]:
    """Each check's outcome against the example add-on given `options`,
    run as an add-on's own repository would run them."""
    test = tmp_path / "test_contract.py"
    test.write_text(textwrap.dedent(f"""
        import sys
        from pathlib import Path
        sys.path.insert(0, {str(SDK)!r})
        from elysium_addon_checks import AddonContract

        class TestBroken(AddonContract):
            manifest = Path({str(ECHO / "module.json")!r})
            protected = ["/whoami"]
            options = {options!r}
            # Short, for a server that never gets healthy: five checks wait.
            start_seconds = 5
    """))
    report = tmp_path / "report.xml"
    subprocess.run([sys.executable, "-m", "pytest", str(test), "-q", "-p", "no:cacheprovider",
                    f"--junitxml={report}", f"--rootdir={tmp_path}", "-c", "/dev/null"],
                   cwd=tmp_path, capture_output=True, text=True, timeout=300)
    outcomes = {}
    for case in ElementTree.parse(report).getroot().iter("testcase"):
        children = {child.tag for child in case}
        outcomes[case.get("name")] = ("failed" if children & {"failure", "error"}
                                      else "skipped" if "skipped" in children else "passed")
    return outcomes


@pytest.mark.parametrize("check, options", [
    ("health", {"health": "never"}),
    ("identity", {"trust_anyone": True}),
    ("identity", {"refuse_all": True}),       # the good-token half: refusing everybody is not keeping it
    ("loopback", {"bind_all": True}),
    ("stop", {"ignore_term": True}),          # still running at the deadline
    ("stop", {"exit_status": 1}),             # ended, but not cleanly
    ("stdin", {"ignore_term": True}),         # ignores its standard input closing too
])
def test_each_check_fails_an_addon_broken_the_way_it_checks_for(tmp_path, check, options):
    outcomes = _outcomes(tmp_path, options)

    if check == "loopback" and outcomes[CHECKS[check]] == "skipped":
        pytest.skip("this machine has no address but loopback, so the loopback check cannot run here")
    assert outcomes[CHECKS[check]] == "failed", outcomes


def test_the_unbroken_addon_passes_every_check_the_same_way(tmp_path):
    # THE SAME RUNNER as the broken ones, so a failure above is the break.
    outcomes = _outcomes(tmp_path, {})

    assert {name: outcome for name, outcome in outcomes.items() if outcome == "failed"} == {}
    assert set(outcomes) == set(CHECKS.values())
