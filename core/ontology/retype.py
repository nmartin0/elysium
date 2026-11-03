"""Changing an existing field's data type: what it does to stored data, what
names the field, and which tables now need their silver rebuilt (slice R1 of
the retype design; BLOCKING.md, "RETYPE, CHECKED AND SLICED").

THE ORDER OF A RETYPE, which this module's three answers serve:

  1. The line in ontology_schema.yaml changes (core/config_editing.
     apply_retype). Reads use the declared type from the moment the
     configuration reloads.
  2. The next sync REFUSES silver for each table whose declared column type
     no longer matches the table (iceberg_sync._refuse_a_changed_declared_
     type): Iceberg cannot change a column's type in place. Nothing is
     dropped by that.
  3. A person names the tables (`run_sync --rebuild silo.table`, or "Rebuild
     now" on the Schema screen) and silver is dropped and rebuilt from
     bronze, which holds every raw value as text and is never touched.
  4. Gold of the type is rebuilt from the new silver (gold._columns_changed
     sees the new column type).

NO MARKER FILE RECORDS THAT A REBUILD IS OWED. `tables_needing_rebuild`
derives it every time by comparing the declared type with the silver table's
own schema, so the answer cannot go stale: a rebuild done by hand with the
command line, a retype undone by putting the old file back, and a table that
was never built all read correctly with nothing to tidy.

WHAT THE SENTENCES BELOW SAY IS PINNED by tests/integration/
test_retype_from_the_ui.py::TestWhatHappensToStoredData, which syncs before
and after and reads each layer, so the words cannot drift from the code.

WHAT THE SYNC DOES ABOUT GOLD WHILE SILVER IS REFUSED (measured, slice R1;
pinned by TestWhileSilverIsRefused): the type's gold is SKIPPED. The refused
table is recorded as unsynced, run_sync leaves out every type that reads it,
and gold keeps serving the rows it published before the change, in the old
type, with its publication tags and changelog untouched. It is not rebuilt
from the old-typed silver and it does not fail. (The reads themselves
already use the NEW declared type from the reload, so for that window gold's
column and the declaration disagree: that is the "rebuilding" state slice R2
is to name and serve properly.)
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

import pyarrow as pa

from core.ontology.field_types import changed_column_types, is_computed, schema_for_columns
from core.ontology.used_by import Referrer, used_by_field

_UNTOUCHED = "Nothing is deleted from your source: Elysium only reads it."
_BRONZE = "Bronze is not touched: it keeps every raw value as text, which is what silver is rebuilt from."
_GOLD = ("Gold of {types}, if it was built, is rebuilt from the new silver at the sync that follows, which "
         "restarts its publication tags from the first. Its changelog and its history of publications are kept; "
         "entries already in them keep the values they had, in the old type, and the first publication afterwards "
         "records no difference, because there is nothing of the new shape to compare it with.")
_SHARED = ("{tables} {is_are} shared by {types}: the sync skips gold of every one of them while silver is "
           "refused, and rebuilds every one of them afterwards, not only {own}.")
_BEFORE_REBUILD = ("Until the rebuild, the sync refuses silver for the table: no change at the source reaches "
                   "silver or gold of {types}, which keep what they hold, in the old type.")
_REFUSE = ("If a stored value cannot be read as {new}, the sync of that table stops with an error naming it, and "
           "so does the rebuild, until the data at the source or the type is fixed.")
_QUARANTINE = ("If a stored value cannot be read as {new}, its row is set aside in the quarantine table at every "
               "sync, while silver is refused as well as after the rebuild, and the other rows are synced.")
_COUNTED = ("Counted in bronze, as of {when} (its last snapshot: a value changed at the source since is not in "
            "it, and the rebuild does not read the source again): {failing} of {checked} values of {column} in "
            "{table} will not convert to {new}.")
_NOT_COUNTED = "The values that will not convert were NOT counted for {table}: {why}."
_NO_TABLE = ("The type the sync gives this field's column does not change, so no silver or gold is rebuilt. "
             "(Two types that declare the same column of one shared table get one type between them: the later "
             "declaration is the one used.)")


def changed_tables(before: Iterable, after: Iterable) -> list[str]:
    """The "silo.table" names whose columns are declared with different types
    after the change than before: the tables a retype touches. `before` and
    `after` are the sync targets (core/mirror/sync_targets) of the two
    configurations, passed in because this package does not import the
    mirror. Asking the targets, not the field, covers a table two types
    share and a field backed by a second storage."""
    was = {f"{target.silo_name}.{target.table_name}": dict(target.column_types) for target in before}
    return sorted(name for name, types in
                  ((f"{target.silo_name}.{target.table_name}", dict(target.column_types)) for target in after)
                  if name in was and was[name] != types)


def stored_data(tables: Sequence[str], types: Sequence[str], new_type: str, *,
                owed: "Sequence[str] | None", on_type_mismatch: "str | None" = None,
                conversions: "Sequence[Any] | None" = None) -> list[str]:
    """What a retype does to the data already stored, one sentence each,
    for the confirmation dialog.

    `tables` are the tables it touches (changed_tables) and `types` every
    object type stored in them (gold of each is skipped and rebuilt, not
    only the one retyped). `owed` is which of ALL tables hold silver of a
    different type right now (tables_needing_rebuild, run on the proposed
    schema), or None when the mirror could not be read. `on_type_mismatch`
    is the deployment's setting (config.yaml), which decides what a value
    that does not convert does at every sync. `conversions` are the counts of
    values that will not convert, one per table (core/mirror/retype_count.
    ConversionCount: table, column, counted, checked, failing, as_of,
    why_not; passed in because this package does not import the mirror),
    from bronze; None says nothing about a count."""
    if not tables:
        return [_UNTOUCHED, _NO_TABLE, _BRONZE]
    listed = ", ".join(tables)
    types_named = ", ".join(types)
    said = [_UNTOUCHED]
    if owed is None:
        said.append(f"The mirror could not be read just now, so this cannot say whether silver of {listed} still "
                    f"has the old type. Where it does, the sync refuses it until it is rebuilt from bronze, and "
                    f"rebuilding discards that table's snapshot history.")
    else:
        mine = [name for name in tables if name in owed]
        rest = [name for name in tables if name not in owed]
        if mine:
            one = len(mine) == 1
            said.append(f"Silver of {', '.join(mine)} cannot take the new type in place, so the sync refuses "
                        f"{'it' if one else 'them'} until you rebuild: silver is then rebuilt from bronze, and "
                        f"its snapshot history is discarded.")
        if rest:
            said.append(f"Silver of {', '.join(rest)} is not built yet or already has the new type, so nothing "
                        f"there is rebuilt.")
    said.append(_BRONZE)
    if len(types) > 1:
        said.append(_SHARED.format(tables=listed, is_are="is" if len(tables) == 1 else "are", types=types_named,
                                   own="the type you are changing"))
    said.append(_GOLD.format(types=types_named))
    if owed is None or any(name in owed for name in tables):
        said.append(_BEFORE_REBUILD.format(types=types_named))
    for each in conversions or ():
        if each.counted:
            said.append(_COUNTED.format(
                when=f"{each.as_of:%d %b %Y %H:%M} UTC" if each.as_of else "now (bronze holds no snapshot)",
                failing=f"{each.failing:,}", checked=f"{each.checked:,}", column=each.column,
                table=each.table, new=new_type))
        else:
            said.append(_NOT_COUNTED.format(table=each.table, why=each.why_not))
    said.append((_QUARANTINE if on_type_mismatch == "quarantine" else _REFUSE).format(new=new_type))
    return said


def _storage_of(type_def: dict, field_config: dict) -> dict:
    """The storage block a field's value is read from: the type's own, or
    the `additional_storage` the field names."""
    key = field_config.get("storage")
    return (type_def.get("additional_storage") or {}).get(key) or type_def.get("storage") or {}


def _holder(type_name: str, type_def: dict, field_config: dict, name: str) -> tuple:
    """(silo, table, column) a data field's value lives in."""
    storage = _storage_of(type_def, field_config)
    return (storage.get("silo"), storage.get("table"), field_config.get("column", name))


