"""
conftest.py  (integration tests -- deployment selection)

Single-tenant: tests run against the one real deployment/ folder by
default. TEST_DEPLOYMENT_DIR exists purely as a test-infrastructure
convenience -- e.g. pointing CI at a scratch copy without touching the
real deployment/ -- NOT a mechanism for switching between orgs.

Uses a PATH lookup, not a Python import -- deployment/ contains no
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

import os
from pathlib import Path

import pytest

from core.deployment_loader import load_deployment_bundle


def _deployment_dir() -> Path:
    return Path(os.environ.get("TEST_DEPLOYMENT_DIR", "deployment"))


@pytest.fixture
def _bundle():
    return load_deployment_bundle(_deployment_dir())


@pytest.fixture
def deployment(_bundle):
    config, _ = _bundle
    return config


@pytest.fixture
def mediator(_bundle):
    _, mediator = _bundle
    return mediator
