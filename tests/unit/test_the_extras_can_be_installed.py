"""
A declared extra is one somebody can actually install.

WHAT WAS WRONG. pyproject.toml declared

    [project.optional-dependencies]
    identity = ["splink>=4.0,<5"]

with NO `[project]` table above it. So the documented command failed:

    $ pip install -e ".[identity]"
    ValueError: invalid pyproject.toml config: `project`.
    configuration error: `project` must contain ['version'] properties

THE EXTRA WAS A DECLARATION NO COMMAND COULD SATISFY, and its own
comment implied otherwise: "A deployment that never enables it never
installs it". There was no way to install it either.

WHAT THAT COST, measured rather than supposed: splink was installed on
NEITHER the owner's machine nor mine, so eight probabilistic-matching
tests skipped in every environment used to approve every patch this
week. GOLD-6 inference had no coverage anywhere. With the extra
installed, all 20 tests in that file pass -- the feature was never
broken, it was unverified.

WHY A TEST AND NOT JUST A FIX. The failure was invisible from inside:
the suite was green, lint was green, and the only symptom was a skip
count nobody was reading. Four lines of TOML could remove it again the
same way.

NOT A LIBRARY. Elysium is run from a checkout -- runtime dependencies
live in requirements.txt with their locks. The `[project]` table
exists so the extra works, and for nothing else.
"""

import tomllib
from pathlib import Path

import pytest

PYPROJECT = tomllib.loads(Path("pyproject.toml").read_text())


class TestTheProjectTable:
    def test_it_exists(self):
        assert "project" in PYPROJECT

    @pytest.mark.parametrize("key", ["name", "version"])
    def test_it_declares_what_pip_requires(self, key):
        """These two are exactly what pip complained about. Without
        them every extra below is unreachable."""
        assert key in PYPROJECT["project"], (
            f"pyproject declares no {key}, so `pip install -e \".[...]\"` "
            f"fails and every extra becomes undeclarable")


class TestEveryExtraIsReachable:
    def test_there_is_at_least_one(self):
        assert PYPROJECT["project"].get("optional-dependencies")

    @pytest.mark.parametrize("extra", PYPROJECT["project"]
                              .get("optional-dependencies", {}))
    def test_it_names_at_least_one_package(self, extra):
        assert PYPROJECT["project"]["optional-dependencies"][extra]

    def test_identity_still_pins_splink_below_five(self):
        """The pin has a reason recorded beside it: splink 5 raises
        "Salting partitions must be specified and > 1" from
        estimate_u_using_random_sampling, reproduced across four
        version pairs. Elysium declares its weights rather than
        estimating them, so the path is unused -- but the pin is
        cheaper than rediscovering it from a deployment."""
        identity = PYPROJECT["project"]["optional-dependencies"]["identity"]

        assert any("splink" in package and "<5" in package
                   for package in identity)


class TestThePackagesAnEditableInstallExposes:
    def test_they_are_named_rather_than_discovered(self):
        """Automatic discovery finds `deployment`, `tests` and the
        sibling worktree directories, and fails or installs them."""
        assert PYPROJECT.get("tool", {}).get("setuptools", {}).get("packages")

    @pytest.mark.parametrize("package", ["core", "api", "adapters", "scripts"])
    def test_the_real_ones_are_included(self, package):
        assert package in PYPROJECT["tool"]["setuptools"]["packages"]

    def test_tests_and_deployment_are_not(self):
        """Installing a deployment's configuration into site-packages
        would be a surprising thing for an editable install to do."""
        packages = PYPROJECT["tool"]["setuptools"]["packages"]

        assert "tests" not in packages
        assert "deployment" not in packages
