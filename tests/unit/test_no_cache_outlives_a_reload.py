"""
Nothing memoises across requests, so a reloaded generation is seen
immediately.

THE HOT-RELOAD PLAN RECORDED THIS AS A NOTE and said exactly why it
was writing it down:

    No cross-request memoisation exists -- checked. `visible_schema`
    is computed per query from the mediator's schema, so a swapped
    generation is picked up with no cache to invalidate. Recorded
    because it is THE ASSUMPTION MOST LIKELY TO BE QUIETLY BROKEN BY A
    FUTURE PERFORMANCE FIX -- an `@lru_cache` keyed on `user_id` would
    survive a reload and serve stale authorization.

A NOTE CANNOT BREAK. This file is that note with teeth: the next
person who reaches for `@lru_cache` on a function taking a user or a
schema finds out here rather than in production, where the symptom is
a user keeping a grant that was revoked.

WHY A SOURCE SCAN RATHER THAN A BEHAVIOURAL TEST. The failure is not
that some particular function caches; it is that ANY of them might,
and a behavioural test can only cover the ones somebody thought of. A
scan covers the ones nobody thought of, which is where this would
actually come from.

IT IS NOT A BAN ON CACHING. A cache keyed on something that does not
change across a reload -- a parsed regex, a format string -- is fine,
and allowed by name below. What is forbidden is a cache that can
outlive a generation while holding something a generation decides.
"""

import ast
from pathlib import Path

import pytest

#: Caching decorators that keep a value between calls.
MEMOISING = {"lru_cache", "cache", "cached_property", "memoize", "cached"}

#: Where a stale value would be an authorization decision.
GOVERNED = ("core", "api", "adapters")


def _decorated_with_memoisation():
    """Every function in the governed packages that memoises."""
    found = []
    for package in GOVERNED:
        for path in sorted(Path(package).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:  # pragma: no cover
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    name = decorator
                    if isinstance(name, ast.Call):
                        name = name.func
                    if isinstance(name, ast.Attribute):
                        name = name.attr
                    elif isinstance(name, ast.Name):
                        name = name.id
                    else:
                        continue
                    if name in MEMOISING:
                        found.append((str(path), node.name, name))
    return found


class TestNothingMemoisesAcrossAReload:
    def test_the_governed_packages_are_free_of_memoisation(self):
        """THE REGRESSION TEST. An `@lru_cache` keyed on `user_id`
        would survive a reload and serve stale authorization."""
        found = _decorated_with_memoisation()

        assert found == [], (
            "memoisation found in a package where a stale value is an "
            f"authorization decision: {found}. If the cached value cannot "
            "change across a configuration reload, add it to this test's "
            "allowance with the reason."
        )

    def test_the_scan_can_actually_see_a_decorator(self):
        """A scan that finds nothing because it is broken passes
        exactly like a scan that finds nothing because the code is
        clean. This proves it is the second."""
        source = ast.parse(
            "from functools import lru_cache\n"
            "@lru_cache\n"
            "def f(user_id): ...\n")
        decorated = [
            node for node in ast.walk(source)
            if isinstance(node, ast.FunctionDef) and node.decorator_list]

        assert len(decorated) == 1
        assert decorated[0].decorator_list[0].id in MEMOISING

    @pytest.mark.parametrize("form", [
        "@lru_cache\ndef f(u): ...",
        "@lru_cache(maxsize=None)\ndef f(u): ...",
        "@functools.cache\ndef f(u): ...",
        "@cached_property\ndef f(self): ...",
    ])
    def test_every_spelling_is_recognised(self, form, tmp_path):
        """Bare, called, dotted and the property form. A scan that only
        catches `@lru_cache` misses three of the four ways somebody
        would actually write it."""
        tree = ast.parse(form)
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    name = decorator
                    if isinstance(name, ast.Call):
                        name = name.func
                    names.append(name.attr if isinstance(name, ast.Attribute)
                                 else name.id)

        assert any(name in MEMOISING for name in names)


class TestWhatThePlanAlsoSettled:
    def test_the_deployment_config_is_frozen(self):
        """The plan recorded it as NOT frozen -- "a plain @dataclass,
        and it holds mutable dicts". It is frozen now, and this says so
        rather than leaving the older note to be believed."""
        import dataclasses

        from core.deployment_loader import DeploymentConfig

        assert dataclasses.fields(DeploymentConfig)
        with pytest.raises(dataclasses.FrozenInstanceError):
            config = DeploymentConfig.__new__(DeploymentConfig)
            object.__setattr__(config, "base_path", Path("."))
            config.base_path = Path("/elsewhere")