def column_of(schema: dict, object_type: str, field: str) -> tuple:
    """(silo, table, column) the field's value is stored in, on a loaded
    schema (`{type: definition}`): where a count of values that will not
    convert looks."""
    type_def = schema.get(object_type) or {}
    return _holder(object_type, type_def, (type_def.get("fields") or {}).get(field) or {}, field)


def _key_columns(schema: dict) -> dict[tuple, str]:
    """{(silo, table, column): the link it is a key of} for the columns a
    link joins on: the foreign key a link type made (on the target's table,
    or the table a reverse link reads through) and both columns of a join
    table. A link field's own column is among them."""
    keys: dict[tuple, str] = {}
    for type_name, type_def in schema.items():
        silo = (type_def.get("storage") or {}).get("silo")
        for name, field_config in (type_def.get("fields") or {}).items():
            if field_config.get("type") != "link" and "link_type" not in field_config:
                continue
            label = field_config.get("link_type") or f"{type_name}.{name}"
            if field_config.get("via_table"):
                for column in (field_config.get("via_column"), field_config.get("via_target_column")):
                    if column:
                        keys[(silo, field_config["via_table"], column)] = label
            else:
                keys[_holder(type_name, type_def, field_config, name)] = label
    return keys


def refusal(schema: dict, targets: Iterable, object_type: str, field: str) -> "str | None":
    """Why this field's type is not changed from the screen, judged on the
    LOADED schema (`security: inherit` has become the silo's block, a
    `<<:` merge has been expanded) and on the sync targets, which are
    per COLUMN: a field is stored in a (silo, table, column), and two
    fields of two types can share one, the last declaration's type winning
    (sync_targets: column_types.update). So the question is whether the
    COLUMN is one that the identifier, the row security or a link rests
    on, not whether this field's NAME is. None when nothing stands in the
    way. `schema` is {type: definition}; `targets` the sync targets of
    that schema (passed in: this package does not import the mirror)."""
    type_def = schema.get(object_type) or {}
    field_config = (type_def.get("fields") or {}).get(field) or {}
    where = f"{object_type}.{field}"
    if is_computed(field_config):
        return (f"{where} is not stored: its type is what its rule produces. Change the rule, not the type.")
    security = type_def.get("security")
    if isinstance(security, Mapping) and security.get("field") == field:
        return (f"{where} decides who may see each row of {object_type}"
                f"{' (it follows the rule of its silo)' if type_def.get('security_inherited_from') else ''}"
                f", and its type is not changed here.")
    silo, table, column = _holder(object_type, type_def, field_config, field)
    where_stored = f"column {column} of {silo}.{table}"
    for target in targets:
        if (target.silo_name, target.table_name) != (silo, table):
            continue
        sharing = ", ".join(sorted(target.object_types)) or object_type
        if target.id_column == column:
            return (f"{where} is stored in {where_stored}, which identifies the rows of {sharing}, and "
                    f"its type is not changed here.")
        if target.security_column == column:
            return (f"{where} is stored in {where_stored}, which decides who may see the rows of "
                    f"{sharing}, and its type is not changed here. Changing how it is stored would change "
                    f"who can see a row.")
    linked = _key_columns(schema).get((silo, table, column))
    if linked:
        return (f"{where} is stored in {where_stored}, which the link {linked} joins on, and its type is "
                f"not changed here.")
    return None


