"""
The README, checked against the system it describes.

IT SAID CROSS-SILO LINKS WERE NOT SUPPORTED long after core/mirror/
fusion.py was assembling one object type from several storages -- and
the claim sat in a "Known limitations, honestly" section, which is the
worst possible place for a stale line. The owner found it, not the
suite.

A limitations section is the part of a README nobody rereads and
everybody trusts. These tests make the specific claims falsifiable:
each one either names something that exists in the code, or denies
something that does not.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")

# LINE BREAKS ARE NOT MEANING. The README is hard-wrapped at 72
# columns, so "never gets direct database access" is split across two
# lines and a substring check for it finds nothing. Collapsing the
# whitespace is the difference between testing the prose and testing
# the wrapping.
FLAT = " ".join(README.split())


class TestWhatItClaimsExists:
    @pytest.mark.parametrize("claim, module", [
        ("bronze", "core/mirror/iceberg_sync.py"),
        ("silver", "core/mirror/transform.py"),
        ("gold", "core/mirror/gold.py"),
        ("fusion.py", "core/mirror/fusion.py"),
    ])
    def test_the_pipeline_stages_it_names_are_real(self, claim, module):
        assert claim in README, claim
        assert (ROOT / module).exists(), module

    def test_every_ui_package_in_the_table_exists(self):
        packages = [p.name for p in (ROOT / "ui/packages").iterdir() if p.is_dir()]

        for package in packages:
            assert f"`{package}`" in README, f"{package} is not in the README's table"

    def test_the_counts_are_not_wildly_stale(self):
        """Not exact -- the suite grows every patch -- but a figure that
        has drifted into fiction fails."""
        import re

        unit = len(list((ROOT / "tests/unit").glob("test_*.py")))
        claimed = int(re.search(r"\| unit \| [^|]+\| (\d+) files", README).group(1))

        assert abs(claimed - unit) <= 25, f"README says {claimed} unit files, there are {unit}"


class TestWhatItClaimsIsMissing:
    """The dangerous half. A limitation that has been fixed is a lie
    the reader has no reason to doubt."""

    def test_it_does_not_still_deny_cross_silo_links(self):
        """THE ONE THAT SURVIVED. fusion.py's own docstring: a Customer
        spanning primary_sql.customers and risk_db.risk_scores "is a
        JOIN: every property has one authoritative home"."""
        # THE ACTIVE LIST ONLY. The README now quotes the retracted
        # line under "What this list used to say, and no longer does",
        # which is deliberate -- a limitations section that silently
        # drops a claim teaches nobody anything. A test that searched
        # the whole section could not tell a retraction from the
        # original.
        section = README[README.index("## 7. Known limitations"):]
        active = section[:section.index("### What this list used to say")]

        assert "cross-silo" not in " ".join(active.split()).lower()

    def test_the_memory_limitation_is_still_true(self):
        """It claims core/memory/ exists but is not consulted by the
        agent loop. If the loop starts importing it, this line has to
        go."""
        loop = (ROOT / "core/agent/agentic_loop.py").read_text(encoding="utf-8")
        imports_memory = any(
            line.strip().startswith(("import core.memory", "from core.memory"))
            for line in loop.splitlines())

        if "isn't wired into the live query path" in FLAT:
            assert not imports_memory, "the agent loop now uses core/memory; fix the README"

    def test_the_single_process_limitation_is_still_true(self):
        """Claimed: concurrency protections coordinate threads within
        one process. A cross-process lock file would falsify it."""
        assert (ROOT / "core/concurrency.py").exists()
        assert "Single OS process" in FLAT

    def test_it_admits_the_pre_customer_status(self):
        """The site's trust centre says so; the README must agree, or
        one of the two is misleading somebody."""
        assert "Pre-customer" in FLAT
        assert "no SOC 2" in FLAT


class TestTheOpeningMatchesTheSite:
    """The homepage copy is derived from this file. If the two drift,
    the site is selling something the README does not describe."""

    SITE = (ROOT / "site/index.html").read_text(encoding="utf-8")

    def test_both_say_the_model_never_gets_database_access(self):
        assert "never gets direct database access" in FLAT
        assert "never gets database access" in self.SITE

    def test_both_say_one_organization_per_instance(self):
        assert "One server instance runs one organization's data" in FLAT
        assert "One tenant" in self.SITE or "one organisation" in self.SITE.lower()

    def test_both_describe_the_approver_recheck(self):
        """The distinctive claim about writes. If the site says it and
        the README does not, a reader who checks will find a gap."""
        assert "approver" in FLAT.lower()
        assert "re-checked at the moment of approval" in FLAT
        assert "re-checked" in self.SITE
