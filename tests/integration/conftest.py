"""
conftest.py  (integration tests -- deployment selection)

Which deployment the integration tests run against is dynamic, not
hardcoded -- defaults to acme_corp (currently the only deployment that
exists), but can be overridden with the TEST_DEPLOYMENT env var so
these same test files work against any future deployment without
editing them.

Uses a PATH lookup (Path("deployments") / name), not a Python import --
deployments/<org>/ contains no Python files at all, so there's nothing
to import. load_deployment_bundle() does the actual loading.

_bundle() is a private fixture so a test requesting BOTH `deployment`
and `engine` only loads the YAML and constructs the engine ONCE --
pytest caches a fixture's result per test, so deployment/engine below
both reuse the same _bundle() call rather than each reloading from disk.

What CANNOT be made generic: the actual assertions in each test still
reference specific known values (e.g. "$49.99") that only make sense
for acme_corp's dev fixture data.
"""

import os
from pathlib import Path

import pytest

from core.deployment_loader import load_deployment_bundle


def _deployment_dir() -> Path:
    return Path("deployments") / os.environ.get("TEST_DEPLOYMENT", "acme_corp")


@pytest.fixture
def _bundle():
    return load_deployment_bundle(_deployment_dir())


@pytest.fixture
def deployment(_bundle):
    config, _ = _bundle
    return config


@pytest.fixture
def engine(_bundle):
    _, engine = _bundle
    return engine
