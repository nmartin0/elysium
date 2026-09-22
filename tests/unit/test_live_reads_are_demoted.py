"""
Live reads are a fallback, and the service says so (GOLD-2b, the
owner's decision of September 22: "Demote live reading mode as it will
be incompatible with using the enriched data").

Everything silver and gold do -- standardisation, the declared
expectations and their quarantine, duplicate-key handling, lineage, and
gold itself -- lives in the lake. A live read goes straight to the
customer's database and sees none of it, so a deployment running that
way is not running the pipeline it declared.
"""

import logging
import shutil
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_YAML = ROOT / "deployment" / "etc" / "config.yaml"
INSTALL = ROOT / "INSTALL.md"


@pytest.fixture
def deployment(synced_deployment, tmp_path, monkeypatch):
    """The shipped configuration, copied so a test can change it."""
    def build(live: bool):
        config_dir = tmp_path / ("live" if live else "mirror")
        shutil.copytree(synced_deployment.config_dir, config_dir)
        if live:
            config = yaml.safe_load((config_dir / "config.yaml").read_text())
            config["mirror"] = {**(config.get("mirror") or {}), "read_from_mirror": False}
            (config_dir / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
        monkeypatch.setenv("ELYSIUM_DATA_DIR", str(synced_deployment.data_dir))
        monkeypatch.setenv("ELYSIUM_LOG_DIR", str(synced_deployment.log_dir))
        from core.deployment_loader import RuntimePaths
        return RuntimePaths(config_dir=config_dir, data_dir=synced_deployment.data_dir,
                            log_dir=synced_deployment.log_dir)
    return build


def _warnings(paths, caplog):
    from api.app import create_app
    with caplog.at_level(logging.WARNING, logger="api.app"):
        create_app(paths)
    return [record.getMessage() for record in caplog.records
            if "read_from_mirror is off" in record.getMessage()]


class TestTheStartupWarning:
    def test_live_reads_are_warned_about(self, deployment, caplog):
        assert _warnings(deployment(live=True), caplog)

    def test_it_names_what_is_bypassed(self, deployment, caplog):
        said = _warnings(deployment(live=True), caplog)[0]

        for bypassed in ("standardisation", "expectations", "quarantine",
                          "duplicate-key", "lineage", "gold"):
            assert bypassed in said

    def test_the_service_still_starts(self, deployment, caplog):
        """DEMOTED, not removed: a deployment that has not synced yet
        still needs it."""
        from api.app import create_app

        assert create_app(deployment(live=True)) is not None

    def test_mirror_reads_are_not_warned_about(self, deployment, caplog):
        assert not _warnings(deployment(live=False), caplog)


class TestTheDocumentation:
    """A TRIPWIRE. config.yaml claimed for months that both mirror keys
    defaulted to 'the conservative answer ... reads going to the
    customer's own databases', which the code stopped doing long before
    anyone noticed -- the exact shape of stale claim the audits kept
    finding."""

    def test_config_yaml_does_not_claim_live_reads_are_the_default(self):
        text = CONFIG_YAML.read_text()

        assert "both default to the conservative answer" not in text
        assert "default to COMING FROM THE MIRROR" in text

    def test_config_yaml_calls_live_reads_a_fallback(self):
        assert "a FALLBACK, not an equal choice" in CONFIG_YAML.read_text()

    def test_install_says_what_live_reads_give_up(self):
        text = INSTALL.read_text()

        assert "read_from_mirror: false" in text
        assert "bypasses all of it" in text
