"""The credentials connection is WRITABLE, and the read paths that use
it are protected by convention rather than by structure (001's F-12b).

WHAT WENT WRONG. login_attempt_tracker.is_locked_out() explained why
it leaves an expired row in place and added: "this is now a
STRUCTURALLY read-only connection besides -- it couldn't delete even
if it tried". It could. `core.auth.database.connection()` reaches
`open_connection()` with `read_only` defaulting to False, which it
MUST, because `connection_with_schema()` runs CREATE TABLE IF NOT
EXISTS and column migrations through the same handle -- and
`record_failure()` on the same class writes through it every failed
login.

WHY A FALSE STRUCTURAL CLAIM IS WORTH A TEST. The engine-enforced
read-only connection is real elsewhere in this project -- an earlier
reviewer executed it against ATTACH and PRAGMA writable_schema and it
held -- so a reader meeting these words in an auth file has every
reason to believe them, and to skip a check they would otherwise make.
A guarantee that does not exist is more dangerous than an
acknowledged convention.

WHAT THIS PINS, AND IN WHICH DIRECTION. It asserts the connection CAN
write. That reads backwards for a security test, and is deliberate:
the claim being guarded against is the FALSE one. If somebody later
makes this handle genuinely read-only, this test fails and sends them
to the two places that depend on it being writable -- the migrations
and record_failure() -- instead of letting a half-change land. Either
the guarantee is real and those move with it, or it is not and nothing
may say it is.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from core.auth.database import connection
from core.auth.login_attempt_tracker import LoginAttemptTracker


@pytest.fixture
def db_path():
    return Path(tempfile.mkdtemp()) / "credentials.db"


def test_the_connection_can_write(db_path):
    """The plain fact the comment denied."""
    with connection(db_path) as conn:
        conn.execute(
            "INSERT INTO login_attempts VALUES ('probe', 1, '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()

    with connection(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE username = 'probe'"
        ).fetchone()[0] == 1


def test_and_it_can_delete(db_path):
    """Verbatim the thing that "couldn't delete even if it tried"."""
    with connection(db_path) as conn:
        conn.execute(
            "INSERT INTO login_attempts VALUES ('probe', 1, '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()
        conn.execute("DELETE FROM login_attempts WHERE username = 'probe'")
        conn.commit()

    with connection(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0] == 0


def test_record_failure_depends_on_that(db_path):
    """THE REASON IT CANNOT SIMPLY BE MADE READ-ONLY. The same helper
    is the write path for every failed login, so a structural
    read-only connection here is not a one-line change."""
    tracker = LoginAttemptTracker(db_path)

    tracker.record_failure("someone")

    with connection(db_path) as conn:
        assert conn.execute(
            "SELECT failed_count FROM login_attempts WHERE username = 'someone'"
        ).fetchone()[0] == 1


def test_is_locked_out_leaves_an_expired_row_alone(db_path):
    """THE BEHAVIOUR THE COMMENT DESCRIBES IS STILL TRUE, and is worth
    keeping true on its own merits -- a read method with a delete in it
    is a surprise. It is a convention, held by this test, and no longer
    claimed to be a guarantee."""
    with connection(db_path) as conn:
        conn.execute(
            "INSERT INTO login_attempts VALUES ('long_gone', 3, '2020-01-01T00:00:00+00:00')"
        )
        conn.commit()

    assert LoginAttemptTracker(db_path).is_locked_out("long_gone") is False

    with connection(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE username = 'long_gone'"
        ).fetchone()[0] == 1, "is_locked_out deleted a row; it is documented as not doing that"


def test_a_genuinely_read_only_connection_would_refuse(db_path):
    """THE CONTROL'S COMPANION: proof that this project's read-only
    mechanism is real and simply is not applied here, so the tests
    above are about THIS handle rather than about SQLite lacking the
    ability. Without it, "the connection can write" could be read as
    "nothing here can ever be protected"."""
    from core.sqlite_connection import open_connection

    with connection(db_path):
        pass  # create the schema first; a read-only handle cannot

    conn = open_connection(db_path, read_only=True)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(
                "INSERT INTO login_attempts VALUES ('x', 1, '2026-01-01T00:00:00+00:00')"
            )
    finally:
        conn.close()
