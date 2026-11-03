"""Erase a person from everything the mirror holds (R13).

    python -m scripts.erase Customer cust_001 --reason "GDPR request 2026-114"
    python -m scripts.erase Customer cust_001 --reason "..." --write
    python -m scripts.erase --list
    python -m scripts.erase --adopt bronze_primary_sql.tags --keys tag_id=Tag [--ids tag_id=Tag]
    python -m scripts.erase --adopt-none primary_sql.audit_notes

--adopt is the operator's statement about ONE lake table written before
its key columns were recorded: these columns hold these types' ids
(--links column=Owner:Target names a removed type's links). No sync can
know what a type removed earlier kept in such a table, so no sync stops it
being "partly known"; this does. --adopt-none says it holds no person's id.

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
    ADOPT_HINT,
    PART_MARK,
    ErasureRegister,
    adopt_table,
    apply_erasures,
    cascade,
    forget_beyond_the_mirror,
    gap_notice,
    recorded_object_types,
    survey,
)
from core.mirror.sync_lock import single_writer


def run(object_type: str, object_id: str, reason: str, write: bool = False,
        paths=None, requested_by: "str | None" = None) -> int:
    paths = paths or resolve_runtime_paths()
    config = load_deployment(paths.config_dir)
    if not reason.strip():
        print("An erasure needs a reason: it is the record of why this was done.",
              file=sys.stderr)
        return 1
    mirror_dir = paths.data_dir / "mirror"
    catalog = open_mirror_catalog(mirror_dir, dict(config.mirror_storage))
    # A TYPE REMOVED FROM THE ONTOLOGY is still a type whose people the lake
    # holds: its tables say so (core/mirror/erasure.KEY_COLUMNS_PROPERTY).
    if object_type not in config.schema and object_type not in recorded_object_types(catalog):
        print(f"{object_type!r} is not an object type of the ontology, and no table in the lake "
              f"records holding its ids.", file=sys.stderr)
        unsearchable = survey(catalog, config.schema).unreachable
        if unsearchable:
            print("If it was removed, its tables may still hold people. Erasure cannot search these, "
                  "which hold data and record no key columns: "
                  + ", ".join(f"{name} ({why})" for name, why in sorted(unsearchable.items()))
                  + f". Restore the type and sync, or {ADOPT_HINT}.", file=sys.stderr)
        return 1

    with single_writer(paths.data_dir / "sync.lock") as acquired:
        if not acquired:
            print("A sync is running. Try again when it has finished; nothing was erased.")
            return 1
        keys = cascade(catalog, config.schema, [(object_type, object_id)])
        counts = Counter(kind for kind, _ in keys)
        for kind, count in sorted(counts.items()):
            print(f"  {kind}: {count}")
        if not write:
            # SO --write IS NOT A SURPRISE: what it would not be able to search.
            for line in gap_notice(survey(catalog, config.schema, set(counts))):
                print(f"  WARNING {line}")
            print("Dry run: nothing was erased. --write to erase.")
            return 0
        register = ErasureRegister(paths.data_dir / "erasures.db")
        who = requested_by or getpass.getuser()
        erasure_id = register.record(keys, who, reason, seeds=[(object_type, object_id)])
        result = apply_erasures(catalog, config.schema, register, mirror_dir)
        removed = result.removed
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
    for line in gap_notice(result.reach):
        print(f"WARNING {line}", file=sys.stderr)
    gaps = result.incomplete.get(erasure_id, [])
    if gaps:
        # NOT A SUCCESS, and not silent: the person may still be in these
        # tables. The register records the erasure as incomplete (--list),
        # and every sync says so, and works it out again, until it is not.
        print(f"NOT COMPLETE: {len(gaps)} table(s) could not be fully searched: "
              f"{', '.join(gaps)}.", file=sys.stderr)
        return 2
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
              f"  -- {erasure.reason}"
              + (f"  INCOMPLETE: {', '.join(erasure.incomplete_tables)}"
                 if erasure.incomplete_tables else ""))
    return 0


def _pairs(text: "str | None", what: str) -> "dict[str, set[str]]":
    """`column=Type[,column=Type]` as {column: {Type}}."""
    found: dict[str, set[str]] = {}
    for part in (text or "").split(","):
        if not part.strip():
            continue
        column, _, name = part.partition("=")
        if not column.strip() or not name.strip():
            raise ValueError(f"{what}: {part!r} is not column=Type")
        found.setdefault(column.strip(), set()).add(name.strip())
    return found


def adopt(identifier: str, keys: "str | None", ids: "str | None", links: "str | None",
          none: bool, paths=None) -> int:
    """The operator's statement about ONE lake table: which of its columns
    hold which types' ids (or that it holds none). Recorded on the table,
    unioned with what is known, never narrowing; the table then stops being
    partly known. Names only; an unknown table or column is refused."""
    from pyiceberg.exceptions import NoSuchNamespaceError, NoSuchTableError

    paths = paths or resolve_runtime_paths()
    config = load_deployment(paths.config_dir)
    try:
        stated = _pairs(keys, "--keys")
        stated_ids = _pairs(ids, "--ids")
        stated_links: dict[str, set[tuple[str, str]]] = {}
        for column, names in _pairs(links, "--links").items():
            for name in names:
                owner, _, target = name.partition(":")
                if not owner or not target:
                    raise ValueError(f"--links: {column}={name} is not column=Owner:Target")
                stated_links.setdefault(column, set()).add((owner, target))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    if none == bool(stated or stated_ids or stated_links):
        print("Say what the table holds (--keys column=Type) or that it holds no person's id "
              "(--adopt-none), not both and not neither.", file=sys.stderr)
        return 1
    catalog = open_mirror_catalog(paths.data_dir / "mirror", dict(config.mirror_storage))
    with single_writer(paths.data_dir / "sync.lock") as acquired:
        if not acquired:
            print("A sync is running. Try again when it has finished; nothing was recorded.")
            return 1
        try:
            record = adopt_table(catalog, config.schema, identifier,
                                 {**stated, **stated_ids}, stated_ids, stated_links)
        except (NoSuchTableError, NoSuchNamespaceError):
            print(f"No table {identifier!r} in the lake.", file=sys.stderr)
            return 1
        except KeyError as e:
            print(f"{identifier} has no column {e.args[0].partition(PART_MARK)[0]!r}.", file=sys.stderr)
            return 1
    print(f"Recorded for {identifier}: "
          + (", ".join(f"{column}={'|'.join(sorted(names))}" for column, names in sorted(record.keys.items()))
             or "no person's id")
          + ". It is no longer partly known. Erasures still marked incomplete are worked out again "
            "at the next sync.")
    return 0


def main() -> int:
    if sys.argv[1:] == ["--list"]:
        return list_erasures()
    if sys.argv[1:2] in (["--adopt"], ["--adopt-none"]):
        parser = argparse.ArgumentParser(prog=f"erase {sys.argv[1]}")
        parser.add_argument("table")
        parser.add_argument("--keys")
        parser.add_argument("--ids")
        parser.add_argument("--links")
        args = parser.parse_args(sys.argv[2:])
        return adopt(args.table, args.keys, args.ids, args.links, sys.argv[1] == "--adopt-none")
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
