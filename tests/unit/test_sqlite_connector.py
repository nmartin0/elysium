"""Tests for connectors/sqlite_connector.py -- the generic SQLite driver."""

import pytest

from connectors.sqlite_connector import connect, run_query, run_query_one


@pytest.fixture
def conn(test_db_path):
    # One place handling connect/close for every test in this file,
    # instead of each test repeating its own try/finally around a raw
    # connection -- same fix as OntologyEngine._connection() in
    # core/ontology/sql_adapter.py, applied to the test suite itself.
    connection = connect(test_db_path)
    yield connection
    connection.close()


def test_run_query_returns_list_of_dicts(conn):
    rows = run_query(conn, "SELECT author_id, name FROM authors ORDER BY author_id")
    assert rows == [
        {"author_id": "auth_001", "name": "Ada Lovelace"},
        {"author_id": "auth_002", "name": "Grace Hopper"},
    ]


def test_run_query_with_params(conn):
    rows = run_query(conn, "SELECT name FROM authors WHERE author_id = ?", ("auth_001",))
    assert rows == [{"name": "Ada Lovelace"}]


def test_run_query_one_returns_none_when_no_match(conn):
    result = run_query_one(conn, "SELECT * FROM authors WHERE author_id = ?", ("nope",))
    assert result is None
