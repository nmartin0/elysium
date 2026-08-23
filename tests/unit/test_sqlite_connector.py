"""Tests for connectors/sqlite_connector.py -- the generic SQLite driver."""

from connectors.sqlite_connector import connect, run_query, run_query_one


def test_run_query_returns_list_of_dicts(test_db_path):
    conn = connect(test_db_path)
    try:
        rows = run_query(conn, "SELECT author_id, name FROM authors ORDER BY author_id")
        assert rows == [
            {"author_id": "auth_001", "name": "Ada Lovelace"},
            {"author_id": "auth_002", "name": "Grace Hopper"},
        ]
    finally:
        conn.close()


def test_run_query_with_params(test_db_path):
    conn = connect(test_db_path)
    try:
        rows = run_query(conn, "SELECT name FROM authors WHERE author_id = ?", ("auth_001",))
        assert rows == [{"name": "Ada Lovelace"}]
    finally:
        conn.close()


def test_run_query_one_returns_none_when_no_match(test_db_path):
    conn = connect(test_db_path)
    try:
        result = run_query_one(conn, "SELECT * FROM authors WHERE author_id = ?", ("nope",))
        assert result is None
    finally:
        conn.close()
