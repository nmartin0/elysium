"""The ontology's schema, rebound to GOLD (GOLD-3).

WHAT THIS IS FOR. Elysium's read path is already ontology-shaped at
its surface -- every mediator method takes an object type, a field and
an id -- and storage-shaped INSIDE, where a field becomes a column and
a type becomes a silo and a table. Gold does not change the surface.
It changes what those inside facts are:

    storage      gold.<ObjectType>, id_column = the type's id_field
    a field      its own PROPERTY NAME, since conform() wrote it that
                 way (core/mirror/gold.py)
    a reverse    the TARGET's gold table, keyed by the target's
    link         property that holds the foreign key

SO THE VIEW IS A TRANSLATION, not a second schema. It is derived from
the declared one every time, never stored, never edited: the
declaration remains the only place an object type is defined
(GOLD-3c), and this is what the reader is handed instead.

WHY A SEPARATE VIEW RATHER THAN EDITING THE SCHEMA IN PLACE. The
SOURCE-shaped schema is still needed, by the sync that fills gold and
by the write path that goes to the customer's database (decision D3).
Both views describe the same ontology; only the bindings differ.

WHAT IT REFUSES. A type gold does not build -- one with more than one
source, which GOLD-5 covers -- has no gold table to point at, and a
view that quietly pointed at a missing table would fail at read time
with a catalog error. Those types are LEFT OUT, and the caller is told
which, so it can keep serving them the old way rather than discover
the gap one request at a time.
"""

from core.ontology.link_types import is_reverse_link

# The catalog namespace gold tables live in. DECLARED HERE, in the
# ontology layer, because core.mirror may import core.ontology and not
# the other way round -- and both need the same word.
GOLD_NAMESPACE = "gold"

# Set on a gold-shaped storage block so anything downstream can tell
# the two views apart without string-matching a namespace.
GOLD_VIEW_MARKER = "elysium_gold_view"


def _gold_fields(type_def: dict, schema: dict) -> dict:
    """Every field, rebound to the column gold actually wrote."""
    fields = {}
    for field_name, field_config in (type_def.get("fields") or {}).items():
        rebound = dict(field_config)
        # conform() writes each property under its OWN name, so any
        # `column` override the source needed is gone -- and a stale
        # one would read a column gold never created.
        rebound.pop("column", None)
        # A type spanning several storages is not in the view at all
        # (see build_gold_view), so a per-field storage pointer has
        # nothing left to mean.
        rebound.pop("storage", None)
        if field_config.get("type") == "link" and is_reverse_link(field_config):
            target = field_config.get("target")
            target_def = schema.get(target) or {}
            # THE RE-KEYING. A reverse link is resolved by querying the
            # TARGET's table for rows pointing back here; in gold that
            # table is gold.<Target>, and the column holding the
            # foreign key is the target's own PROPERTY name, not the
            # source column the via_column named.
            rebound["via_table"] = target
            rebound["via_column"] = _property_for_column(
                target_def, field_config.get("via_column"),
            )
        fields[field_name] = rebound
    return fields


def _property_for_column(target_def: dict, via_column: str | None) -> str | None:
    """The target's property whose value gold stores in that column.

    The source named a COLUMN; gold stores properties. Where the target
    declares a field backed by that column, its name is what the gold
    table holds. Where nothing matches, the column name is kept --
    conform() writes a property of the same name when no override was
    declared, so an unmapped column is usually already correct, and a
    wrong guess here would be worse than an honest passthrough.
    """
    if via_column is None:
        return None
    for field_name, field_config in (target_def.get("fields") or {}).items():
        if field_config.get("column", field_name) == via_column:
            return field_name
    return via_column


def build_gold_view(schema: dict) -> tuple[dict, dict[str, str]]:
    """(the gold-shaped schema, {object_type: why it was left out}).

    Deriving this is cheap and it is derived per generation, not
    cached: a schema that disagrees with the declaration is a bug
    waiting for somebody to edit one and not the other.
    """
    view: dict = {}
    excluded: dict[str, str] = {}
    for object_type, type_def in schema.items():
        if type_def.get("additional_storage"):
            excluded[object_type] = "more than one source: gold does not build it yet (GOLD-5)"
            continue
        id_field = type_def.get("id_field")
        if not id_field:
            excluded[object_type] = "no id_field: gold is keyed by the object's id"
            continue
        rebound = dict(type_def)
        rebound["storage"] = {
            "silo": GOLD_NAMESPACE,
            "table": object_type,
            "id_column": id_field,
            GOLD_VIEW_MARKER: True,
        }
        rebound["fields"] = _gold_fields(type_def, schema)
        view[object_type] = rebound

    # A LINK INTO A TYPE THAT IS NOT IN THE VIEW cannot be followed
    # here: its target has no gold table. Excluding the target alone
    # would leave a field pointing at nothing, which is the shape of
    # bug this module exists to avoid, so the SOURCE type goes too.
    changed = True
    while changed:
        changed = False
        for object_type in list(view):
            for field_name, field_config in (view[object_type].get("fields") or {}).items():
                target = field_config.get("target")
                if field_config.get("type") == "link" and target not in view:
                    excluded[object_type] = (
                        f"links to {target!r} through {field_name!r}, which gold does not build"
                    )
                    del view[object_type]
                    changed = True
                    break
    return view, excluded
