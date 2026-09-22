"""Finds 'create' entries in the write log that crash recovery fabricated.

READ-ONLY. It opens write_log.db with SQLite's mode=ro, so it cannot
change the database -- and cannot create an empty one at a mistyped
path, which opening one read-write would.

WHAT IT CAN LEAVE BEHIND: write_log.db-shm and an empty -wal. The log is
in WAL mode, and SQLite needs its shared-memory file even to READ; a
read-only connection cannot remove it on close. Neither holds data --
the -wal is empty -- and the application tidies them on its next clean
open. Measured on this deployment's own log: the database file's bytes
and timestamp unchanged, the two sidecars created.

WHY THEY EXIST (001's F-27, fixed in patch 311). Crash recovery used to
dispatch two ways over three operations, so a resumed DELETE fell into
the create branch: the delete was lost, recovery reported success, and
the log gained an applied 'create' with EMPTY changes. Nothing else
produces one -- a real create must carry its id field, which
_expected_current_values_for() checks -- so an applied create with {}
changes is a fabrication.

WHAT TO DO WITH ONE. Each marks a delete that was lost: the object is
still visible though somebody deleted it. Check with whoever made the
delete (the description and user are printed) before acting, and do NOT
rebuild the deleted index from this log until they are dealt with --
the fabricated 'create' is the latest operation for its object, so a
rebuild would cement the object as NOT deleted.

Usage:
    python -m scripts.find_fabricated_creates [--data-dir DIR]

Exits 0 if none are found, 1 if any are, 2 if there is no write log.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def find_fabricated_creates(write_log_path: Path) -> list[dict]:
    """Every applied 'create' whose changes are empty. Opens read-only."""
    uri = f"file:{write_log_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, object_type, object_id, changes, user_id, description, "
            "created_at, batch_id FROM write_log "
            "WHERE operation = 'create' AND status = 'applied' "
            "ORDER BY created_at, id"
        ).fetchall()
    finally:
        conn.close()
    # PARSED, not compared as text: '{}' and '{ }' are both empty, and a
    # string comparison would miss the second.
    return [dict(row) for row in rows if json.loads(row["changes"]) == {}]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="the deployment's data directory (default: this deployment's)")
    args = parser.parse_args()
    if args.data_dir is None:
        from core.deployment_loader import resolve_runtime_paths
        args.data_dir = Path(resolve_runtime_paths().data_dir)

    path = args.data_dir / "write_log.db"
    if not path.exists():
        print(f"No write log at {path}.", file=sys.stderr)
        return 2

    found = find_fabricated_creates(path)
    if not found:
        print(f"No fabricated creates in {path}.")
        return 0
    print(f"{len(found)} fabricated create(s) in {path} -- each marks a LOST DELETE:")
    for entry in found:
        print(f"  {entry['created_at']}  {entry['object_type']} {entry['object_id']!r}  "
              f"by {entry['user_id']}: {entry['description']!r}  (entry {entry['id']})")
    print("\nDo not rebuild the deleted index until these are resolved.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
