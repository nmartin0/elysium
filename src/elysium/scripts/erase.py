"""Erase a person from everything the mirror holds (R13).

    python -m elysium.scripts.erase Customer cust_001 --reason "GDPR request 2026-114"
    python -m elysium.scripts.erase Customer cust_001 --reason "..." --write
    python -m elysium.scripts.erase --list
    python -m elysium.scripts.erase --adopt-all-current --confirm-no-type-was-ever-removed
    python -m elysium.scripts.erase --adopt-all-current --confirm-no-type-was-ever-removed \\
        --including-unmapped-columns [--typed-confirmation "I VOUCH FOR THESE COLUMNS"]
    python -m elysium.scripts.erase --adopt bronze_primary_sql.tags --keys tag_id=Tag [--ids tag_id=Tag]
    python -m elysium.scripts.erase --adopt-none primary_sql.audit_notes

--adopt-all-current is the normal remedy after an upgrade, for a deployment that
never removed an object type: it marks every table whose every column the
ontology maps complete, on your statement, and lists (never touches) the rest
with the columns the ontology does not map. Adding --including-unmapped-columns
also adopts those, on the stronger statement that no type, link or field was
ever removed or re-pointed and the unmapped columns hold no person ids. That
statement is the one nobody can check, so it also needs a typed confirmation:
every table and unmapped column about to be vouched for is printed, then you
type the phrase I VOUCH FOR THESE COLUMNS exactly. With no terminal it is
refused unless the phrase is given with --typed-confirmation "<phrase>", so a
script is possible but deliberate. A wrong or empty phrase adopts nothing
(exit 1). --write REFUSES, and
erases nothing, while a table that could affect the erasure cannot be fully
searched; --erase-reachable-now erases what can be reached and records the
erasure incomplete.

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

EXIT CODES: 0 erased (or a dry run) with nothing left to search; 1 bad
arguments or a sync was running (nothing was done); 2 ERASED BUT INCOMPLETE
(some table could not be fully searched: see --list); 3 REFUSED, NOTHING
ERASED (a table that could affect the erasure cannot be fully searched).

HOLDS THE SYNC LOCK, so no sync is half-way through a table it rewrites.
The server pins the publication it loaded: restart it, or reload
(POST /api/admin/reload), after an erasure.
"""

import argparse
import getpass
import sys
from collections import Counter

from elysium.core.access.audit import AuditLog
from elysium.core.deployment_loader import load_deployment, resolve_runtime_paths
from elysium.core.mirror.catalog import open_mirror_catalog
from elysium.core.mirror.erasure import (
    ADOPT_HINT,
    PART_MARK,
    ErasureRegister,
    adopt_all_current,
    adopt_table,
    apply_erasures,
    cascade,
    forget_beyond_the_mirror,
    gap_notice,
    preview_adopt_all_current,
    recorded_object_types,
    relevant_tables,
    survey,
)
from elysium.core.mirror.sync_lock import single_writer


def run(object_type: str, object_id: str, reason: str, write: bool = False,
        paths=None, requested_by: "str | None" = None, erase_reachable_now: bool = False) -> int:
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
        reach_now = survey(catalog, config.schema, set(counts))
        blocking = relevant_tables(reach_now, config.schema, set(counts))
        if write and blocking and not erase_reachable_now:
            # NOTHING IS ERASED: an erasure run first removes the rows that link a person to
            # what depended on them, which adopting the tables afterwards could not follow.
            print(f"NOT ERASED: {len(blocking)} table(s) could affect this erasure and cannot be fully "
                  f"searched: {', '.join(blocking)}. Resolve them first -- " + ADOPT_HINT
                  + ". Or pass --erase-reachable-now to erase what can be reached now and record the "
                    "erasure as incomplete. (Exit code 3: refused, nothing erased.)", file=sys.stderr)
            return 3
        if not write:
            # SO --write IS NOT A SURPRISE: what it would not be able to search.
            reach = survey(catalog, config.schema, set(counts))
            for line in gap_notice(reach):
                print(f"  WARNING {line}")
            if blocking and not erase_reachable_now:
                print(f"--write would REFUSE and erase nothing: {len(blocking)} table(s) could not be "
                      f"fully searched ({', '.join(blocking)}). Resolve them first, or pass "
                      f"--erase-reachable-now to erase what can be reached and record the erasure "
                      f"incomplete.")
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
            merged = {column: stated.get(column, set()) | stated_ids.get(column, set())
                      for column in {*stated, *stated_ids}}
            record = adopt_table(catalog, config.schema, identifier, merged, stated_ids, stated_links)
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


VOUCH_PHRASE = "I VOUCH FOR THESE COLUMNS"


def _typed_phrase(supplied: "str | None") -> "str | None":
    """The phrase the operator gave: the flag if there is one, else a line
    typed on stdin. None when there is no terminal and no flag."""
    if supplied is not None:
        return supplied
    if not sys.stdin.isatty():
        return None
    try:
        return input(f"To vouch for these columns, type exactly: {VOUCH_PHRASE}\n> ")
    except EOFError:
        return ""


