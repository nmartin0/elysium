"""
A column added to a schema reaches databases that already exist.

`CREATE TABLE IF NOT EXISTS` DOES NOT ADD A COLUMN to a table that
already exists. A column added to a SCHEMA string reaches fresh
databases and silently misses every existing one -- and a store that
reads the new column then fails on each read.

THAT SHIPPED. `saved_views.presentation` was added to the schema
alone, and a database created before it returned NO VIEWS AT ALL:
"no such column: presentation", swallowed by the store's best-effort
handling and returned as an empty list.

SILENT, AND THE KIND OF DATA LOSS NOBODY REPORTS because nothing looks
broken -- the popover just shows no saved views. Found while about to
add a column to `triggers`, which would have repeated it.
"""

import sqlite3

import pytest

from core.sqlite_connection import add_column_if_missing

OLD_SAVED_VIEWS = """
CREATE TABLE saved_views (
    view_id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL,
    name TEXT NOT NULL, object_type TEXT NOT NULL,
    query_text TEXT NOT NULL DEFAULT '',
    conditions TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
"""


@pytest.fixture
def old_saved_views(tmp_path):
    """A saved_views database exactly as patch 267 created it."""
    path = tmp_path / "v.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SAVED_VIEWS)
    conn.execute(
        "INSERT INTO saved_views VALUES "
        "('v1', 'alice', 'Kept', 'Customer', '', '[]', '2026-01-01')",
    )
    conn.commit()
    conn.close()
    return path


class TestAnOlderDatabaseStillReads:
    def test_its_views_come_back(self, old_saved_views):
        """THE BUG THAT SHIPPED. Before the migration this returned an
        empty list, and nothing anywhere said so."""
        from core.saved_views import SavedViewStore

        views = SavedViewStore(old_saved_views).for_owner("alice")

        assert [view.name for view in views] == ["Kept"]

    def test_the_new_column_takes_its_default(self, old_saved_views):
        from core.saved_views import SavedViewStore

        view = SavedViewStore(old_saved_views).for_owner("alice")[0]

        assert view.presentation == {}

    def test_opening_twice_is_harmless(self, old_saved_views):
        """IDEMPOTENT, because every connection runs the migrations."""
        from core.saved_views import SavedViewStore

        store = SavedViewStore(old_saved_views)
        store.for_owner("alice")

        assert len(store.for_owner("alice")) == 1


class TestTheHelper:
    def test_it_adds_a_missing_column(self, tmp_path):
        conn = sqlite3.connect(tmp_path / "t.db")
        conn.execute("CREATE TABLE t (a TEXT)")

        add_column_if_missing("t", "b", "TEXT")(conn)

        assert "b" in [row[1] for row in conn.execute("PRAGMA table_info(t)")]

    def test_it_tolerates_the_column_already_being_there(self, tmp_path):
        conn = sqlite3.connect(tmp_path / "t.db")
        conn.execute("CREATE TABLE t (a TEXT, b TEXT)")

        add_column_if_missing("t", "b", "TEXT")(conn)

    def test_it_does_not_swallow_other_errors(self, tmp_path):
        """NARROWER THAN THE PRECEDENT IT FOLLOWS. database.py's own
        migration catches EVERY OperationalError, which would also
        swallow a missing table or a locked database. This catches only
        the duplicate it means."""
        conn = sqlite3.connect(tmp_path / "t.db")

        with pytest.raises(sqlite3.OperationalError):
            add_column_if_missing("no_such_table", "b", "TEXT")(conn)
