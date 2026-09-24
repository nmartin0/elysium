"""The ontology, and separately where its data comes from (GOLD-3c).

WHY SPLIT THEM. Two different things had been living in one file:

    WHAT AN OBJECT IS -- its identity field, its properties and their
    types, its links, what carries its classification, its constraints
    and its actions. This is the ontology. It is what a person reads to
    understand the system, what an analyst argues about, and what the
    agent is told.

    WHERE THE DATA COMES FROM -- which silo, which table, which
    column, and which table a link is resolved through. This is an
    INGESTION detail. Since GOLD-8 it is not even how reads work: a
    read goes to gold, whose table is the object type and whose
    columns are the property names.

Keeping them together meant every reader of the ontology waded through
column names, and every change of source system edited the file that
defines what a Customer IS -- so a diff that should have read "we now
track a second address" read the same as "the CRM renamed a column".

NOT A RENAME OF THE OLD FILE. ontology_schema.yaml keeps its name and
loses its bindings; source_bindings.yaml gains them. The merged result
is exactly what the loader produced before, so nothing downstream
changes -- the sync still reads a type's storage block, the write path
still finds its silo. Only the files a person edits are different.

AND NOT "GENERATE THE ONTOLOGY FROM THE SOURCES", which the roadmap
rules out for a reason: the pipeline is driven BY the declaration. It
standardises, quarantines and conforms because the ontology says so.
A declaration derived from what the data happens to hold could not
refuse anything.

WHAT IS A BINDING, EXACTLY. On a type: `storage` and
`additional_storage`. On a field: `column`, `storage`, `via_table`,
`via_column` and `via_target_column`. Everything else is declaration,
including `security` -- WHICH field carries a classification is a fact
about the ontology, even though the column that field reads is not.
"""

TYPE_BINDING_KEYS = ("storage", "additional_storage")
FIELD_BINDING_KEYS = ("column", "storage", "via_table", "via_column", "via_target_column")


def split_bindings(schema: dict) -> tuple[dict, dict]:
    """(the declaration, the bindings) from a merged schema.

    Used to produce the second file from a deployment that still has
    one, and by the tests that prove a round trip.
    """
    declaration: dict = {}
    bindings: dict = {}
    for object_type, type_def in schema.items():
        declared = {key: value for key, value in type_def.items()
                    if key not in TYPE_BINDING_KEYS and key != "fields"}
        bound = {key: value for key, value in type_def.items() if key in TYPE_BINDING_KEYS}

        declared_fields, bound_fields = {}, {}
        for field_name, field_config in (type_def.get("fields") or {}).items():
            declared_field = {key: value for key, value in field_config.items()
                              if key not in FIELD_BINDING_KEYS}
            bound_field = {key: value for key, value in field_config.items()
                           if key in FIELD_BINDING_KEYS}
            declared_fields[field_name] = declared_field
            if bound_field:
                bound_fields[field_name] = bound_field
        declaration[object_type] = {**declared, "fields": declared_fields}
        if bound_fields:
            bound["fields"] = bound_fields
        if bound:
            bindings[object_type] = bound
    return declaration, bindings


def merge_bindings(declaration: dict, bindings: dict) -> dict:
    """The schema the rest of the system already understands.

    REFUSES RATHER THAN GUESSES, in both directions:

      A BINDING FOR A TYPE OR FIELD THAT IS NOT DECLARED is almost
      always a rename that happened on one side only -- the sort of
      thing that otherwise shows up months later as a column nobody
      reads.

      A TYPE WITH NO BINDING cannot be ingested at all, so the sync
      would skip it silently and gold would never publish it; since
      GOLD-8 that means it cannot be served either. Better to say so
      at load.
    """
    unknown_types = sorted(set(bindings) - set(declaration))
    if unknown_types:
        raise ValueError(
            f"source_bindings.yaml binds object type(s) the ontology does not "
            f"declare: {', '.join(unknown_types)}."
        )
    unbound = sorted(
        object_type for object_type in declaration
        if not (bindings.get(object_type) or {}).get("storage")
    )
    if unbound:
        raise ValueError(
            f"no source binding for object type(s): {', '.join(unbound)}. "
            f"Every declared type needs a storage block in "
            f"source_bindings.yaml, or nothing can fill its gold table."
        )

    merged: dict = {}
    for object_type, type_def in declaration.items():
        bound = bindings.get(object_type) or {}
        fields: dict = {}
        bound_fields = bound.get("fields") or {}
        unknown_fields = sorted(set(bound_fields) - set(type_def.get("fields") or {}))
        if unknown_fields:
            raise ValueError(
                f"source_bindings.yaml binds field(s) {object_type} does not "
                f"declare: {', '.join(unknown_fields)}."
            )
        for field_name, field_config in (type_def.get("fields") or {}).items():
            fields[field_name] = {**field_config, **(bound_fields.get(field_name) or {})}
        merged[object_type] = {
            **type_def,
            **{key: value for key, value in bound.items() if key != "fields"},
            "fields": fields,
        }
    return merged
