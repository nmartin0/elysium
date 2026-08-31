"""
audit.py  (the paper trail -- generic, org-agnostic)

A CLASS, not free functions writing to a module-level global LOG_PATH
-- refactored deliberately, not incidentally: the physical log
location is genuinely this object's own state (which file every entry
gets appended to), so it belongs on self, encapsulated the same way
every other per-deployment store in this project now is (see
core/ontology/write_log.py's own module docstring for the identical
reasoning, applied here). A shared, mutable module global caused real,
concrete friction this refactor closes: every test needing an
isolated log had to save the global, mutate it, yield, then restore
it by hand (see the OLD version of tests/conftest.py's
isolated_audit_log fixture) -- a real, ongoing risk of test pollution
or cross-test leakage that a proper instance removes structurally,
not just by convention.

Writes one JSON line per event. Five kinds of entries:

  log_access() -- ONE line per access decision, on EVERY read/write/
               memory check, whether allowed OR denied. Breaks out the
               MAC and RBAC results independently (not just the final
               allow/deny), so a denial's actual cause is visible
               without cross-referencing anything else -- this is what
               closes the long-deferred "auditing isn't connected"
               gap for real, not just for writes.

  log_unknown_reference() -- an object_type/field_name a caller asked
               about that GENUINELY doesn't exist in the schema at
               all -- distinct from log_access()'s "exists but not
               authorized" case. Purely additive alongside
               log_access(), not a replacement for it -- see its own
               docstring for why.

  log_security_resolution_failed() -- a MAC denial caused by the
               object's OWN security value being unresolvable at all
               (e.g. an orphaned MDO record), not an ordinary,
               expected mismatch. Also purely additive alongside
               log_access().

  log_pre()  -- written BEFORE a write executes. What was asked, by
               whom, and whether it was approved. Exists even for
               rejected writes.

  log_post() -- written AFTER a write actually executes. Record ID
               only, never the full data itself.

The unknown_reference/security_resolution_failed distinction follows a
standard security engineering pattern, not a project-specific
invention: fail UNIFORMLY to the requester (this project's existing
"doesn't exist" vs "exists but denied" indistinguishability, by
design), while logging the REAL reason for an operator. The same
separation underlies why AWS IAM returns a generic "Access Denied" to
a caller while recording the specific cause in CloudTrail -- satisfying
fail-safe defaults and auditability as two genuinely separate
concerns, not one.

log_path DOES have a real, class-level default (deployment/var/log/
audit.log, matching local development's own default layout -- see
core/deployment_loader.py's resolve_runtime_paths()), unlike this
project's OTHER per-deployment stores (WriteLog, CredentialStore,
SessionStore, UserDirectory all REQUIRE their own db_path explicitly,
no default at all). This IS a deliberate, narrower exception, not an
inconsistency: audit logging is a core security requirement this
project treats as always-on, never optional (see DataMediator's own
docstring on why audit_log is never None there either), so a
DataMediator/PendingWriteStore constructed without an explicit
AuditLog still logs correctly, to a sensible default location, rather
than either silently doing nothing or forcing every caller (including
every test that has nothing to do with audit logging specifically) to
wire one up by hand. Every OTHER store's default would be meaningless
(there is no sensible "default" credentials.db); this one genuinely
isn't.

No org-specific data lives here -- deployments call these same
methods with their own details as arguments.

Used by: core/ontology/mediator.py (owns the instance directly,
         constructed once via core/deployment_loader.py's
         load_deployment_bundle()), core/intermediate_layer/
         access_control.py (reads it back via the mediator it's
         already given), core/ontology/write_mediator.py and
         core/agent/agentic_loop.py (read it back via
         self.mediator.audit_log), core/pending_write_store.py (holds
         its own explicit reference -- it has no mediator to read one
         from)
"""

import json
from datetime import UTC, datetime
from pathlib import Path

_DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "deployment" / "var" / "log" / "audit.log"


