"""Removing a field or a link type: what blocks it, and what it leaves behind
(29 October, owner-agreed design; BLOCKING.md, "Editing the ontology's shape").

THE SEQUENCE IS ALWAYS deprecate -> wait -> remove. Only a name that is
already deprecated can be removed, and removal is refused while anything
still names it. "Names it" is core/ontology/used_by.py's answer, the same
list Schema shows under "Used by" -- one source, so the screen that says
what names a thing and the rule that refuses to remove it cannot disagree.
This adds the one thing that report does not read, because it is not in
the configuration: PENDING WRITES. A write proposed against a field and not
yet decided can only be applied to a field that exists, so removing the
field would leave it in the queue forever (core/mirror/drift_policy.py makes
the same distinction for a column the source dropped, after the precedent: an
applied edit is history, a pending one is an obligation). When there is no
write log to ask, the answer is "cannot tell", which refuses -- the drift
policy's rule too: a check that did not happen must not look like a check
that passed.

REMOVING DELETES THE FIELD (OR LINK TYPE) FROM THE ONTOLOGY AND NOTHING
ELSE. No data is touched. What the pipeline then does with the data it
already holds was measured, not assumed, by syncing a copy of the fixture
configuration before and after removing a field (tests/integration/
test_removal_from_the_ui.py::TestWhatHappensToStoredData runs it again on
every test run, so the words below cannot drift from the code):

  SOURCE   never written to; Elysium only reads it.
  BRONZE   still holds the raw column. With `ingest_undeclared_columns:
           false` the next sync empties it in bronze's current copy; any
           other setting keeps the values as an undeclared column.
  SILVER   keeps the column in its table, every value empty from the next
           sync (Iceberg widens a schema, never narrows it). Earlier
           snapshots still hold the old values until they expire. A
           silver rebuild (`--rebuild silo.table`) drops the column.
  GOLD     rebuilt without the column at the next sync, which restarts the
           type's publication tags (gold.py, _columns_changed).
  READS    use the declared fields only, so nothing serves the column from
           the moment the configuration reloads, before any sync.

A FOREIGN-KEY LINK's stored column (on the type that holds the key) goes
the same way as a field; a MANY-TO-MANY LINK's join table stops being
synced and its bronze, silver and gold tables stay where they were,
no longer refreshed.

Nothing here refuses because of the pipeline: removing a declared field
does not break a sync or a rebuild (both measured). What would break one is
a name something still depends on, and that is what the blockers are.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace

from core.ontology.used_by import Referrer, used_by_field, used_by_link, used_by_type

PENDING_WRITE = "pending write"


def link_ends(schema: Mapping, link_type: str) -> list[tuple[str, str]]:
    """[(type, field)] for the one or two fields a link type made."""
    return [(owner, name)
            for owner, type_def in schema.items()
            for name, field in (type_def.get("fields") or {}).items()
            if field.get("type") == "link" and field.get("link_type") == link_type]


def field_blockers(schema: Mapping, roles: Mapping, action_types: Mapping, triggers, write_log,
                   object_type: str, field: str) -> list[Referrer]:
    """Everything that stops one stored field being removed."""
    found = used_by_field(schema, roles, action_types, triggers, object_type, field)
    return [*found, *_pending_writes(write_log, [(object_type, field)])]


def link_blockers(schema: Mapping, roles: Mapping, action_types: Mapping, triggers, write_log,
                  link_type: str) -> list[Referrer]:
    """Everything that stops one link type being removed."""
    found = used_by_link(schema, roles, action_types, triggers, link_type)
    return [*found, *_pending_writes(write_log, link_ends(schema, link_type))]


def type_blockers(schema: Mapping, roles: Mapping, action_types: Mapping, triggers, write_log,
                  object_type: str, functions=(), incremental: "Sequence[tuple[str, str]]" = ()) -> list[Referrer]:
    """Everything that stops a whole object type being removed: the Used by
    report for the type, then what that report does not read -- functions
    that declare they read it, a silo's `incremental:` declaration for the
    only table it was read from (`incremental`: those tables, asked of the
    mirror; the loader refuses a declaration for a table the sync no longer
    reads), and PENDING WRITES against any of its fields.

    THE TYPE'S OWN FIELDS ARE NOT SECRETS FROM THE PERSON ASKING: they go
    with the type, and a manager of the deployment reads every name in the
    declaration. So a row naming only them is not hidden from a person who
    may not discover those fields one by one (they would otherwise be unable
    to remove anything, as for a field). Other types' names stay gated."""
    own = {f"{object_type}.{name}" for name in (schema.get(object_type) or {}).get("fields") or {}}
    found = [replace(row, subjects=tuple(name for name in row.subjects if name not in own))
             for row in used_by_type(schema, roles, action_types, triggers, object_type)]
    found += [Referrer("function", f"function {function.name}", f"declares that it reads {object_type}")
              for function in functions if object_type in getattr(function, "reads_object_types", ())]
    found += _incremental_tables(incremental, object_type)
    own_fields = [(object_type, name) for name in (schema.get(object_type) or {}).get("fields") or {}]
    return [*found, *_pending_writes(write_log, own_fields)]


def _incremental_tables(only_read_by_it: "Sequence[tuple[str, str]]", object_type: str) -> list[Referrer]:
    """A silo's `incremental:` entry for each table only this type reads
    (core/mirror/incremental.incremental_tables_only_read_by, which the
    caller asks: this package does not import the mirror)."""
    return [Referrer("silo", f"data silo {silo}, incremental",
                     f"reads table {table} by changed rows, and only {object_type} reads that table")
            for silo, table in only_read_by_it]


