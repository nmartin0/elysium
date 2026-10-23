"""A database file deleted and made again at the same path gets its tables
again (core/sqlite_connection.connection_with_schema).

The schema is run once per path per process, and remembered by path. A
file removed and recreated at that path -- a test's temporary directory
reused once pytest removes a passing test's, an operator deleting a store
to start it afresh -- was opened empty with its tables skipped: "no such
table: generation_sequence", 11 errors in test_api.py the day passing
tests' directories began to be removed (23 October)."""

from core.sqlite_connection import connection_with_schema

SCHEMA = "CREATE TABLE IF NOT EXISTS things (id INTEGER PRIMARY KEY);"


def test_a_store_deleted_and_opened_again_has_its_tables(tmp_path):
    path = tmp_path / "store.db"
    with connection_with_schema(path, SCHEMA) as conn:
        conn.execute("INSERT INTO things DEFAULT VALUES")
        conn.commit()
    for sidecar in tmp_path.iterdir():
        sidecar.unlink()

    with connection_with_schema(path, SCHEMA) as conn:
        assert conn.execute("SELECT count(*) FROM things").fetchone()[0] == 0
