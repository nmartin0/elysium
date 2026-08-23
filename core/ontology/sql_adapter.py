"""
sql_adapter.py  (generic SQL-backed ontology adapter -- org-agnostic)

Implements search_object() and get_field() for ANY SQLite-backed
deployment, driven entirely by a schema dict declaring: table/id_column
per object type, which fields are data vs. link (and link
cardinality/target), via_table/via_column for reverse ("many") links,
and a "security" block per object type describing how to find that
object's row-level access-control value -- either a field on the object
itself, or by following a forward link to another object that holds it.

No table names, column names, or org-specific concepts are hardcoded
anywhere in this file -- everything comes from the schema dict.

Used by: deployments/<org>/ontology_adapter.py (a thin wrapper binding
         this org's own db_path and schema via functools.partial)
"""

from connectors.sqlite_connector import connect, run_query, run_query_one
from core.ontology.schema import get_field_info, is_link_field, get_link_target


def _get_security_value(conn, schema: dict, object_type: str, object_id):
    """Resolves the row-level security value for one object, following a
    via_field link if this object type doesn't hold it directly. Assumes
    security chains terminate (no circular via_field references)."""
    obj_schema = schema[object_type]
    security = obj_schema["security"]
    table = obj_schema["table"]
    id_column = obj_schema["id_column"]

    if "field" in security:
        row = run_query_one(
            conn, f"SELECT {security['field']} FROM {table} WHERE {id_column} = ?",
            (object_id,),
        )
        return row[security["field"]] if row else None

    if "via_field" in security:
        via_field = security["via_field"]
        target_type = obj_schema["fields"][via_field]["target"]

        row = run_query_one(
            conn, f"SELECT {via_field} FROM {table} WHERE {id_column} = ?", (object_id,)
        )
        if row is None:
            return None
        return _get_security_value(conn, schema, target_type, row[via_field])

    raise ValueError(f"No security resolution declared for object_type {object_type!r}")


def _security_allowed(conn, schema: dict, object_type: str, object_id,
                       requesting_user_security_value: str) -> bool:
    value = _get_security_value(conn, schema, object_type, object_id)
    return value is not None and value == requesting_user_security_value


def _filterable_columns(schema: dict, object_type: str) -> set:
    obj = schema[object_type]
    columns = {obj["id_field"]}
    for field_name, info in obj["fields"].items():
        if info["type"] == "data":
            columns.add(field_name)
        elif info["type"] == "link" and info.get("cardinality") == "one":
            columns.add(field_name)
    return columns


def search_object(db_path, schema: dict, requesting_user_security_value: str,
                   object_type: str, filter: dict) -> list:
    if object_type not in schema:
        raise ValueError(f"Unknown object_type: {object_type}")

    valid_columns = _filterable_columns(schema, object_type)
    for key in filter:
        if key not in valid_columns:
            raise ValueError(
                f"Cannot filter {object_type} by {key!r} (valid: {sorted(valid_columns)})"
            )

    obj = schema[object_type]
    table = obj["table"]
    id_column = obj["id_column"]

    # Column NAMES are whitelisted above; VALUES are always bound params.
    where_clause = " AND ".join(f"{key} = ?" for key in filter.keys())
    values = tuple(filter.values())

    conn = connect(db_path)
    try:
        if where_clause:
            rows = run_query(
                conn, f"SELECT {id_column} FROM {table} WHERE {where_clause}", values
            )
        else:
            rows = run_query(conn, f"SELECT {id_column} FROM {table}")

        candidate_ids = [row[id_column] for row in rows]
        return [
            cid for cid in candidate_ids
            if _security_allowed(conn, schema, object_type, cid, requesting_user_security_value)
        ]
    finally:
        conn.close()


def get_field(db_path, schema: dict, requesting_user_security_value: str,
              object_type: str, object_id, field_name: str):
    field_info = get_field_info(schema, object_type, field_name)

    conn = connect(db_path)
    try:
        if not _security_allowed(conn, schema, object_type, object_id, requesting_user_security_value):
            return None

        obj = schema[object_type]

        if is_link_field(field_info) and field_info.get("cardinality") == "many":
            via_table = field_info["via_table"]
            via_column = field_info["via_column"]
            target_type = get_link_target(field_info)
            target_id_column = schema[target_type]["id_column"]

            rows = run_query(
                conn, f"SELECT {target_id_column} FROM {via_table} WHERE {via_column} = ?",
                (object_id,),
            )
            return [r[target_id_column] for r in rows]

        # Plain data field OR forward link (cardinality "one") -- both are
        # just a literal column on this object's own row, read identically.
        table = obj["table"]
        id_column = obj["id_column"]
        row = run_query_one(
            conn, f"SELECT {field_name} FROM {table} WHERE {id_column} = ?", (object_id,)
        )
        return row[field_name] if row else None
    finally:
        conn.close()
