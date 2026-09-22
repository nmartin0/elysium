"""
Roles the running application can change.

POLICY.YAML IS THE BOOTSTRAP, and nothing changes until somebody edits
a role. The store does not exist before then: loading reads policy.yaml
exactly as before and writes nothing. Once seeded, the store governs,
and its roles pass the SAME freeze and validators a file's do.

WHY LOADING NEVER WRITES. build_generation is "pure with respect to
process state" -- which is what lets a failed reload leave the running
generation untouched.
"""

import logging

import pytest

from core.role_store import RoleStore, canonical


@pytest.fixture
def paths(private_deployment):
    # E-08: this COPIED the developer's data directory, credentials and
    # all. The test's own private deployment is all it ever needed.
    real = private_deployment
    return real.config_dir, real.data_dir, real.log_dir


def _generation(paths):
    from core.deployment_loader import build_generation

    return build_generation(*paths)


def _policy_roles(paths):
    return {name: dict(role) for name, role in _generation(paths).config.roles.items()}


class TestBeforeAnyEdit:
    def test_policy_yaml_governs(self, paths):
        roles = _generation(paths).config.roles

        assert "debug" in roles

    def test_loading_creates_no_store(self, paths):
        """OPENING A SQLITE DATABASE THAT IS NOT THERE CREATES IT, which
        is why the store checks the file exists first."""
        _generation(paths)

        assert not (paths[1] / "roles.db").exists()

    def test_the_digest_is_the_files_alone(self, paths):
        """NOTHING DIFFERS until an edit -- including the digest, so no
        trigger baseline resets merely because this feature exists.

        AGAINST THE FILES' OWN DIGEST, computed independently. A first
        version compared the generation's digest with its config's --
        always the same value, since one is copied from the other, so
        it would have passed whatever the digest was.
        """
        from core.deployment_loader import CONFIG_FILENAMES, _source_digest

        assert _generation(paths).source_digest == _source_digest(
            paths[0], CONFIG_FILENAMES,
        )


class TestOnceSeeded:
    def test_the_store_governs(self, paths):
        roles = _policy_roles(paths)
        roles["auditor"] = {"allowed_actions": ["read:Customer"]}
        RoleStore(paths[1] / "roles.db").save(roles)

        assert "auditor" in _generation(paths).config.roles

    def test_its_roles_are_frozen_like_a_files(self, paths):
        """THE SAME FREEZE: allowed_actions becomes a frozenset, so every
        authorize() stays O(1)."""
        RoleStore(paths[1] / "roles.db").save(_policy_roles(paths))

        role = _generation(paths).config.roles["debug"]

        assert isinstance(role["allowed_actions"], frozenset)

    def test_a_grant_change_changes_the_digest(self, paths):
        """THE DIGEST COVERS EFFECTIVE ROLES. Trigger baselines reset on
        a digest change, and hashing policy.yaml's bytes alone would stop
        seeing grant changes the moment roles live here."""
        store = RoleStore(paths[1] / "roles.db")
        roles = _policy_roles(paths)
        store.save(roles)
        before = _generation(paths).source_digest

        roles["debug"] = {"allowed_actions": ["read:Customer"]}
        store.save(roles)

        assert _generation(paths).source_digest != before

    def test_an_invalid_role_is_refused_at_load(self, paths):
        """REFUSED AT LOAD, so a bad edit cannot become the running
        generation."""
        roles = _policy_roles(paths)
        roles["broken"] = {"allowed_actions": ["read:NoSuchType"]}
        RoleStore(paths[1] / "roles.db").save(roles)

        with pytest.raises(ValueError):
            _generation(paths)

    def test_a_policy_yaml_that_disagrees_is_named(self, paths, caplog):
        """LOUD, BECAUSE THE FAILURE IT PREVENTS IS SILENT: somebody
        edits policy.yaml, reloads, and nothing happens."""
        roles = _policy_roles(paths)
        roles["auditor"] = {"allowed_actions": ["read:Customer"]}
        RoleStore(paths[1] / "roles.db").save(roles)

        with caplog.at_level(logging.WARNING):
            _generation(paths)

        assert "NOT in effect" in caplog.text

    def test_agreement_is_quiet(self, paths, caplog):
        RoleStore(paths[1] / "roles.db").save(_policy_roles(paths))

        with caplog.at_level(logging.WARNING):
            _generation(paths)

        assert "NOT in effect" not in caplog.text


class TestTheStoreItself:
    def test_an_unseeded_file_means_policy_yaml(self, tmp_path):
        """EMPTINESS IS NOT THE SIGNAL -- the seeded marker is. A store
        somebody emptied would otherwise hand control back to
        policy.yaml silently."""
        path = tmp_path / "roles.db"
        store = RoleStore(path)
        with store._connection():
            pass

        assert path.exists()
        assert store.load() is None

    def test_an_emptied_store_stays_authoritative(self, tmp_path):
        store = RoleStore(tmp_path / "roles.db")
        store.save({"a": {"allowed_actions": []}})
        store.save({})

        assert store.load() == {}

    def test_it_round_trips(self, tmp_path):
        store = RoleStore(tmp_path / "roles.db")
        store.save({"a": {"allowed_actions": ["read:X", "manage:users"]}})

        assert store.load() == {"a": {"allowed_actions": ["manage:users", "read:X"]}}

    def test_the_canonical_form_ignores_order(self):
        """THE SAME ROLES SERIALISE THE SAME WAY, so the digest over them
        does not change because a set iterated differently."""
        one = canonical({"a": {"allowed_actions": frozenset({"x", "y"})}})
        two = canonical({"a": {"allowed_actions": ["y", "x"]}})

        assert one == two
