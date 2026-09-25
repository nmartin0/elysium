"""
Nothing can quietly put the serving path back on the sources
(PA001-A19).

THE FINDING: "every API integration test runs read_from_mirror false,
so the DEFAULT serving path has no end-to-end tests". It was true and
it is fixed -- patch 386 removed the declaration from
tests/integration/fixtures/config.yaml, and the suite's own template
now carries a `gold` namespace that every read goes through.

WHAT WAS MISSING IS THE THING THAT KEEPS IT FIXED. `_refuse_live_reads`
exists and nothing asserted it refuses; the fixture no longer declares
the flag and nothing asserted it must not. Either could be undone by
one line in a YAML file, and the symptom would be silence: the
integration suite would keep passing while testing a path no
deployment uses. That is exactly the shape of the original defect.

WHY REFUSED RATHER THAN IGNORED, from the guard's own reasoning: a
deployment that set this deliberately expects the old behaviour, and
silently giving it the new one is the worst of both -- the operator
believes reads bypass the lake, and they do not.
"""

from pathlib import Path

import pytest
import yaml

from core.deployment_loader import _refuse_live_reads

FIXTURE_CONFIGS = (
    "tests/integration/fixtures/config.yaml",
    "deployment/etc/config.yaml",
    "templates/config.yaml",
)


class TestADeclarationIsRefused:
    def test_read_from_mirror_false_fails_the_load(self):
        with pytest.raises(ValueError):
            _refuse_live_reads({"mirror": {"read_from_mirror": False}})

    def test_the_refusal_says_what_to_do_instead(self):
        """A load that fails without telling an operator how to
        proceed just gets the line deleted at random until it
        starts."""
        with pytest.raises(ValueError) as raised:
            _refuse_live_reads({"mirror": {"read_from_mirror": False}})

        assert "read_from_mirror" in str(raised.value)

    @pytest.mark.parametrize("declared", [True, None])
    def test_true_or_absent_is_accepted(self, declared):
        config = {} if declared is None else {"mirror": {"read_from_mirror": declared}}

        assert _refuse_live_reads(config) is True

    def test_it_is_always_true(self):
        """Not "usually". Every other part of the read path is built
        on this being unconditional."""
        assert _refuse_live_reads({}) is True
        assert _refuse_live_reads({"mirror": {}}) is True


class TestNoShippedConfigDeclaresIt:
    """THE TRIPWIRE FOR A19 ITSELF. The finding was not that the flag
    existed -- it was that a TEST FIXTURE used it, so the suite
    measured a path no deployment runs. A fixture is the easiest place
    for that to come back, and the easiest place for it to go
    unnoticed."""

    @pytest.mark.parametrize("path", FIXTURE_CONFIGS)
    def test_the_config_does_not_set_it(self, path):
        config = yaml.safe_load(Path(path).read_text()) or {}

        declared = (config.get("mirror") or {}).get("read_from_mirror")
        assert declared is not False, (
            f"{path} declares read_from_mirror: false. The integration suite "
            f"would then test a path no deployment uses (PA001-A19).")

    def test_the_integration_fixture_would_load(self):
        """Stronger than reading the key: the same call the loader
        makes, against the file the suite actually uses."""
        config = yaml.safe_load(
            Path("tests/integration/fixtures/config.yaml").read_text()) or {}

        assert _refuse_live_reads(config) is True
