"""
Direct, adapter-level tests for SQLiteReadAdapter.find_ids_matching_text()
-- the free-text, CONTAINS-match search underneath DataMediator.
search_object_free_text() (see that method's own docstring/AI-notes
for the full design). No existing test file exercised this directly
before -- tests/unit/test_mediator.py's own coverage goes through the
full DataMediator, which is the realistic call path, but this file
isolates the SQL itself, the one place a real, subtle bug (the LIKE
wildcard-escaping issue below) would actually live.

A REAL, CONFIRMED gotcha this file specifically guards against,
verified directly (not assumed) before this method was ever written:
SQLite's LIKE operator treats "%" and "_" as genuine wildcards, not
literal characters, unless escaped -- an unescaped search for a
literal "50%" would otherwise ALSO match "50X" and similar. Fixed via
backslash-escaping both characters in the query text before wrapping
it in %...%, plus an explicit ESCAPE '\\' clause.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter

TYPE_CONFIG = {
    "storage": {"silo": "test", "table": "widgets", "id_column": "widget_id"},
}


@pytest.fixture
def adapter(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE widgets (widget_id TEXT PRIMARY KEY, name TEXT, note TEXT, count INTEGER);
        INSERT INTO widgets VALUES ('w1', 'Ada Lovelace', 'first programmer', 1843);
        INSERT INTO widgets VALUES ('w2', 'Bob Smith', 'nothing special', 2020);
        INSERT INTO widgets VALUES ('w3', '50% Off Corp', 'discount vendor', 2021);
        INSERT INTO widgets VALUES ('w4', '50X Off Corp', 'unrelated vendor', 2022);
    """)
    conn.commit()
    conn.close()
    return SQLiteReadAdapter({"path": db_path})


def test_finds_a_partial_match_in_one_column(adapter):
    assert adapter.find_ids_matching_text("Widget", ["name"], "ada", TYPE_CONFIG) == ["w1"]


def test_is_case_insensitive(adapter):
    assert adapter.find_ids_matching_text("Widget", ["name"], "ADA", TYPE_CONFIG) == ["w1"]


def test_matches_across_multiple_columns_with_or(adapter):
    # "programmer" only appears in `note`, not `name` -- proves the
    # search genuinely covers every given column, not just the first.
    assert adapter.find_ids_matching_text("Widget", ["name", "note"], "programmer", TYPE_CONFIG) == ["w1"]


def test_matches_an_integer_column_via_type_coercion(adapter):
    # SQLite's own dynamic typing coerces an INTEGER column to text for
    # a LIKE comparison -- confirmed directly, not assumed.
    assert adapter.find_ids_matching_text("Widget", ["count"], "184", TYPE_CONFIG) == ["w1"]


def test_literal_percent_is_not_treated_as_a_wildcard(adapter):
    # THE core gotcha this file exists to guard against -- an
    # unescaped "%" would also match w4 ("50X Off Corp"), since % is a
    # genuine SQL wildcard matching any character sequence. Escaped
    # correctly, "50%" matches ONLY the row with that literal text.
    assert adapter.find_ids_matching_text("Widget", ["name"], "50%", TYPE_CONFIG) == ["w3"]


def test_literal_underscore_is_not_treated_as_a_wildcard(adapter):
    # Same gotcha, the other LIKE wildcard character (_ matches any
    # SINGLE character). "50_" unescaped would match both w3 and w4;
    # escaped, it matches neither (neither name contains a literal "_").
    assert adapter.find_ids_matching_text("Widget", ["name"], "50_", TYPE_CONFIG) == []


def test_no_match_returns_empty_list(adapter):
    assert adapter.find_ids_matching_text("Widget", ["name"], "zzz_nonexistent", TYPE_CONFIG) == []


def test_empty_columns_list_returns_empty_list_without_querying(adapter):
    assert adapter.find_ids_matching_text("Widget", [], "ada", TYPE_CONFIG) == []
