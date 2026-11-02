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

import pyarrow as pa

from core.ontology.field_types import changed_column_types, is_computed, schema_for_columns
from core.ontology.used_by import Referrer, used_by_field

_UNTOUCHED = "Nothing is deleted from your source: Elysium only reads it."
_BRONZE = "Bronze is not touched: it keeps every raw value as text, which is what silver is rebuilt from."
_GOLD = ("Gold of {type} is rebuilt from the new silver at the sync that follows, which restarts its "
         "publication tags from the first. Its changelog and its history of publications are kept; entries "
         "already in them keep the values they had, in the old type, and the first publication afterwards "
         "records no difference, because there is nothing of the new shape to compare it with.")
_NOT_COUNTED = ("How many stored values will not convert to the new type is not counted yet, so it is not "
                "shown here.")
_BEFORE_REBUILD = ("Until the rebuild, the sync refuses silver for the table and gold of this type is left "
                   "as it was; nothing is lost by waiting.")


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


def stored_data(tables: Sequence[str], gold_type: str) -> list[str]:
    """What a retype does to the data already stored, one sentence each,
    for the confirmation dialog. `tables` are the tables it touches
    (changed_tables), `gold_type` the object type whose gold is rebuilt."""
    if not tables:
        return [_UNTOUCHED,
                "No table is read for this field yet, so there is no silver or gold to rebuild.",
                _BRONZE]
    one = len(tables) == 1
    silver = (f"Silver of {', '.join(tables)} cannot take the new type in place, so the sync refuses "
              f"{'it' if one else 'them'} until you rebuild: silver is then rebuilt from bronze, and its "
              f"snapshot history is discarded.")
    return [_UNTOUCHED, silver, _BRONZE, _GOLD.format(type=gold_type), _BEFORE_REBUILD, _NOT_COUNTED]


def _storage_of(type_def: dict, field_config: dict) -> dict:
    """The storage block a field's value is read from: the type's own, or
    the `additional_storage` the field names."""
    key = field_config.get("storage")
    return (type_def.get("additional_storage") or {}).get(key) or type_def.get("storage") or {}


def _holder(type_name: str, type_def: dict, field_config: dict, name: str) -> tuple:
    """(silo, table, column) a data field's value lives in."""
    storage = _storage_of(type_def, field_config)
    return (storage.get("silo"), storage.get("table"), field_config.get("column", name))


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


def tables_needing_rebuild(targets: Iterable, silver_schema_of: Callable[[str], "pa.Schema | None"]) -> list[str]:
    """The "silo.table" names whose SILVER column types differ from what the
    ontology declares now: exactly the tables the sync refuses until they are
    rebuilt. `targets` are the sync targets of the running configuration;
    `silver_schema_of("silo.table")` is the table's Arrow schema as the lake
    holds it, or None when it was never built (nothing to rebuild).

    THE COMPARISON IS THE SYNC'S OWN (field_types.schema_for_columns for
    what is declared, changed_column_types for the spelling rules), so a
    table listed here is one the sync would refuse and one not listed is
    one it would not -- a rebuild of anything else discards snapshot
    history for nothing. A column on one side only is not a type change.
    One difference, on purpose: a column the SOURCE no longer has is left
    out of the sync's comparison and is in this one."""
    needing = []
    for target in targets:
        identifier = f"{target.silo_name}.{target.table_name}"
        have = silver_schema_of(identifier)
        if have is None:
            continue
        if changed_column_types(have, schema_for_columns(list(target.columns), target.column_types)):
            needing.append(identifier)
    return sorted(set(needing))