class AuditLog:
    def __init__(self, log_path: Path = _DEFAULT_LOG_PATH):
        self._log_path = log_path

    def _write(self, entry: dict) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        entry["timestamp"] = datetime.now(UTC).isoformat()
        with open(self._log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def log_access(self, user_id: str, object_type: str, object_id, action: str,
                    mac_allowed: bool | None, rbac_allowed: bool) -> None:
        # mac_allowed is bool | None -- None means the MAC check never ran
        # (short-circuited by an earlier RBAC failure), NOT that it ran and
        # failed. Logging a fabricated False for a check that never
        # evaluated would be inaccurate audit data -- arguably worse than
        # not logging it, since it implies something happened that didn't.
        self._write({
            "stage": "access_check",
            "user_id": user_id,
            "object_type": object_type,
            "object_id": object_id,
            "action": action,
            "mac_allowed": mac_allowed,
            "rbac_allowed": rbac_allowed,
            "allowed": bool(mac_allowed) and rbac_allowed,
        })

    def log_unknown_reference(self, user_id: str, object_type: str, field_name: str | None = None) -> None:
        # A get_field()/search_object() request naming an object_type or
        # field_name that GENUINELY does not exist in the schema at all --
        # distinct from log_access()'s "exists but not authorized" case,
        # which already has its own mac_allowed/rbac_allowed breakdown.
        # Without this, an administrator reviewing the log cannot tell "a
        # user was correctly denied a real field they lack permission for"
        # apart from "a model guessed at a field name that was never real"
        # -- both currently produce an IDENTICAL access_check entry
        # (rbac_allowed=False), even though they mean very different
        # things. field_name=None means the object_type ITSELF is unknown;
        # otherwise the type is real but this specific field isn't.
        #
        # Deliberately does NOT replace or reorder the existing
        # access_check entry -- see the module docstring's own reasoning:
        # dropping that entry entirely for an unknown reference would mean
        # LESS trace for exactly the case worth watching most closely, not
        # more. This is purely additive.
        self._write({
            "stage": "unknown_reference",
            "user_id": user_id,
            "object_type": object_type,
            "field_name": field_name,
        })

    def log_security_resolution_failed(self, user_id: str, object_type: str, object_id) -> None:
        # A MAC check that failed for a DIFFERENT reason than the normal,
        # expected one -- the object's own security value could not be
        # resolved AT ALL (DataMediator._get_security_value() itself
        # returned None), rather than resolving to a real value that
        # simply doesn't match the requesting user's own. The clearest real
        # example: an orphaned MDO record with no primary-storage row to
        # read the security field from at all (see
        # tests/unit/test_mdo.py's orphaned-record test) -- a genuine data-
        # integrity signal, not an ordinary permission boundary being
        # correctly enforced. Both currently produce an identical
        # mac_allowed=False in log_access() -- this adds the missing
        # distinction, additively, without changing that existing entry.
        self._write({
            "stage": "security_resolution_failed",
            "user_id": user_id,
            "object_type": object_type,
            "object_id": object_id,
        })

    def log_pre(self, request_id: str, user_id: str, query_text: str,
                action_id: str, params: dict, decision: bool) -> None:
        self._write({
            "stage": "pre",
            "request_id": request_id,
            "user_id": user_id,
            "query_text": query_text,
            "action_id": action_id,
            "params": params,
            "decision": "allow" if decision else "deny",
        })

    def log_post(self, request_id: str, status: str, returned_record_ids: list) -> None:
        self._write({
            "stage": "post",
            "request_id": request_id,
            "status": status,
            "returned_record_ids": returned_record_ids,
            "returned_count": len(returned_record_ids),
        })

    def log_query_cancelled(self, user_id: str, query_text: str, items_gathered: int) -> None:
        # A query that stopped early because the caller detected the
        # requester was gone (e.g. api/routes.py's disconnect watcher) --
        # worth its own clear entry, distinct from normal per-step logging,
        # so it's visible something was cut SHORT, not just silently absent
        # from any results.
        self._write({
            "stage": "query_cancelled",
            "user_id": user_id,
            "query_text": query_text,
            "items_gathered": items_gathered,
        })

    def log_write_expired(self, write_id: str, user_id: str, description: str) -> None:
        # A write that was proposed and never confirmed, until its TTL ran
        # out (see core/pending_write_store.py). Without this, an
        # unconfirmed proposal would simply vanish with no trace once it
        # expires -- a security reviewer should be able to see that this
        # happened, not just find it absent.
        self._write({
            "stage": "write_expired",
            "write_id": write_id,
            "user_id": user_id,
            "description": description,
        })

    def log_write_resume_ambiguous(self, entry_id: str, object_type: str, object_id, field_name: str,
                                    current_value, expected_old_value, expected_new_value) -> None:
        # WriteMediator.resume_pending_writes() found a write_log entry
        # left at status='pending' by a crash mid-apply, and -- for THIS
        # specific field -- the real backend holds a value that is NEITHER
        # the pre-write value the write expected NOR the post-write value
        # it intended to set. Something else touched this field between
        # the crash and recovery (or the write's own precondition was
        # already stale before the crash), and resume deliberately does
        # NOT guess which state is "right" by overwriting either way --
        # see resume_pending_writes()'s own docstring for the full
        # reconciliation logic this is one outcome of. The entry is left
        # 'pending' (get_field() keeps reporting the ORIGINAL intended
        # value for this field, same as before recovery ran at all -- not
        # worse, just not resolved), and this is the trace an operator
        # needs to manually decide what actually happened and fix it by
        # hand. A genuine data-integrity signal, not routine operation --
        # same class of "worth its own distinct entry" as
        # log_security_resolution_failed() above, for the same reason.
        self._write({
            "stage": "write_resume_ambiguous",
            "entry_id": entry_id,
            "object_type": object_type,
            "object_id": object_id,
            "field_name": field_name,
            "current_value": current_value,
            "expected_old_value": expected_old_value,
            "expected_new_value": expected_new_value,
        })
