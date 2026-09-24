"""
Live reads are gone, and a deployment that asks for them is refused
(GOLD-9).

THIS FILE USED TO TEST A WARNING. While `read_from_mirror: false`
existed, the service started and said what was being bypassed --
standardisation, the declared expectations and their quarantine,
duplicate-key handling, lineage and gold itself. That was the right
answer for a fallback that could still be selected.

IT CANNOT BE SELECTED NOW, so a warning would be worse than nothing:
it would imply the mode still works. The load FAILS instead, naming
the setting and saying what to do -- because a deployment that set it
deliberately expects the old behaviour, and silently giving it the new
one would be the worst of both. The operator believes reads bypass the
lake, and they do not.
"""

import shutil

import pytest
import yaml

from core.deployment_loader import load_deployment


@pytest.fixture
def config_dir(synced_deployment, tmp_path):
    """A copy of the shipped configuration, editable."""
    def build(declared_value):
        target = tmp_path / f"etc-{declared_value}"
        shutil.copytree(synced_deployment.config_dir, target)
        config = yaml.safe_load((target / "config.yaml").read_text())
        mirror = dict(config.get("mirror") or {})
        if declared_value is None:
            mirror.pop("read_from_mirror", None)
        else:
            mirror["read_from_mirror"] = declared_value
        config["mirror"] = mirror
        (target / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
        return target
    return build


class TestTheRefusal:
    def test_asking_for_live_reads_fails_the_load(self, config_dir):
        with pytest.raises(ValueError, match="no longer supported"):
            load_deployment(config_dir(False))

    def test_the_message_says_what_to_do_instead(self, config_dir):
        """An operator reading this at 2am needs the next command, not
        a description of the architecture."""
        with pytest.raises(ValueError, match="run_sync"):
            load_deployment(config_dir(False))

    def test_saying_nothing_is_fine_and_means_the_mirror(self, config_dir):
        assert load_deployment(config_dir(None)).read_from_mirror is True

    def test_asking_for_the_mirror_explicitly_is_fine_too(self, config_dir):
        """A deployment that wrote `true` was already right, and should
        not be punished for having said so."""
        assert load_deployment(config_dir(True)).read_from_mirror is True


class TestTheDocumentation:
    def _install(self):
        from pathlib import Path
        return Path("INSTALL.md").read_text()

    def test_install_says_reads_come_from_gold(self):
        assert "READS COME FROM THE GOLD TABLES" in self._install().upper()

    def test_install_says_the_first_sync_must_run(self):
        """The one thing a new deployment has to know: it starts, and
        it cannot answer reads until gold exists."""
        text = self._install()

        assert "run_sync" in text
        assert "first sync" in text.lower()

    def test_config_yaml_no_longer_offers_the_setting(self):
        """NOT OFFERED, though still EXPLAINED. The file mentions the
        setting on purpose -- an operator grepping for what they used
        to write should find out what happened to it -- so what must
        not appear is an uncommented one somebody could uncomment."""
        from pathlib import Path
        shipped = Path("deployment/etc/config.yaml").read_text()

        offered = [
            line for line in shipped.splitlines()
            if "read_from_mirror" in line and not line.strip().startswith("#")
        ]

        assert offered == []
        assert "read_from_mirror" in shipped, "the explanation went too"
