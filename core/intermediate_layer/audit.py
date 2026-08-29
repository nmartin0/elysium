"""
audit.py  (the paper trail -- generic, org-agnostic)

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

LOG_PATH has a real, working default (deployment/var/log/audit.log,
matching local development's own default layout -- see
core/deployment_loader.py's resolve_runtime_paths()) so this module
works correctly even if nothing ever calls configure_audit_log()
explicitly. configure_audit_log() is how an entry point (scripts/
run_deployment.py, api/app.py) points this at a real install's actual
log directory -- this module never reads an environment variable
itself; that would be exactly the kind of implicit, ambient
configuration core/logging_config.py's configure_logging() already
established the pattern of avoiding. One canonical resolver
(resolve_runtime_paths()) decides the real path; every module that
needs it is told explicitly, once, by whichever entry point is running.

No org-specific data lives here -- deployments call these same
functions with their own details as arguments.

Called by: core/intermediate_layer/access_control.py (log_access,
           log_security_resolution_failed, on every check),
           core/ontology/mediator.py (log_unknown_reference, on every
           read/search naming something that doesn't exist),
           core/ontology/write_mediator.py (log_pre/log_post, on every
           write attempt)
"""

import json
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "deployment" / "var" / "log" / "audit.log"


def configure_audit_log(log_dir: Path) -> None:
    # Called once, at the start of a real entry point -- same pattern
    # as core/logging_config.py's configure_logging(). Library code
    # never calls this itself.
    global LOG_PATH
    LOG_PATH = log_dir / "audit.log"


def _write(entry: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def log_access(user_id: str, object_type: str, object_id, action: str,
                mac_allowed: bool | None, rbac_allowed: bool) -> None:
    # mac_allowed is bool | None -- None means the MAC check never ran
    # (short-circuited by an earlier RBAC failure), NOT that it ran and
    # failed. Logging a fabricated False for a check that never
    # evaluated would be inaccurate audit data -- arguably worse than
    # not logging it, since it implies something happened that didn't.
    _write({
        "stage": "access_check",
        "user_id": user_id,
        "object_type": object_type,
        "object_id": object_id,
        "action": action,
        "mac_allowed": mac_allowed,
        "rbac_allowed": rbac_allowed,
        "allowed": bool(mac_allowed) and rbac_allowed,
    })


def log_unknown_reference(user_id: str, object_type: str, field_name: str | None = None) -> None:
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
    _write({
        "stage": "unknown_reference",
        "user_id": user_id,
        "object_type": object_type,
        "field_name": field_name,
    })


def log_security_resolution_failed(user_id: str, object_type: str, object_id) -> None:
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
    _write({
        "stage": "security_resolution_failed",
        "user_id": user_id,
        "object_type": object_type,
        "object_id": object_id,
    })


def log_pre(request_id: str, user_id: str, query_text: str,
            action_id: str, params: dict, decision: bool) -> None:
    _write({
        "stage": "pre",
        "request_id": request_id,
        "user_id": user_id,
        "query_text": query_text,
        "action_id": action_id,
        "params": params,
        "decision": "allow" if decision else "deny",
    })


def log_post(request_id: str, status: str, returned_record_ids: list) -> None:
    _write({
        "stage": "post",
        "request_id": request_id,
        "status": status,
        "returned_record_ids": returned_record_ids,
        "returned_count": len(returned_record_ids),
    })


def log_query_cancelled(user_id: str, query_text: str, items_gathered: int) -> None:
    # A query that stopped early because the caller detected the
    # requester was gone (e.g. api/routes.py's disconnect watcher) --
    # worth its own clear entry, distinct from normal per-step logging,
    # so it's visible something was cut SHORT, not just silently absent
    # from any results.
    _write({
        "stage": "query_cancelled",
        "user_id": user_id,
        "query_text": query_text,
        "items_gathered": items_gathered,
    })


def log_write_expired(write_id: str, user_id: str, description: str) -> None:
    # A write that was proposed and never confirmed, until its TTL ran
    # out (see core/pending_write_store.py). Without this, an
    # unconfirmed proposal would simply vanish with no trace once it
    # expires -- a security reviewer should be able to see that this
    # happened, not just find it absent.
    _write({
        "stage": "write_expired",
        "write_id": write_id,
        "user_id": user_id,
        "description": description,
    })
