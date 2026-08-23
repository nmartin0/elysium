"""
conftest.py  (integration tests -- deployment selection)

Which deployment the integration tests run against is dynamic, not
hardcoded -- defaults to acme_corp (currently the only deployment that
exists), but can be overridden with the TEST_DEPLOYMENT env var so
these same test files work against any future deployment without
editing them.

What CANNOT be made generic: the actual assertions in each test still
reference specific known values (e.g. "$49.99") that only make sense
for acme_corp's dev fixture data. Full assertion-level portability
would require each deployment to declare its own expected test
scenarios as data -- a real future enhancement, out of scope for now.
"""

import importlib
import os

import pytest


def _deployment_name() -> str:
    return os.environ.get("TEST_DEPLOYMENT", "acme_corp")


@pytest.fixture
def deployment():
    return importlib.import_module(f"deployments.{_deployment_name()}.deployment")


@pytest.fixture
def ontology_adapter():
    return importlib.import_module(f"deployments.{_deployment_name()}.ontology_adapter")
