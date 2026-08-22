"""
audit.py  (the paper trail -- generic, org-agnostic)

Writes one JSON line per event to logs/audit.log at the project root.
Two kinds of entries:

  log_pre()  -- written BEFORE the adapter runs. What was asked, by whom,
               and whether it was allowed. Exists even for denied requests.

  log_post() -- written AFTER the adapter returns. Record IDs only, never
               the full data itself.

No org-specific data lives here -- deployments call these same functions
with their own request/user/action details as arguments.

Called by: gateway.py (once before dispatch, once after)
"""

import json
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "logs" / "audit.log"


def _write(entry: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


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
