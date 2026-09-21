"""Changes to a role, proposed by one person and approved by another.

FOUNDRY'S MODEL. Security changes are approval requests -- "Group
membership: Add a user as a member of a group", decided by somebody
with Manage permissions -- and changes to access policy "require
approval from a user... other than the change request author". So a
role edit here is a PROPOSAL, and its author cannot approve it.

NOT THE PENDING-WRITE QUEUE. That queue carries ontology writes,
executed by the write mediator; a role change is a different thing with
a different executor. Folding it in would add risk to the store under
every approval. Foundry keeps group membership as its own task type too.

ONE ROLE PER CHANGE. The approver sees exactly one role before and
after, which is what they are agreeing to.

THE GUARDS, and what each prevents:

  FOUR-EYES      the author cannot approve their own change
  STALE          a role changed since the proposal is refused, so an
                 approver never agrees to a merge nobody reviewed
  VALID          the resulting SET must pass the same validators
                 loading uses -- at proposal and again at approval
  NO LOCKOUT     some ACTIVE user must still hold a role granting
                 manage:roles. Once the store governs, policy.yaml
                 cannot rescue a deployment that locked itself out
  NOT STRANDED   a role ANY account holds cannot be deleted -- a
                 disabled one included, since it can be re-enabled
  OWN GRANT      a proposer cannot remove manage:roles from their own
                 role -- the commonest way to lock yourself out

THE TABLE IS THE AUDIT TRAIL: who proposed, who decided, the grants
before and after, and how it ended. Rows are never deleted.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.sqlite_connection import connection_with_schema

MANAGE_ROLES = "manage:roles"

SCHEMA = """
CREATE TABLE IF NOT EXISTS role_changes (
    change_id TEXT PRIMARY KEY,
    role_name TEXT NOT NULL,
    -- The role's grants when proposed; NULL when the change creates it.
    before TEXT,
    -- The grants proposed; NULL when the change deletes the role.
    after TEXT,
    proposed_by TEXT NOT NULL,
    proposed_at TEXT NOT NULL,
    -- pending, applied, rejected, stale, or failed.
    status TEXT NOT NULL DEFAULT 'pending',
    decided_by TEXT,
    decided_at TEXT,
    detail TEXT
);
"""


@dataclass(frozen=True)
class RoleChange:
    change_id: str
    role_name: str
    before: list | None
    after: list | None
    proposed_by: str
    proposed_at: str
    status: str
    decided_by: str | None
    decided_at: str | None
    detail: str | None


class RoleChangeStore:
    """Proposed role changes and how each one ended.

    IN roles.db, beside the roles themselves. Proposing creates the file
    without seeding it, so policy.yaml stays in force until something
    is actually APPROVED.
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def propose(self, role_name: str, before: list | None, after: list | None,
                proposed_by: str) -> str:
        change_id = str(uuid.uuid4())
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO role_changes (change_id, role_name, before, after, "
                "proposed_by, proposed_at) VALUES (?, ?, ?, ?, ?, ?)",
                (change_id, role_name, _dump(before), _dump(after),
                 proposed_by, datetime.now(UTC).isoformat()),
            )
            conn.commit()
        return change_id

    def get(self, change_id: str) -> RoleChange | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM role_changes WHERE change_id = ?", (change_id,),
            ).fetchone()
        return _row(row) if row else None

    def pending(self) -> list[RoleChange]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM role_changes WHERE status = 'pending' "
                "ORDER BY proposed_at",
            ).fetchall()
        return [_row(row) for row in rows]

    def decide(self, change_id: str, status: str, decided_by: str,
               detail: str | None = None) -> bool:
        """Records how a change ended. Only a PENDING one can end.

        `AND status = 'pending'` IN THE UPDATE, so two approvers acting
        at once cannot both decide it: one matches, the other matches
        nothing -- the same claim the pending-write store uses.
        """
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE role_changes SET status = ?, decided_by = ?, "
                "decided_at = ?, detail = ? WHERE change_id = ? "
                "AND status = 'pending'",
                (status, decided_by, datetime.now(UTC).isoformat(), detail,
                 change_id),
            ).rowcount
            conn.commit()
        return changed == 1


def _dump(grants: list | None) -> str | None:
    return None if grants is None else json.dumps(sorted(grants))


