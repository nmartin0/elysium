"""The production read path's PostgreSQL tests fail rather than skip.

They SKIPPED, silently, from the day the gating machine moved to Python
3.13 -- `pgserver` has no wheel there, and `importorskip` turned that
into green. tests/postgres_server.py now falls back to the machine's
own PostgreSQL and fails when there is none.
"""

import sys

import pytest

import tests.postgres_server as postgres_server


def test_with_no_postgresql_at_all_it_fails_and_says_what_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "pgserver", None)  # import raises ImportError
    monkeypatch.setattr(postgres_server, "_binaries", lambda: None)

    # BaseException, then the TYPE: a skip is also an exception, and
    # `pytest.raises(Failed)` would let a skip escape and report the
    # test as skipped -- green, the very thing this guards against. The
    # control in check_controls.py did not fire until this said so.
    with pytest.raises(BaseException, match="Install PostgreSQL") as raised:
        postgres_server.real_postgres()
    assert raised.type is pytest.fail.Exception


def test_the_server_it_starts_is_a_real_postgresql():
    """THE CONTROL: the fallback is an engine, not a stand-in."""
    import psycopg

    uri, stop = postgres_server.real_postgres()
    try:
        with psycopg.connect(uri) as conn, conn.cursor() as cur:
            cur.execute("SELECT version()")
            assert cur.fetchone()[0].startswith("PostgreSQL ")
    finally:
        stop()