def places_naming(schema, roles, action_types, triggers, object_type: str, field: str) -> list[Referrer]:
    """Every place in the configuration that names the field: constraints
    and value checks on it, fields derived from it or enriched or predicted
    with it, action parameters and submission criteria that read it, triggers
    and grants. NOTES for the person retyping, not blockers: a retype changes
    what the field holds, not whether it exists, and each owner decides
    whether their rule still means what they wrote. The Used by report's own
    rows, one source (core/ontology/used_by.py)."""
    return used_by_field(schema, roles, action_types, triggers, object_type, field)


def tables_needing_rebuild(targets: Iterable, silver_schema_of: Callable[[str], "pa.Schema | None"],
                           source_columns_of: "Callable[[str], set[str] | None] | None" = None) -> list[str]:
    """The "silo.table" names whose SILVER column types differ from what the
    ontology declares now: exactly the tables the sync refuses until they
    are rebuilt. `targets` are the sync targets of the running configuration;
    `silver_schema_of("silo.table")` is the table's Arrow schema as the lake
    holds it, or None when it was never built (nothing to rebuild).

    THE COMPARISON IS THE SYNC'S OWN (field_types.schema_for_columns for
    what is declared, changed_column_types for the spelling rules). A column
    on one side only is not a type change.

    A COLUMN THE SOURCE NO LONGER HAS IS NOT COMPARED, as in the sync, which
    drops it before it compares (iceberg_sync, "columns = [column for
    column in columns if column not in missing]") -- or refuses the table for
    the vanished column and never reaches the comparison. A rebuild listed
    for it would discard history for nothing. WHAT THIS CANNOT KNOW without
    reading the source is which columns it has now: `source_columns_of
    ("silo.table")` answers with the columns the source had at the LAST
    sync (bronze records them, iceberg_sync.SOURCE_COLUMNS_PROPERTY), or
    None when none were recorded (then every declared column is compared,
    as before). A column that vanished since the last sync is therefore still
    compared here and not by the next sync; the sync's own verdict on it
    stands, and the table is listed until a sync has recorded the loss."""
    needing = []
    for target in targets:
        identifier = f"{target.silo_name}.{target.table_name}"
        have = silver_schema_of(identifier)
        if have is None:
            continue
        present = source_columns_of(identifier) if source_columns_of else None
        columns = [column for column in target.columns if present is None or column in present]
        if changed_column_types(have, schema_for_columns(columns, target.column_types)):
            needing.append(identifier)
    return sorted(set(needing))
