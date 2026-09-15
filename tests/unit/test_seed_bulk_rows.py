"""
Extra rows for a browser, without changing what the tests see.

WHY A FLAG AND NOT THE FIXTURE. seed_dev_silos.py's own comment states
the constraint: the databases it builds match the integration fixtures
"so a developer's server and the test suite disagree about nothing".

Tests want small, deterministic data -- several assert exact counts.
A browser wants enough rows to page: the server's default page size is
50, and alice could see 4 transactions, so nothing in the UI could
reach a second page. A visual check of paging was literally unaskable.

Opt-in keeps both.
"""

import sqlite3
from pathlib import Path

from scripts.seed_dev_silos import FIXTURES, build

SCHEMA = FIXTURES / "schema.sql"


def _transaction_count(db_path: Path) -> int:
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute("SELECT count(*) FROM transactions").fetchone()[0]
    finally:
        connection.close()


def test_the_default_leaves_the_fixture_alone(tmp_path):
    """THE CONTROL, and the one that protects every other test.

    A default that added rows would break the suite's own count
    assertions, quietly, in a file nobody reads while debugging them.
    """
    db_path = tmp_path / "mediator.db"
    build(SCHEMA, db_path)

    assert _transaction_count(db_path) == 7


def test_bulk_adds_the_requested_number(tmp_path):
    db_path = tmp_path / "mediator.db"
    build(SCHEMA, db_path, bulk=60)

    assert _transaction_count(db_path) == 67


def test_bulk_rows_are_visible_to_the_development_user(tmp_path):
    """ON CUSTOMERS alice CAN SEE, which is the point of the exercise.

    Rows filed under a region she cannot read are filtered out by MAC
    before reaching the page -- giving a list that is still short and a
    developer who concludes paging is broken.
    """
    db_path = tmp_path / "mediator.db"
    build(SCHEMA, db_path, bulk=60)

    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT count(*) FROM transactions t JOIN customers c "
            "ON c.customer_id = t.customer_id WHERE c.region = 'us-west'"
        ).fetchone()[0]
    finally:
        connection.close()

    # Enough to exceed the server's default page size of 50, which is
    # the whole reason the flag exists.
    assert rows > 50


def test_bulk_rows_do_not_touch_the_other_silos(tmp_path):
    # Only the mediator database has a transactions table; asking the
    # others for one would fail loudly, and silently skipping the
    # insert is what keeps the flag safe to pass to every build.
    db_path = tmp_path / "support.db"
    build(FIXTURES / "support_schema.sql", db_path, bulk=60)

    connection = sqlite3.connect(db_path)
    try:
        tables = {
            row[0] for row in
            connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        connection.close()

    assert "transactions" not in tables


def test_zero_is_the_same_as_absent(tmp_path):
    db_path = tmp_path / "mediator.db"
    build(SCHEMA, db_path, bulk=0)

    assert _transaction_count(db_path) == 7
