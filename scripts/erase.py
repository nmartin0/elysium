"""Erase a person from everything the mirror holds (R13).

    python -m scripts.erase Customer cust_001 --reason "GDPR request 2026-114"
    python -m scripts.erase Customer cust_001 --reason "..." --write
    python -m scripts.erase --list

Without --write it says what would go -- the object and everything
that links to it, counted per type -- and changes nothing. With it:

  1. the keys are recorded in the erasure register, as salted hashes;
  2. every mirror table is rewritten without them, every older snapshot
     and publication tag holding them is dropped, and the files are
     deleted outright -- time travel included;
  3. every later sync drops them on the way in for as long as the
     source still returns them, and says so;
  4. every store outside the lake forgets them too -- memories, notes,
     frozen sets, the write log, waiting writes, paused questions and
     the notifications answers were built from -- and the audit log
     records that an erasure happened, by type and count, never whom.

Elysium cannot erase the SOURCE -- it only reads it. The report names
what the source still returns after each sync, for the source's owner.

HOLDS THE SYNC LOCK, so no sync is half-way through a table it rewrites.
The server pins the publication it loaded: restart it, or reload
(POST /api/admin/reload), after an erasure.
"""

import argparse
import getpass
import sys
from collections import Counter

from core.deployment_loader import load_deployment, resolve_runtime_paths
from core.intermediate_layer.audit import AuditLog
from core.mirror.catalog import open_mirror_catalog
from core.mirror.erasure import (
    ErasureRegister,
    apply_erasures,
    cascade,
    forget_beyond_the_mirror,
)
from core.mirror.sync_lock import single_writer


def run(object_type: str, object_id: str, reason: str, write: bool = False,
        paths=None, requested_by: "str | None" = None) -> int:
    paths = paths or resolve_runtime_paths()
    config = load_deployment(paths.config_dir)
    if object_type not in config.schema:
        print(f"No object type {object_type!r}.", file=sys.stderr)
        return 1
    if not reason.strip():
        print("An erasure needs a reason: it is the record of why this was done.",
              file=sys.stderr)
        return 1
    mirror_dir = paths.data_dir / "mirror"
    catalog = open_mirror_catalog(mirror_dir, dict(config.mirror_storage))

    with single_writer(paths.data_dir / "sync.lock") as acquired:
        if not acquired:
            print("A sync is running. Try again when it has finished; nothing was erased.")
            return 1
        keys = cascade(catalog, config.schema, [(object_type, object_id)])
        counts = Counter(kind for kind, _ in keys)
        for kind, count in sorted(counts.items()):
            print(f"  {kind}: {count}")
        if not write:
            print("Dry run: nothing was erased. --write to erase.")
            return 0
        register = ErasureRegister(paths.data_dir / "erasures.db")
        who = requested_by or getpass.getuser()
        erasure_id = register.record(keys, who, reason)
        removed = apply_erasures(catalog, config.schema, register, mirror_dir)
        # AND EVERYWHERE ELSE (decided 14 Oct): every store but the audit
        # log, matched by the register's hashes -- the same call a
        # restore makes, so the two cannot forget differently.
        audit = AuditLog(paths.log_dir / "audit.log", generation=config.generation)
        forgotten = forget_beyond_the_mirror(paths.data_dir, register, audit)
        audit.log_erasure(erasure_id, who, dict(counts), forgotten)
    elsewhere = ", ".join(f"{count} {name.replace('_', ' ')}"
                          for name, count in sorted(forgotten.items()) if count)
    print(f"Erased ({erasure_id}): {sum(removed.values())} row(s) from {len(removed)} table(s), "
          f"older snapshots and their files deleted"
          f"{'; and ' + elsewhere if elsewhere else ''}. Restart or reload the server.")
    return 0


def list_erasures(paths=None) -> int:
    """The register, without a single id: what was erased, when, why, by
    whom, whether the mirror has applied it, and whether the source has
    caught up."""
    from datetime import UTC, datetime

    paths = paths or resolve_runtime_paths()

    def when(stamp):
        return "-" if stamp is None else datetime.fromtimestamp(stamp, UTC).isoformat(
            timespec="minutes")

    for erasure in ErasureRegister(paths.data_dir / "erasures.db").erasures():
        print(f"{erasure.erasure_id}  {erasure.object_type:<14} "
              f"requested {when(erasure.requested_at)} by {erasure.requested_by}  "
              f"applied {when(erasure.purged_at)}  source cleared {when(erasure.source_cleared_at)}"
              f"  -- {erasure.reason}")
    return 0


def main() -> int:
    if sys.argv[1:] == ["--list"]:
        return list_erasures()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("object_type")
    parser.add_argument("object_id")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    return run(args.object_type, args.object_id, args.reason, write=args.write)


if __name__ == "__main__":
    sys.exit(main())
