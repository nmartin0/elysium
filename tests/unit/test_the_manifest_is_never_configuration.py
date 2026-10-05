"""
The lake's manifest is read-only input. It must never become
configuration.

Decided 5 October and closed permanently. `LAKE_METADATA_NOTE.md`
deferred the question in its own words, which are the whole argument:

> The stronger version -- bootstrapping a new deployment FROM the
> manifest -- is tempting and should wait. A copy that can become a
> source of truth is a copy that can disagree with one, and the whole
> reason this is a copy is to avoid that.

CONFIGURATION PRODUCES THE LAKE. If the lake could also produce
configuration there would be a cycle with no authority at either end,
and the failure is quiet: a deployment that boots from a stale
manifest and serves an ontology nobody declared.

THE SCENARIO THAT TEMPTS IT IS DISASTER RECOVERY -- "the config is
gone, rebuild it from what the mirror knows" -- and the answer there
is backing up the configuration, which
`scripts/backup_deployment.py` already does.

WHY A TEST AND NOT A NOTE. Planning documents get consumed; thirty-five
of them went this month. A reason that lives only in a list someone
will eventually delete is a reason that gets rediscovered the hard
way. This pins it to the function somebody would actually reach for.
"""

import inspect
from pathlib import Path

from core.mirror.manifest import read_manifests


class TestTheRefusalIsWhereSomebodyWouldLookForIt:
    def test_the_reader_says_so_in_its_own_docstring(self):
        """Not in a document three directories away. In the function a
        person opens when they want to do this."""
        doc = inspect.getdoc(read_manifests)

        assert "MUST NEVER BECOME CONFIGURATION" in doc

    def test_it_gives_the_reason_rather_than_the_rule(self):
        """A rule with no reason gets overturned by whoever finds it
        inconvenient."""
        # NORMALISED, because the sentence wraps. A substring test
        # against wrapped prose passes or fails on where the line
        # breaks fall, which is not what this is checking.
        doc = " ".join(inspect.getdoc(read_manifests).split())

        assert "A COPY THAT CAN BECOME A SOURCE OF TRUTH IS A COPY THAT " \
               "CAN DISAGREE WITH ONE" in doc

    def test_it_names_the_alternative_for_the_tempting_case(self):
        """Somebody reaching for this has a real problem. Refusing
        without pointing anywhere is how a refusal gets worked
        around."""
        doc = inspect.getdoc(read_manifests)

        assert "backup_deployment" in doc

    def test_the_original_contract_survived_the_edit(self):
        """I appended to a docstring that already said something
        important about failure handling."""
        doc = inspect.getdoc(read_manifests)

        assert "RETURNS WHAT IT CAN" in doc


class TestNothingLoadsConfigurationFromTheLake:
    def test_the_deployment_loader_does_not_read_manifests(self):
        """The check that would actually catch a regression: if this
        ever fails, somebody has wired the lake into configuration."""
        source = Path("core/deployment_loader.py").read_text()

        assert "read_manifests" not in source
        assert "manifest" not in source.lower().replace("manifesto", "")

    def test_only_reporting_code_reads_them(self):
        """Who may call it: scripts that REPORT, and tests. A caller in
        core/ that is not the manifest module itself would mean the
        lake had become an input to something that runs."""
        callers = []
        for path in Path("core").rglob("*.py"):
            if path.name == "manifest.py":
                continue
            if "read_manifests" in path.read_text():
                callers.append(str(path))

        assert callers == [], callers
