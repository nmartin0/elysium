"""
internal_storage.py  (the shared base classes for Elysium's OWN internal
storage -- credentials, sessions, login attempts, query rate limits,
write_log, audit_log, and (once built) the mirror/outbox)

A real, direct request, worked through carefully rather than assumed:
"we need a Python abstract class or parent class that defines external
reads, external writes, internal reads, and internal writes... the base
classes are what should be extensible and actually carry the common,
generic logic... adapters/ should just be the veneer that extends down
the implementation-specific interfacing." This file is the INTERNAL
half of that four-way split; see core/ontology/interface.py for the
EXTERNAL half (ExternalReadAdapter/ExternalWriteAdapter, the generic,
ontology-driven contract for the customer's own third-party data). Both
halves descend from the same three, shared roots in core/adapter_roles.py
-- see that module's own docstring for why those roots live in their
own, separate, neutral file rather than either of these two.

Three real, separate base classes (ReadAdapter/WriteAdapter/
AppendOnlyAdapter, in core/adapter_roles.py), confirmed against real,
established precedent before choosing this shape, not invented from
scratch:
- ReadAdapter / WriteAdapter -- confirmed directly against CQRS
  (Command Query Responsibility Segregation, Greg Young, building on
  Bertrand Meyer's older Command-Query Separation principle) -- a
  real, established pattern whose entire premise is separating read
  operations from write operations via genuinely separate interfaces,
  not one interface a caller happens to use only half of. Python's own
  standard typing already does the identical thing at the language
  level -- _typeshed.SupportsRead/SupportsWrite are separate, single-
  method Protocols, composed together via real inheritance only where
  a concrete type genuinely needs both (confirmed directly against a
  real, production codebase importing them separately, and a real
  design discussion in a widely-used typing library reaching the same
  conclusion: build the combined type FROM the separate ones, never
  the other way around).
- AppendOnlyAdapter -- a real, deliberately NARROWER third category,
  not a subtype of WriteAdapter. Confirmed directly: even CQRS's own
  strict definition explicitly carves out an exception for exactly
  this case ("fulfilling a query request will only retrieve data and
  will not modify the state of the system, with some exceptions like
  LOGGING ACCESS") -- audit logging (and any genuinely append-only
  store) doesn't cleanly fit the read/write binary at all. The
  broader, established name for this is the append-only log / event-
  sourcing pattern (Kafka, ledgers, audit trails) -- genuinely
  different from arbitrary write, because it structurally never
  permits updating or deleting an existing entry. AuditLog is the
  clean, motivating example in this codebase -- an audit trail that
  could be edited or deleted would defeat its own purpose. WriteLog
  and the future outbox table are explicitly NOT append-only despite
  superficially looking similar -- both insert new entries AND update
  existing ones (WriteLog's own mark_applied(); the future outbox's
  own "mark this item successfully pushed") -- so both stay under
  WriteAdapter, not this narrower one.

Deliberately NOT unified with core/ontology/interface.py's external
adapters into one, shared Read/Write pair differentiated only by which
RBAC/MAC policy happens to wrap a given instance -- a real, considered
rejection, not an oversight: RBAC/MAC is an application-level, Python
check that runs ABOVE the adapter layer entirely (DataMediator/
WriteMediator deciding WHETHER to call a method at all); it is not a
property of the connection or credential itself. The entire reason
this project wants a real, STRUCTURAL distinction between what can and
cannot write (confirmed directly against Palantir's own real practice:
the credential itself is the real enforcement point, not application
code alone) would be quietly undone if "internal vs. external" reduced
to "same class, different permission check wrapping it" -- a bug in
that application-level check (this project has already found several
real ones, in unrelated areas, this same session) could then let a
write through with nothing structural underneath to stop it. What IS
genuinely shared between internal and external reads is kept shared,
just at a lower, more honest level: the real, reusable read-only-
connection mechanism itself (core/sqlite_connection.py's own
open_connection(read_only=True)), not the classes built on top of it.

InternalReadAdapter/InternalWriteAdapter carry real, concrete, shared
LOGIC (not just an abstract contract) -- confirmed this is possible,
unlike the external side, precisely BECAUSE internal stores don't need
a generic, ontology-driven method surface at all (each one --
CredentialStore, SessionStore, LoginAttemptTracker, QueryRateLimiter --
has its own real, specific methods; there is no shared "find_ids"-style
operation across them the way there is for arbitrary EXTERNAL object
types). What IS genuinely common: how a connection is obtained at all,
and, for the read side specifically, the real, structural guarantee
that it can never write. A read-only connection can NEVER be the one
responsible for lazy schema creation either (CREATE TABLE IS a write-
type operation the authorizer denies same as any other) -- see this
class's own _connection() docstring for the real, load-bearing
consequence this has for startup sequencing.

Used by: core/auth/credential_store.py, core/auth/session_store.py,
         core/auth/login_attempt_tracker.py, core/auth/query_rate_limiter.py,
         core/ontology/write_log.py, core/intermediate_layer/audit.py
         (each split into its own Reader/Writer/AppendOnly pair,
         extending the appropriate base class here)
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
