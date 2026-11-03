"""
The prose documents, checked against the system they describe.

The old README was a manual; its content now lives in docs/architecture.md
(how it is organized, the untrusted-model design), docs/limitations.md
(known limitations) and docs/development.md (the front end, the test
counts). README.md is a short introduction. Each claim is checked in the
file where it now lives.

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
ARCHITECTURE = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
LIMITATIONS = (ROOT / "docs/limitations.md").read_text(encoding="utf-8")
DEVELOPMENT = (ROOT / "docs/development.md").read_text(encoding="utf-8")

# LINE BREAKS ARE NOT MEANING. The documents are hard-wrapped at 72
# columns, so "never gets direct database access" is split across two
# lines and a substring check for it finds nothing. Collapsing the
# whitespace is the difference between testing the prose and testing
# the wrapping.
FLAT = " ".join(ARCHITECTURE.split())
LIMITATIONS_FLAT = " ".join(LIMITATIONS.split())
README_FLAT = " ".join(README.split())


class TestWhatItClaimsExists:
    @pytest.mark.parametrize("claim, module", [
        ("bronze", "src/elysium/core/mirror/iceberg_sync.py"),
        ("silver", "src/elysium/core/mirror/transform.py"),
        ("gold", "src/elysium/core/mirror/gold.py"),
        ("fusion.py", "src/elysium/core/mirror/fusion.py"),
    ])
    def test_the_pipeline_stages_it_names_are_real(self, claim, module):
        # The stages are named in the architecture; fusion.py is named
        # where the retracted cross-silo limitation is recorded.
        assert claim in ARCHITECTURE + LIMITATIONS, claim
        assert (ROOT / module).exists(), module

    def test_every_ui_package_in_the_table_exists(self):
        packages = [p.name for p in (ROOT / "ui/packages").iterdir() if p.is_dir()]

        for package in packages:
            assert f"`{package}`" in DEVELOPMENT, f"{package} is not in docs/development.md's table"

    def test_the_counts_are_not_wildly_stale(self):
        """Not exact -- the suite grows every patch -- but a figure that
        has drifted into fiction fails."""
        import re

        unit = len(list((ROOT / "tests/unit").glob("test_*.py")))
        claimed = int(re.search(r"\| unit \| [^|]+\| (\d+) files", DEVELOPMENT).group(1))

        assert abs(claimed - unit) <= 25, f"docs/development.md says {claimed} unit files, there are {unit}"


class TestWhatItClaimsIsMissing:
    """The dangerous half. A limitation that has been fixed is a lie
    the reader has no reason to doubt."""

    def test_it_does_not_still_deny_cross_silo_links(self):
        """THE ONE THAT SURVIVED. fusion.py's own docstring: a Customer
        spanning primary_sql.customers and risk_db.risk_scores "is a
        JOIN: every property has one authoritative home"."""
        # THE ACTIVE LIST ONLY. docs/limitations.md quotes the retracted
        # line under "What this list used to say, and no longer does",
        # which is deliberate -- a limitations section that silently
        # drops a claim teaches nobody anything. A test that searched
        # the whole section could not tell a retraction from the
        # original.
        section = LIMITATIONS[LIMITATIONS.index("## Known limitations"):]
        active = section[:section.index("### What this list used to say")]

        assert "cross-silo" not in " ".join(active.split()).lower()

    def test_the_memory_limitation_is_still_true(self):
        """Claimed: Query is given memories and never writes one unless
        remember_from_query is on -- which is off by default. Checked on
        the code, not the source text: with the switch off the loop has
        no remember handler at all."""
        from unittest.mock import MagicMock

        from elysium.core.agent.agentic_loop import AgentLoop
        from elysium.core.llm.agent_features import OFF, AgentFeatures

        loop = (ROOT / "src/elysium/core/agent/agentic_loop.py").read_text(encoding="utf-8")

        assert "Agent memory is written by hand" in LIMITATIONS_FLAT
        assert "remember_from_query" in LIMITATIONS_FLAT and "off by default" in LIMITATIONS_FLAT
        assert AgentFeatures() == OFF and not OFF.remember_from_query
        assert "self.memory.fresh(" in loop
        assert "remember" not in AgentLoop(MagicMock(), MagicMock())._step_handlers(), \
            "the agent writes memories by default now; fix docs/limitations.md"

    def test_the_one_machine_limitation_is_still_true(self):
        """Claimed: several workers on one machine are checked, and the
        coordination is file locks -- which is why it is ONE machine."""
        assert (ROOT / "src/elysium/scripts/check_workers.py").exists()
        assert "fcntl" in (ROOT / "src/elysium/core/ontology/write_mediator.py").read_text(encoding="utf-8")
        assert "One machine." in LIMITATIONS_FLAT

    def test_it_admits_the_pre_customer_status(self):
        """The site's trust centre says so; the README must agree, or
        one of the two is misleading somebody."""
        assert "Pre-customer" in LIMITATIONS_FLAT
        assert "no SOC 2" in LIMITATIONS_FLAT
        assert "Pre-1.0" in README_FLAT and "no deployments" in README_FLAT


class TestTheOpeningMatchesTheSite:
    """The homepage copy is derived from the README and
    docs/architecture.md. If the two drift, the site is selling
    something the documents do not describe."""

    SITE = (ROOT / "site/index.html").read_text(encoding="utf-8")

    def test_both_say_the_model_never_gets_database_access(self):
        assert "never gets direct database access" in README_FLAT
        assert "never gets direct database access" in FLAT
        assert "never gets database access" in self.SITE

    def test_both_say_one_organization_per_instance(self):
        assert "One server instance runs one organization's data" in README_FLAT
        assert "One server instance runs one organization's data" in FLAT
        assert "One tenant" in self.SITE or "one organisation" in self.SITE.lower()

    def test_both_describe_the_approver_recheck(self):
        """The distinctive claim about writes. If the site says it and
        the README does not, a reader who checks will find a gap."""
        assert "approver" in FLAT.lower()
        assert "re-checked at the moment of approval" in FLAT
        assert "re-checked" in self.SITE
