"""
ontology_adapter.py  (acme_corp-specific -- NOT portable to other orgs)

Implements the two generic ontology primitives for this deployment's
actual database:

  search_object(user_region, object_type, filter) -> list of object IDs
  get_field(user_region, object_type, object_id, field_name) -> value

Region scoping is re-checked on EVERY call to either function, based on
the object actually being touched -- not just once at the start of a
request. This is what stops a link hop from being used to route around
the boundary: whether you reach a Transaction by searching for it
directly or by following a link from a Customer, get_field() checks that
specific transaction's owning customer's region every time.

Uses connectors/sqlite_connector.py (generic) + deployments/acme_corp/
ontology_schema.py (this deployment's field shape) together.

Called by: core/ontology/ (via the agent loop, once that exists)
"""

from pathlib import Path

from connectors.sqlite_connector import connect, run_query, run_query_one
from core.ontology.schema import get_field_info, is_link_field, get_link_target
from deployments.acme_corp.ontology_schema import SCHEMA

DB_PATH = Path(__file__).resolve().parent / "dev_fixtures" / "mediator.db"

# object_type -> its table and primary key column
TABLE_MAP = {
    "Customer": {"table": "customers", "id_column": "customer_id"},
    "Transaction": {"table": "transactions", "id_column": "transaction_id"},
}


def _region_allowed(conn, object_type: str, object_id, requesting_user_region: str) -> bool:
    """The per-hop enforcement check. Re-run on every field access."""
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


def search_object(requesting_user_region: str, object_type: str, filter: dict) -> list:
    """
    Minimal version: only supports looking up one object by its own ID
    column (e.g. {"customer_id": "cust_001"}). Returns [] if the object
    doesn't exist OR is outside the requesting user's region -- the two
    cases are deliberately indistinguishable from the caller's side.
    """
    if object_type not in TABLE_MAP:
        raise ValueError(f"Unknown object_type: {object_type}")

    id_column = TABLE_MAP[object_type]["id_column"]
    if list(filter.keys()) != [id_column]:
        raise ValueError(f"search_object only supports filtering by {id_column!r} for now")

    candidate_id = filter[id_column]

    conn = connect(DB_PATH)
    try:
        if not _region_allowed(conn, object_type, candidate_id, requesting_user_region):
            return []
        return [candidate_id]
    finally:
        conn.close()


def get_field(requesting_user_region: str, object_type: str, object_id, field_name: str):
    """
    Returns one field's value. If it's a link field, the value is another
    object's ID (or list of IDs) -- the caller can immediately pass that
    into search_object() or get_field() again, which is what makes link
    traversal fall out of this one function rather than needing a
    separate "follow link" primitive.
    """
    # Validated against the schema FIRST -- field_name below is only ever
    # one of a fixed, known set of column names by the time it reaches
    # any SQL, never arbitrary caller input.
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

        # Plain data field -- id_column/table come from TABLE_MAP (not
        # user input); field_name was already whitelisted above.
        table = TABLE_MAP[object_type]["table"]
        id_column = TABLE_MAP[object_type]["id_column"]
        row = run_query_one(
            conn, f"SELECT {field_name} FROM {table} WHERE {id_column} = ?", (object_id,)
        )
        return row[field_name] if row else None
    finally:
        conn.close()
