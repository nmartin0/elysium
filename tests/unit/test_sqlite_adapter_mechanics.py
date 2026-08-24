"""
Tests for adapters/sqlite_adapter.py's private low-level mechanics
(_connect/_run_query/_run_query_one) -- the raw SQL execution primitives,
tested in isolation from SQLiteAdapter's DataSiloAdapter-contract methods.
This coverage used to test connectors/sqlite_connector.py directly;
that module was merged into sqlite_adapter.py (see that file's
docstring for why), so this file moved and its imports updated to match.
"""

import pytest

from adapters.sqlite_adapter import _connect, _run_query, _run_query_one


@pytest.fixture
def conn(test_db_path):
    connection = _connect(test_db_path)
    yield connection
    connection.close()


def test_run_query_returns_list_of_dicts(conn):
    rows = _run_query(conn, "SELECT author_id, name FROM authors ORDER BY author_id")
    assert rows == [
        {"author_id": "auth_001", "name": "Ada Lovelace"},
        {"author_id": "auth_002", "name": "Grace Hopper"},
    ]


def test_run_query_with_params(conn):
    rows = _run_query(conn, "SELECT name FROM authors WHERE author_id = ?", ("auth_001",))
    assert rows == [{"name": "Ada Lovelace"}]


def test_run_query_one_returns_none_when_no_match(conn):
    result = _run_query_one(conn, "SELECT * FROM authors WHERE author_id = ?", ("nope",))
    assert result is None
