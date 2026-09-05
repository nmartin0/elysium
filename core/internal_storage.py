"""
internal_storage.py  (base classes for Elysium's OWN internal storage
that genuinely needs a read/write split)

InternalReadAdapter gives a structurally read-only connection
(core/sqlite_connection.py's open_connection(read_only=True), enforced
by SQLite itself); InternalWriteAdapter gives a write-capable one.

DELIBERATELY NARROW SCOPE, corrected after over-applying it. Four auth
stores (CredentialStore, SessionStore, LoginAttemptTracker,
QueryRateLimiter) were briefly split into Reader/Writer pairs on this
base and then reverted -- the split was pattern-matching, not a real
requirement. Each produced classes holding a single method and forced
every caller to pick a half, for a failure mode that was never real:
these tables are Elysium's own, written only by Elysium, with no third
party to protect.

The real guarantee that motivated all of this is about the CUSTOMER'S
OWN external database -- someone else's production system, which our
read path must be structurally incapable of writing to. That lives in
core/ontology/interface.py and adapters/sqlite_adapter.py, not here.

The one internal store that DOES earn a split is WriteLog: DataMediator
consults it on every single field read, and it holds write-intent state
the read path must never mutate. See core/ontology/write_log.py.

Before adding a split here, the question to answer is what real failure
it prevents -- not whether it matches a pattern used elsewhere.
"""

from contextlib import contextmanager
from pathlib import Path

from core.adapter_roles import ReadAdapter, WriteAdapter
from core.sqlite_connection import open_connection


class InternalReadAdapter(ReadAdapter):
    def __init__(self, db_path: Path):
        self.db_path = db_path

    @contextmanager
    def _connection(self):
        # read_only=True -- a real, structural, SQLite-engine-enforced
        # guarantee (core/sqlite_connection.py's own open_connection(),
        # confirmed directly, empirically, before being relied on
        # anywhere in this project). NEVER responsible for schema
        # creation -- CREATE TABLE is itself a write-type operation
        # the authorizer denies same as any other, so the real
        # database file this points at must already have its real
        # schema in place before a Reader for it is ever constructed.
        # This is a genuine, load-bearing startup-ordering requirement,
        # not a hypothetical: see api/app.py's own explicit schema-
        # creation step, run once at real app startup, before either
        # half of any internal store is constructed.
        conn = open_connection(self.db_path, read_only=True)
        try:
            yield conn
        finally:
            conn.close()


class InternalWriteAdapter(WriteAdapter):
    def __init__(self, db_path: Path):
        self.db_path = db_path

    @contextmanager
    def _connection(self):
        conn = open_connection(self.db_path)
        try:
            yield conn
        finally:
            conn.close()
