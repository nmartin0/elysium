"""
ontology_adapter.py  (acme_corp-specific -- NOT portable to other orgs)

Implements the two generic ontology primitives for this deployment's
actual database:

  search_object(user_region, object_type, filter) -> list of object IDs
  get_field(user_region, object_type, object_id, field_name) -> value

search_object() accepts a filter on the object's id_field OR any "data"
field OR any "link" field with cardinality "one" (a real foreign-key
column on this table). Fields with cardinality "many" (e.g.
Customer.transactions) are NOT filterable here -- they're computed
relationships, not real columns, and can only be reached via get_field().

Region scoping is re-checked on EVERY object returned/touched, whether
by search_object() or get_field() -- this is what stops a link hop (or
now, a broader search) from being used to route around the boundary.

Called by: core/agent/loop.py (via core/ontology/, once that exists)
"""

from pathlib import Path

from connectors.sqlite_connector import connect, run_query, run_query_one
from core.ontology.schema import get_field_info, is_link_field, get_link_target
from deployments.acme_corp.deployment import SCHEMA

DB_PATH = Path(__file__).resolve().parent / "dev_fixtures" / "mediator.db"

TABLE_MAP = {
    "Customer": {"table": "customers", "id_column": "customer_id"},
    "Transaction": {"table": "transactions", "id_column": "transaction_id"},
}


def _region_allowed(conn, object_type: str, object_id, requesting_user_region: str) -> bool:
    """The per-hop enforcement check. Re-run on every field access AND
    on every candidate returned by search_object()."""
    if object_type == "Customer":
        row = run_query_one(
            conn, "SELECT region FROM customers WHERE customer_id = ?", (object_id,)
        )
    elif object_type == "Transaction":
        row = run_query_one(
            conn,
            "SELECT c.region AS region FROM transactions t "
            "JOIN customers c ON t.customer_id = c.customer_id "
            "WHERE t.transaction_id = ?",
            (object_id,),
        )
    else:
        return False

    return row is not None and row["region"] == requesting_user_region


def _filterable_columns(object_type: str) -> set:
    """id_field + data fields + link fields with cardinality 'one'
    (real FK columns). Excludes cardinality 'many' -- those are
    computed reverse relationships, not real columns."""
    obj = SCHEMA[object_type]
    columns = {obj["id_field"]}
    for field_name, info in obj["fields"].items():
        if info["type"] == "data":
            columns.add(field_name)
        elif info["type"] == "link" and info.get("cardinality") == "one":
            columns.add(field_name)
    return columns


def search_object(requesting_user_region: str, object_type: str, filter: dict) -> list:
    if object_type not in TABLE_MAP:
        raise ValueError(f"Unknown object_type: {object_type}")

    valid_columns = _filterable_columns(object_type)
    for key in filter:
        if key not in valid_columns:
            raise ValueError(
                f"Cannot filter {object_type} by {key!r} "
                f"(valid: {sorted(valid_columns)})"
            )

    table = TABLE_MAP[object_type]["table"]
    id_column = TABLE_MAP[object_type]["id_column"]

    # Column NAMES are whitelisted above before ever touching this string;
    # VALUES are always passed as bound parameters, never interpolated.
    where_clause = " AND ".join(f"{key} = ?" for key in filter.keys())
    values = tuple(filter.values())

    conn = connect(DB_PATH)
    try:
        if where_clause:
            rows = run_query(
                conn, f"SELECT {id_column} FROM {table} WHERE {where_clause}", values
            )
        else:
            rows = run_query(conn, f"SELECT {id_column} FROM {table}")

        candidate_ids = [row[id_column] for row in rows]

        # Per-result region enforcement -- a broader search doesn't bypass
        # the same boundary a single-ID lookup already enforced.
        return [
            cid for cid in candidate_ids
            if _region_allowed(conn, object_type, cid, requesting_user_region)
        ]
    finally:
        conn.close()


def get_field(requesting_user_region: str, object_type: str, object_id, field_name: str):
    field_info = get_field_info(SCHEMA, object_type, field_name)

    conn = connect(DB_PATH)
    try:
        if not _region_allowed(conn, object_type, object_id, requesting_user_region):
            return None

        if is_link_field(field_info):
            target = get_link_target(field_info)

            if object_type == "Customer" and field_name == "transactions":
                rows = run_query(
                    conn, "SELECT transaction_id FROM transactions WHERE customer_id = ?",
                    (object_id,),
                )
                return [r["transaction_id"] for r in rows]

            if object_type == "Transaction" and field_name == "customer_id":
                row = run_query_one(
                    conn, "SELECT customer_id FROM transactions WHERE transaction_id = ?",
                    (object_id,),
                )
                return row["customer_id"] if row else None

            raise ValueError(f"No resolver for link field {object_type}.{field_name}")

        table = TABLE_MAP[object_type]["table"]
        id_column = TABLE_MAP[object_type]["id_column"]
        row = run_query_one(
            conn, f"SELECT {field_name} FROM {table} WHERE {id_column} = ?", (object_id,)
        )
        return row[field_name] if row else None
    finally:
        conn.close()
