"""
conftest.py  (integration tests -- deployment selection)

Single-tenant: tests run against the real deployment by default, using
the SAME resolve_runtime_paths() every entry point uses -- config,
data, and logs are three independent locations, always (see
core/deployment_loader.py's docstring), not something this file
special-cases. Setting ELYSIUM_CONFIG_DIR/ELYSIUM_DATA_DIR (the SAME
variables a real install's systemd unit sets) points these tests at a
scratch copy instead of the real deployment/ -- no separate
test-specific mechanism exists, or needs to.

Uses a PATH lookup, not a Python import -- deployment/etc/ contains no
Python files at all, so there's nothing to import. load_deployment_bundle()
does the actual loading.

_bundle() is a private fixture so a test requesting BOTH `deployment`
and `mediator` only loads the YAML and constructs the mediator ONCE --
pytest caches a fixture's result per test, so deployment/mediator below
both reuse the same _bundle() call rather than each reloading from disk.

What CANNOT be made generic: the actual assertions in each test still
reference specific known values (e.g. "$49.99") that only make sense
for this deployment's dev fixture data.
"""

import pytest

from core.deployment_loader import load_deployment_bundle, resolve_runtime_paths


@pytest.fixture
def _bundle():
    paths = resolve_runtime_paths()
    return load_deployment_bundle(paths.config_dir, paths.data_dir)


@pytest.fixture
def deployment(_bundle):
    config, _ = _bundle
    return config


@pytest.fixture
def mediator(_bundle):
    _, mediator = _bundle
    return mediator
