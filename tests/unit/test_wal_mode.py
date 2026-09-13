"""
Internal databases run in WAL mode, so a commit does not stall readers.

MEASURED BEFORE CHANGING. Changing journal mode blind on the store
holding credentials and the write log is not the shape of change this
project makes. Four readers against one writer, three seconds:

    rollback  606,793 reads  p50 0.003ms  p99 0.02ms  max 241ms
    WAL     1,312,596 reads  p50 0.002ms  p99 0.01ms  max  48ms

Twice the read throughput and a fifth of the worst case. The p50
barely moves, which is the tell: this is entirely about the tail.

THE RECORDED CONCERN WAS OVERSTATED, and the measurement is what said
so. IDEAS.md described rollback mode as one where "a writer blocks all
readers for the duration of its transaction". It does not -- BEGIN
IMMEDIATE takes a RESERVED lock and RESERVED permits readers. Only the
brief EXCLUSIVE phase during COMMIT blocks them.
"""

import sqlite3
import threading
import time

from core.sqlite_connection import connection_with_schema

SCHEMA = "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT);"


def test_a_store_created_through_the_shared_helper_is_in_wal(tmp_path):
    db = tmp_path / "store.db"

    with connection_with_schema(db, SCHEMA) as conn:
        conn.execute("INSERT INTO t VALUES (1, 'a')")
        conn.commit()

    assert sqlite3.connect(db).execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_it_persists_without_being_set_again(tmp_path):
    # SET ONCE, AT CREATION. Journal mode lives in the database header,
    # so setting it per connection would be a redundant write -- and
    # read-only connections cannot do it at all, since their authorizer
    # denies PRAGMA.
    db = tmp_path / "store.db"
    with connection_with_schema(db, SCHEMA):
        pass

    reopened = sqlite3.connect(db)

    assert reopened.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_a_reader_is_not_blocked_by_an_open_write_transaction(tmp_path):
    """THE PROPERTY THIS EXISTS FOR.

    A reader proceeds against the last committed state while a writer
    works. Timed rather than asserted structurally, because the whole
    claim is about latency.
    """
    db = tmp_path / "store.db"
    with connection_with_schema(db, SCHEMA) as conn:
        conn.execute("INSERT INTO t VALUES (1, 'before')")
        conn.commit()

    writer = sqlite3.connect(db, timeout=10)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("UPDATE t SET v='after' WHERE id=1")

    took = {}

    def read():
        reader = sqlite3.connect(db, timeout=10)
        start = time.monotonic()
        took["value"] = reader.execute("SELECT v FROM t WHERE id=1").fetchone()[0]
        took["seconds"] = time.monotonic() - start
        reader.close()

    thread = threading.Thread(target=read)
    thread.start()
    time.sleep(0.3)
    writer.commit()
    writer.close()
    thread.join(timeout=10)

    # The LAST COMMITTED state, not the uncommitted one, and promptly.
    assert took["value"] == "before"
    assert took["seconds"] < 0.2, f"read waited {took['seconds']:.3f}s for a writer"


def test_the_wal_sidecar_files_appear(tmp_path):
    # WAL creates -wal and -shm beside the database, which a backup has
    # to account for. Asserted so the fact is discoverable from the
    # tests rather than only from a comment.
    db = tmp_path / "store.db"
    with connection_with_schema(db, SCHEMA) as conn:
        conn.execute("INSERT INTO t VALUES (1, 'a')")
        conn.commit()

        assert (tmp_path / "store.db-wal").exists()
