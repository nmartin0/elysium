"""
A role store that exists and cannot be read REFUSES, rather than
falling back to policy.yaml.

SEC-19, SURVIVING ITS OWN FIX. The security agent raised "a truncated
roles.db silently hands authority back to policy.yaml", and
`RoleStore.load` was given a docstring promising exactly the right
thing:

    A STORE THAT EXISTS BUT CANNOT BE READ RAISES rather than falling
    back. Falling back to policy.yaml would silently restore whatever
    roles the store had replaced -- possibly grants that were
    deliberately withdrawn.

A TRUNCATED FILE DID RAISE. AN EMPTY ONE DID NOT, and that is the gap
this closes. A zero-byte file is a VALID SQLite database with no
tables, and `load()` went through `connection_with_schema`, which
CREATES tables when they are missing -- so the schema was written,
`seeded_at` was absent, `load()` returned None, and the deployment
fell back to policy.yaml exactly as the docstring said it must not.

MEASURED: a zero-byte roles.db grew to 20,480 bytes and gained both
tables MERELY BY BEING LOADED, which also contradicts the same
docstring's "loading must not write".

WHY A ZERO-BYTE STORE IS NOT A HYPOTHETICAL. It is what a full disk,
an interrupted copy, or a restore that created the file and copied
nothing leaves behind -- the same family as the stranded catalog in
patch 475, where a half-finished write left a pointer to nothing.

THE FIX IS READ-ONLY, not a new check. Opening read-only makes the
missing table an error instead of an invitation to create one, so the
promise the docstring already made becomes true rather than
additionally asserted.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from core.role_store import RoleStore, RoleStoreUnreadable


@pytest.fixture
def store_dir():
    with tempfile.TemporaryDirectory() as directory:
        yield Path(directory)


class TestWhatCountsAsAbsent:
    def test_no_file_means_use_policy_yaml(self, store_dir):
        """The only case that may fall back: a deployment that has
        never edited a role."""
        assert RoleStore(store_dir / "roles.db").load() is None

    def test_loading_an_absent_store_creates_nothing(self, store_dir):
        """Opening a SQLite database that is not there creates it, so
        the existence check has to come first."""
        path = store_dir / "roles.db"

        RoleStore(path).load()

        assert not path.exists()


class TestWhatCountsAsDamaged:
    def test_an_empty_file_refuses(self, store_dir):
        """THE CASE SEC-19's OWN FIX MISSED."""
        path = store_dir / "roles.db"
        path.write_bytes(b"")

        with pytest.raises(RoleStoreUnreadable):
            RoleStore(path).load()

    def test_a_truncated_file_refuses(self, store_dir):
        path = store_dir / "roles.db"
        path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 40)

        with pytest.raises(RoleStoreUnreadable):
            RoleStore(path).load()

    def test_a_database_with_OTHER_tables_is_not_damage(self, store_dir):
        """THE CASE I GOT WRONG FIRST, and thirteen role-change tests
        said so.

        `roles.db` holds TWO stores' tables -- the roles, and the
        changes proposed to them -- so a file created by the change
        store has tables but not ours and has simply never been seeded.
        Refusing it broke role editing entirely.

        The distinction that matters is NO TABLES AT ALL, which is the
        zero-byte case, versus tables belonging to something else."""
        path = store_dir / "roles.db"
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE role_changes (x TEXT)")
        connection.commit()
        connection.close()

        assert RoleStore(path).load() is None


class TestLoadingNeverWrites:
    def test_an_empty_store_is_not_given_a_schema(self, store_dir):
        """MEASURED BEFORE THE FIX: 0 bytes became 20,480 and gained
        both tables, purely from a load."""
        path = store_dir / "roles.db"
        path.write_bytes(b"")

        with pytest.raises(RoleStoreUnreadable):
            RoleStore(path).load()

        assert path.stat().st_size == 0

    def test_a_truncated_store_is_left_exactly_as_found(self, store_dir):
        path = store_dir / "roles.db"
        original = b"SQLite format 3\x00" + b"\x00" * 40
        path.write_bytes(original)

        with pytest.raises(RoleStoreUnreadable):
            RoleStore(path).load()

        assert path.read_bytes() == original


class TestTheRefusalIsActionable:
    def test_it_says_what_will_NOT_happen(self, store_dir):
        """The dangerous outcome is the silent one, so the message
        names it."""
        path = store_dir / "roles.db"
        path.write_bytes(b"")

        with pytest.raises(RoleStoreUnreadable, match="NOT fall back"):
            RoleStore(path).load()

    def test_it_offers_both_remedies(self, store_dir):
        """Restore it, or delete it on purpose. Deleting is a real
        choice -- it means starting from policy.yaml deliberately
        rather than by accident, which is the whole distinction."""
        path = store_dir / "roles.db"
        path.write_bytes(b"")

        with pytest.raises(RoleStoreUnreadable) as caught:
            RoleStore(path).load()

        assert "Restore it" in str(caught.value)
        assert "DELETE" in str(caught.value)
