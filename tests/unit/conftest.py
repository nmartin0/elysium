"""
A seeded, synced deployment of this repository's own configuration --
built for each test, in its own temporary directory.

E-08: THIRTY UNIT TESTS FAILED ON A FRESH CLONE. They built generations
from resolve_runtime_paths() -- the DEVELOPER'S data directory -- so
they passed only where a server had once seeded and synced it, and
reported green from exactly those working copies. Four of them built on
that directory with no copy at all, so every run wrote pending writes
and notifications into the developer's own deployment.

NOW each test gets the real configuration (deployment/etc, as shipped)
over data nobody else can see: the three development silos seeded from
tests/integration/fixtures by the same build() a developer's seed uses,
and the mirror filled by the real run_sync().

PER TEST, NOT SHARED. A template copied per test was the obvious
shortcut, and wrong: the Iceberg catalog stores ABSOLUTE paths, so a
copy's warehouse still reads -- and would write new snapshots beside --
the template's files. Seeding and syncing measured 0.17 s once warm,
about fifteen seconds across the ninety tests that use it; isolation
costs that and no more.
"""

import contextlib
import io
from pathlib import Path

import pytest

import scripts.seed_dev_silos as seed
from core.deployment_loader import RuntimePaths
from scripts.run_sync import run_sync

# THE REPOSITORY'S OWN, not resolve_runtime_paths()'s: a developer with
# ELYSIUM_CONFIG_DIR set would otherwise test someone else's deployment.
CONFIG_DIR = Path(__file__).resolve().parents[2] / "deployment" / "etc"


@pytest.fixture
def synced_deployment(tmp_path) -> RuntimePaths:
    paths = RuntimePaths(
        config_dir=CONFIG_DIR,
        data_dir=tmp_path / "synced" / "data",
        log_dir=tmp_path / "synced" / "log",
    )
    paths.data_dir.mkdir(parents=True)
    paths.log_dir.mkdir(parents=True)
    for schema_name, db_name in seed.DATABASES:
        seed.build(seed.FIXTURES / schema_name, paths.data_dir / "dev_fixtures" / db_name)
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        status = run_sync(paths)
    # LOUD, not a quiet empty mirror: every test using this would
    # otherwise fail as "assert 0 > 0" -- E-08's own symptom.
    assert status == 0, f"the synced deployment could not sync:\n{printed.getvalue()}"
    return paths


@pytest.fixture
def private_deployment(tmp_path) -> RuntimePaths:
    """The shipped configuration over an EMPTY data directory of the
    test's own -- for tests that need a deployment's paths but no data.

    The same E-08 rule, the writing half: five more unit tests built on
    resolve_runtime_paths() and passed without data, WRITING into the
    developer's deployment as they went -- credentials.db, triggers.db,
    write_log.db, a mirror -- found by running the suite on a fresh clone
    and listing what appeared.
    """
    paths = RuntimePaths(
        config_dir=CONFIG_DIR,
        data_dir=tmp_path / "private" / "data",
        log_dir=tmp_path / "private" / "log",
    )
    paths.data_dir.mkdir(parents=True)
    paths.log_dir.mkdir(parents=True)
    return paths
