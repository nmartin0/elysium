"""
Direct, adapter-level tests for SQLiteAdapter.write_fields() -- the
atomic conditional write / lost-update check at the heart of every
confirmed write in this project. No existing test file exercised this
directly before -- every prior test went through the higher-level
WriteMediator.confirm_and_execute() only.

A REAL, CONFIRMED BUG this file specifically guards against: the
conditional WHERE clause used to build "{key} = ?" for every field in
expected_current_values -- but in SQL, "column = NULL" always
evaluates to NULL/unknown, never TRUE, even when the actual stored
value genuinely IS NULL. This meant the lost-update check silently,
ALWAYS failed for any write touching a field whose CURRENT value
happened to be NULL -- not scoped to named actions or any specific
feature, a general correctness bug in the write path itself, found
while testing propose_action() against a field that legitimately
started NULL (a raw ValueError, "changed since this write was
proposed," on a field that had never actually changed at all). Fixed
with "IS ?" instead of "= ?" -- SQLite's null-safe equality, identical
to "=" for non-NULL values.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteAdapter

TYPE_CONFIG = {
    "storage": {"silo": "test", "table": "widgets", "id_column": "widget_id"},
}


@pytest.fixture
def adapter(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE widgets (widget_id TEXT PRIMARY KEY, name TEXT, note TEXT);
        INSERT INTO widgets VALUES ('w1', 'Original Name', NULL);
    """)
    conn.commit()
    conn.close()
    return SQLiteAdapter({"path": db_path})


def test_write_succeeds_when_expected_current_values_match(adapter):
    success = adapter.write_fields(
        "Widget", "w1", {"name": "New Name"}, {"name": "Original Name"}, TYPE_CONFIG,
    )
    assert success is True
    assert adapter.get_raw_field("Widget", "w1", "name", TYPE_CONFIG) == "New Name"


def test_write_fails_on_genuine_lost_update(adapter):
    # expected_current_values claims the name is something it genuinely
    # is NOT -- simulating another writer having changed it first.
    success = adapter.write_fields(
        "Widget", "w1", {"name": "New Name"}, {"name": "Someone Else Already Changed This"}, TYPE_CONFIG,
    )
    assert success is False
    # And the database is provably untouched -- a failed conditional
    # write must never partially apply.
    assert adapter.get_raw_field("Widget", "w1", "name", TYPE_CONFIG) == "Original Name"


def test_write_succeeds_when_expected_current_value_is_genuinely_null(adapter):
    # THE regression test for the real bug: "note" genuinely IS NULL
    # right now (see fixture) -- expected_current_values correctly
    # reflects that as None. Before the fix, this ALWAYS failed here,
    # regardless of whether the value had actually changed, because
    # "note = NULL" in the generated SQL never matches anything.
    success = adapter.write_fields(
        "Widget", "w1", {"note": "First note ever set"}, {"note": None}, TYPE_CONFIG,
    )
    assert success is True
    assert adapter.get_raw_field("Widget", "w1", "note", TYPE_CONFIG) == "First note ever set"


def test_write_still_fails_on_lost_update_when_expected_value_is_null(adapter):
    # Proves the fix didn't accidentally WEAKEN the null case in the
    # other direction -- if expected_current_values claims None but
    # the real value is genuinely something else (not null), the
    # write must still correctly fail as a lost update.
    conn = sqlite3.connect(adapter.db_path)
    conn.execute("UPDATE widgets SET note = ? WHERE widget_id = ?", ("Someone already set this", "w1"))
    conn.commit()
    conn.close()

    success = adapter.write_fields(
        "Widget", "w1", {"note": "My new note"}, {"note": None}, TYPE_CONFIG,
    )
    assert success is False
    assert adapter.get_raw_field("Widget", "w1", "note", TYPE_CONFIG) == "Someone already set this"


def test_write_multiple_fields_atomically_including_a_null_one(adapter):
    # Both a non-null and a null-valued field checked TOGETHER, in one
    # atomic statement -- the realistic shape of what propose_action()'s
    # resolved mutations actually produce.
    success = adapter.write_fields(
        "Widget", "w1",
        {"name": "New Name", "note": "New note"},
        {"name": "Original Name", "note": None},
        TYPE_CONFIG,
    )
    assert success is True
    assert adapter.get_raw_field("Widget", "w1", "name", TYPE_CONFIG) == "New Name"
    assert adapter.get_raw_field("Widget", "w1", "note", TYPE_CONFIG) == "New note"