def _row(row) -> RoleChange:
    return RoleChange(
        row["change_id"], row["role_name"],
        None if row["before"] is None else json.loads(row["before"]),
        None if row["after"] is None else json.loads(row["after"]),
        row["proposed_by"], row["proposed_at"], row["status"],
        row["decided_by"], row["decided_at"], row["detail"],
    )


def grants_of(roles, role_name: str) -> list | None:
    """A role's grants, sorted, or None if it does not exist."""
    if role_name not in roles:
        return None
    return sorted(roles[role_name].get("allowed_actions", ()))


def resulting_roles(roles, role_name: str, after: list | None) -> dict:
    """Every role, raw, with one changed -- or removed, if `after` is None."""
    result = {
        name: {**dict(role), "allowed_actions": sorted(role.get("allowed_actions", ()))}
        for name, role in roles.items()
    }
    if after is None:
        result.pop(role_name, None)
    else:
        result[role_name] = {**result.get(role_name, {}), "allowed_actions": sorted(after)}
    return result


def change_problem(roles, role_name: str, after: list | None,
                   holders: dict[str, int], active_holders: dict[str, int],
                   validate: Callable[[dict], None]) -> str | None:
    """Why this change may not happen, or None. Asked at BOTH ends.

    TWO COUNTS OF HOLDERS, because they answer two questions.

      `holders` counts EVERY account holding a role, disabled ones
      included -- for STRANDING. A disabled account can be re-enabled,
      and would come back holding a role that no longer exists.

      `active_holders` counts only enabled ones -- for LOCKOUT. A
      disabled account cannot edit anything, so it cannot keep a
      deployment able to edit roles.

    One map used to answer both, and the active-only count let a role
    held only by disabled accounts be deleted: re-enable one and it was
    stranded. Not a race -- it happened every time.

    `validate` runs the same validators loading uses, and raises
    ValueError.
    """
    if after is None and holders.get(role_name, 0) > 0:
        return (
            f"{holders[role_name]} account(s) hold {role_name!r}, counting "
            f"disabled ones -- which can be re-enabled. Move them to another "
            f"role before deleting it."
        )

    result = resulting_roles(roles, role_name, after)
    try:
        validate(result)
    except ValueError as e:
        return str(e)

    if not any(
        MANAGE_ROLES in role["allowed_actions"] and active_holders.get(name, 0) > 0
        for name, role in result.items()
    ):
        return (
            "After this change no active user could edit roles. Once roles "
            "live in the store, policy.yaml cannot restore that -- so it is "
            "refused."
        )
    return None


def proposal_problem(roles, role_name: str, after: list | None, proposer_role: str | None,
                     holders: dict[str, int], active_holders: dict[str, int],
                     validate: Callable[[dict], None]) -> str | None:
    """change_problem, plus what only the PROPOSER is refused."""
    if (
        role_name == proposer_role
        and (after is None or MANAGE_ROLES not in after)
    ):
        return (
            f"This would remove {MANAGE_ROLES} from your own role. Ask "
            f"somebody else to propose it, so it is not the last thing you do."
        )
    if after is not None and grants_of(roles, role_name) == sorted(after):
        return f"{role_name!r} already has exactly these grants."
    return change_problem(roles, role_name, after, holders, active_holders, validate)


def approval_problem(change: RoleChange, approver: str, roles, holders: dict[str, int],
                     active_holders: dict[str, int],
                     validate: Callable[[dict], None]) -> tuple[str, str] | None:
    """Why this approval may not happen, as (status_to_record, reason).

    The STATUS matters: a stale change is recorded as stale, so the
    trail says why it never took effect. An approval refused for a
    reason that might pass later -- four-eyes -- records nothing.
    """
    if change.status != "pending":
        return ("", f"This change was already {change.status}.")
    if approver == change.proposed_by:
        # FOUR-EYES. Not recorded: somebody else may still approve it.
        return ("", "You proposed this change; somebody else must approve it.")
    if grants_of(roles, change.role_name) != change.before:
        return (
            "stale",
            f"{change.role_name!r} has changed since this was proposed. Propose "
            f"it again against what is in force now.",
        )
    problem = change_problem(
        roles, change.role_name, change.after, holders, active_holders, validate,
    )
    if problem is not None:
        return ("stale", problem)
    return None
