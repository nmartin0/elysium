"""
run_sync(runtime_paths) reads the silos under THOSE paths.

FOUND BUILDING E-08'S FIXTURE. build_live_read_adapters() took only a
config directory and resolved the data directory itself, so
run_sync(runtime_paths) wrote its mirror under the paths it was given
and read the silos from the DEFAULT ones. In production one environment
supplies both, so they agreed. Given anything else, the silo path
resolved into the other deployment, where SQLite created an empty
database, and the sync refused every table with a column "gone".
"""

from pathlib import Path

import pytest

import scripts.seed_dev_silos as seed
from core.deployment_loader import RuntimePaths
from scripts.run_sync import run_sync


@pytest.fixture
def seeded(tmp_path):
    paths = RuntimePaths(
        config_dir=Path(__file__).resolve().parents[2] / "deployment" / "etc",
        data_dir=tmp_path / "data", log_dir=tmp_path / "log",
    )
    paths.data_dir.mkdir()
    paths.log_dir.mkdir()
    for schema_name, db_name in seed.DATABASES:
        seed.build(seed.FIXTURES / schema_name, paths.data_dir / "dev_fixtures" / db_name)
    return paths


@pytest.fixture
def decoy(tmp_path, monkeypatch):
    """The DEFAULT data directory, pointed somewhere empty -- where the
    bug would read from, and create a database in."""
    decoy = tmp_path / "decoy"
    # dev_fixtures/ EXISTS, as it does in the repository, where its
    # schema.sql is committed. Without it SQLite cannot create a file
    # there and errors instead -- and a first version of this test,
    # lacking it, passed against the bug.
    (decoy / "dev_fixtures").mkdir(parents=True)
    monkeypatch.setenv("ELYSIUM_DATA_DIR", str(decoy))
    return decoy


def test_the_sync_succeeds_from_the_silos_it_was_given(seeded, decoy):
    assert run_sync(seeded) == 0


def test_and_touches_no_other_deployment(seeded, decoy):
    """THE SIDE EFFECT: SQLite, opening a path that is not there, makes
    an empty database -- inside somebody else's data directory."""
    run_sync(seeded)

    assert list((decoy / "dev_fixtures").iterdir()) == []
