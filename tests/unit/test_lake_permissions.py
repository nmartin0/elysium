"""
Who can read the lake (OPEN_RISKS item 2).

GOLD CHANGED WHAT THE FILES ARE WORTH, and nobody decided that it
should. The mirror used to be a scattered copy of source tables under
source column names; gold is one table per object type, conformed,
keyed and joined -- the business picture. The same bytes became far
more worth stealing.

AND THE ONTOLOGY'S SECURITY DOES NOT APPLY TO THEM. Object and
property security, the region check and the audit entry all happen in
the READ PATH. A process that opens the Parquet gets every row and
every column, and nothing records that it did -- which is Iceberg's
design, not a gap in Elysium.

SO: A LAKE ELYSIUM CREATES IS OWNER-ONLY, and one that already exists
is REPORTED RATHER THAN CHANGED. An operator may have widened it
deliberately for a backup user or a read-only mount, and a deployment
that silently revokes that at boot is one that breaks at 3am.
"""

import logging
import stat

import pytest

from core.mirror.lake_permissions import (
    PRIVATE_MODE,
    make_private,
    readable_by_others,
    warn_if_world_readable,
)


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


class TestCreating:
    def test_a_new_lake_is_owner_only(self, tmp_path):
        lake = tmp_path / "mirror"

        make_private(lake)

        assert _mode(lake) == PRIVATE_MODE

    def test_it_creates_parents_too(self, tmp_path):
        lake = tmp_path / "var" / "lib" / "mirror"

        make_private(lake)

        assert lake.exists()

    def test_an_EXISTING_directory_is_left_exactly_as_it_was(self, tmp_path):
        """The asymmetry that matters: creating is ours, and an
        existing directory is the operator's."""
        lake = tmp_path / "mirror"
        lake.mkdir()
        lake.chmod(0o755)

        make_private(lake)

        assert _mode(lake) == 0o755

    def test_the_sync_creates_its_lake_private(self, tmp_path):
        """Through the real path, not the helper: it defaulted to
        0o755, which on a shared host is every account on the box."""
        from core.mirror.iceberg_sync import IcebergMirrorSync

        lake = tmp_path / "mirror"
        IcebergMirrorSync(lake, {})

        assert _mode(lake) == PRIVATE_MODE
        assert _mode(lake / "warehouse") == PRIVATE_MODE


class TestReporting:
    def test_a_private_lake_says_nothing(self, tmp_path, caplog):
        lake = tmp_path / "mirror"
        make_private(lake)

        with caplog.at_level(logging.WARNING):
            warned = warn_if_world_readable(lake, logging.getLogger("t"))

        assert warned is False and caplog.records == []

    @pytest.mark.parametrize("mode", [0o755, 0o750, 0o705, 0o775])
    def test_anything_others_can_reach_is_reported(self, tmp_path, mode):
        """Group counts. A deployment whose lake is 0o750 has given
        every member of that group the whole ontology."""
        lake = tmp_path / "mirror"
        lake.mkdir()
        lake.chmod(mode)

        assert readable_by_others(lake) == oct(mode)

    def test_the_warning_names_the_mode_and_the_command(self, tmp_path, caplog):
        """A warning an operator cannot act on is noise."""
        lake = tmp_path / "mirror"
        lake.mkdir()
        lake.chmod(0o755)

        with caplog.at_level(logging.WARNING):
            warn_if_world_readable(lake, logging.getLogger("t"))

        message = caplog.records[0].message
        assert "0o755" in message
        assert f"chmod 700 {lake}" in message

    def test_it_says_WHY_rather_than_only_what(self, tmp_path, caplog):
        """The point is not the file mode: it is that the ontology's
        security does not apply to these files at all."""
        lake = tmp_path / "mirror"
        lake.mkdir()
        lake.chmod(0o755)

        with caplog.at_level(logging.WARNING):
            warn_if_world_readable(lake, logging.getLogger("t"))

        message = caplog.records[0].message
        assert "every region" in message and "no audit entry" in message

    def test_a_lake_that_does_not_exist_yet_is_not_a_finding(self, tmp_path):
        """A deployment before its first sync has none, and warning
        about it would train an operator to ignore the warning."""
        assert readable_by_others(tmp_path / "absent") is None