def _pending_writes(write_log, fields: "list[tuple[str, str]]") -> list[Referrer]:
    if write_log is None:
        return [Referrer(PENDING_WRITE, "write log",
                         "cannot be asked, so whether a write is waiting on it cannot be told")]
    found = []
    for object_type, field in fields:
        waiting = write_log.edits_touching_field(object_type, field).get("pending", 0)
        if waiting:
            found.append(Referrer(
                PENDING_WRITE, f"{object_type}.{field}",
                f"{waiting} proposed write(s) are waiting to set it, and could never be applied once it "
                f"is gone: decide them first"))
    return found


def applied_writes(write_log, fields: "list[tuple[str, str]]") -> int:
    """How many applied edits set these fields: history that stays in the
    write log when they go. 0 when there is no log to ask."""
    if write_log is None:
        return 0
    return sum(write_log.edits_touching_field(object_type, field).get("applied", 0)
               for object_type, field in fields)


def visible_to(blockers: list[Referrer], knows: Callable[[str], bool]) -> "tuple[list[Referrer], int]":
    """(the blockers this person may be shown, how many they may not).

    A row is shown only when every name it carries (Referrer.subjects) is
    one the person could find in Schema. The rest are counted, never
    described: that something they cannot discover names this is a fact
    about the thing they asked about, which they may know, and the count
    stops the list reading as shorter than it is."""
    shown = [item for item in blockers if all(knows(subject) for subject in item.subjects)]
    return shown, len(blockers) - len(shown)


_UNTOUCHED = "Nothing is deleted from your source: Elysium only reads it."
_SILVER = ("Silver keeps the column in its table but empties it at the next sync; its earlier snapshots "
           "still hold the old values until they expire. Rebuilding that table (run_sync --rebuild) drops "
           "the column for good.")
_BRONZE = ("Bronze still holds the raw column: with ingest_undeclared_columns set to false it is emptied at "
           "the next sync, otherwise its values stay.")
_GOLD = "Gold is rebuilt without the column at the next sync, which restarts that type's publication tags."


#: Measured (TestWhatHappensToStoredDataWhenATypeGoes): after the type is
#: removed and a sync runs, every one of its tables -- bronze, silver, gold,
#: gold's history -- has the same snapshots and the same tags as before, and
#: a --rebuild naming its silver table exits 0 and writes nothing.
_TYPE_TABLES = [
    "Bronze, silver and gold keep the type's tables exactly as they were at the last sync, and so does the "
    "history of its changes: nothing is dropped, and no sync reads or refreshes them again. (If another type "
    "reads the same source table, that table keeps syncing for the other type only, and the columns only this "
    "type mapped are emptied the way a removed field's column is.)",
    "A later erasure request still reaches these tables, and follows the type's links from an erased "
    "person to its own rows: each table records which of its columns hold ids, and erasure reads that "
    "record once the type is gone. Removing the type here records its tables first (if the lake cannot "
    "be read at that moment, or a sync is running, the reply says so). That holds in full for a table whose "
    "every column the ontology maps, and for tables an operator has adopted (python -m scripts.erase "
    "--adopt). A table with a column the ontology does not map is different, and no sync can change that: "
    "what a type, link or field removed earlier kept in that column is unknown. Erasure searches it by the "
    "columns still known, says it is partly known, names the unmapped columns, and marks every erasure "
    "incomplete, so the person may remain in those columns until the table is adopted or dropped in the "
    "lake. If no type was ever removed from your deployment, the normal remedy after an upgrade is one "
    "command: python -m scripts.erase --adopt-all-current --confirm-no-type-was-ever-removed (tables "
    "with unmapped columns need --including-unmapped-columns as well, which states those columns hold "
    "no person ids and asks for a typed phrase). Adopt such tables before erasing: an erasure refuses to run "
    "while they could affect it, unless told to erase what it can reach now.",
    "Asking for a rebuild of its silver table does nothing, because the sync no longer knows the table. Dropping "
    "the tables is done in the lake itself, by a person.",
]


def stored_data(kind: str, cardinality: "str | None", applied: int) -> list[str]:
    """What removal leaves behind, one sentence each, for the confirmation
    dialog. `kind` is "field", "link" or "type"; `cardinality` the link's, so a
    join table is described as one. Each sentence is pinned by a test that
    syncs before and after (see the module docstring)."""
    if kind == "type":
        notes = [_UNTOUCHED, *_TYPE_TABLES,
                 "Nothing serves the type from the moment this applies, before any sync runs."]
    elif kind == "link" and cardinality == "many_to_many":
        notes = [_UNTOUCHED,
                 "The join table stops being synced. Its bronze, silver and gold tables stay as they were "
                 "and are no longer refreshed.",
                 "Nothing serves the link from the moment this applies."]
    elif kind == "link":
        notes = [_UNTOUCHED,
                 "The foreign key column is no longer a field of the type that holds it, so it goes the way "
                 "a removed field's column does.",
                 _SILVER, _BRONZE, _GOLD,
                 "Nothing serves the link from the moment this applies."]
    else:
        notes = [_UNTOUCHED, _SILVER, _BRONZE, _GOLD,
                 "Nothing serves the column from the moment this applies, before any sync runs."]
    if applied:
        notes.append(f"{applied} edit(s) already applied to it stay in the write log as history.")
    return notes