def adopt_everything_current(confirmed: bool, paths=None, including_unmapped: bool = False,
                             typed_confirmation: "str | None" = None) -> int:
    """--adopt-all-current: the one-step remedy for a deployment that never
    removed an object type. Refused without --confirm-no-type-was-ever-removed.
    Touches only tables whose every column the current ontology maps -- or,
    with --including-unmapped-columns, also tables with columns it does not
    map; lists the rest with those columns' names. That second form first
    prints every table and unmapped column it will vouch for and needs
    VOUCH_PHRASE, typed or given as typed_confirmation; without either (no
    terminal) or with a different phrase it adopts nothing and returns 1."""
    if not confirmed:
        print("This states that no object type was EVER removed from this deployment, which only you "
              "can know. Say so with --confirm-no-type-was-ever-removed. Nothing was recorded.",
              file=sys.stderr)
        return 1
    paths = paths or resolve_runtime_paths()
    config = load_deployment(paths.config_dir)
    catalog = open_mirror_catalog(paths.data_dir / "mirror", dict(config.mirror_storage))
    if including_unmapped:
        shown, _ = preview_adopt_all_current(catalog, config.schema, True)
        print("You are about to vouch that no type, link or field was ever removed or re-pointed, and that "
              "these columns hold NO PERSON'S ID, for:")
        for table, columns in sorted(shown.items()):
            print(f"  {table}: " + (", ".join(columns) if columns else "(every column is mapped)"))
        if not shown:
            print("  (no table)")
        phrase = _typed_phrase(typed_confirmation)
        if phrase is None:
            print(f"No terminal to type on. Give the phrase with --typed-confirmation \"{VOUCH_PHRASE}\" "
                  "if you mean it. Nothing was recorded.", file=sys.stderr)
            return 1
        if phrase != VOUCH_PHRASE:
            print(f"That was not the phrase {VOUCH_PHRASE}. Nothing was recorded.", file=sys.stderr)
            return 1
    with single_writer(paths.data_dir / "sync.lock") as acquired:
        if not acquired:
            print("A sync is running. Try again when it has finished; nothing was recorded.")
            return 1
        if including_unmapped and preview_adopt_all_current(catalog, config.schema, True)[0] != shown:
            print("The tables or columns changed while you were confirming. Nothing was recorded; "
                  "run it again.", file=sys.stderr)
            return 1
        adopted, unresolved = adopt_all_current(catalog, config.schema, confirmed, including_unmapped)
    print(f"Adopted {len(adopted)} table(s) the ontology maps, on your statement that no type was ever "
          f"removed.")
    if unresolved:
        print(f"STILL UNRESOLVED ({len(unresolved)}):")
        for table, why in sorted(unresolved.items()):
            print(f"  {table}: {why}")
        print("Adopt each with --adopt, or drop it in the lake"
              + ("" if including_unmapped else "; for tables whose only gap is columns the ontology does "
                 "not map, --adopt-all-current --including-unmapped-columns "
                 "--confirm-no-type-was-ever-removed states that no type, link or field was ever removed "
                 "or re-pointed and those columns hold no person ids, and asks you to type "
                 f"{VOUCH_PHRASE} to say so")
              + ".")
    return 0


def main() -> int:
    if sys.argv[1:] == ["--list"]:
        return list_erasures()
    if sys.argv[1:2] == ["--adopt-all-current"]:
        parser = argparse.ArgumentParser(prog="erase --adopt-all-current", description=__doc__,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("--confirm-no-type-was-ever-removed", action="store_true")
        parser.add_argument("--including-unmapped-columns", action="store_true")
        parser.add_argument("--typed-confirmation", metavar="PHRASE",
                            help=f"the phrase {VOUCH_PHRASE!r}, for runs with no terminal; only with "
                                 "--including-unmapped-columns")
        try:
            args = parser.parse_args(sys.argv[2:])
        except SystemExit as stop:
            return int(stop.code or 0)
        if args.typed_confirmation is not None and not args.including_unmapped_columns:
            print("--typed-confirmation belongs with --including-unmapped-columns, the only form that "
                  "asks for it.", file=sys.stderr)
            return 1
        return adopt_everything_current(args.confirm_no_type_was_ever_removed,
                                        including_unmapped=args.including_unmapped_columns,
                                        typed_confirmation=args.typed_confirmation)
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
    parser.add_argument("--erase-reachable-now", action="store_true",
                        help="erase what can be searched even though some tables cannot be fully "
                             "searched; the erasure is recorded incomplete")
    args = parser.parse_args()
    return run(args.object_type, args.object_id, args.reason, write=args.write,
               erase_reachable_now=args.erase_reachable_now)


if __name__ == "__main__":
    sys.exit(main())
