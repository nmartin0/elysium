"""
sql_adapter.py  (generic SQL-backed ontology engine -- org-agnostic)

OntologyEngine binds ONE database + ONE schema together and provides
search_object()/get_field() as methods. This used to be plain functions
combined with functools.partial to bind db_path/schema at the deployment
level -- a class is the more discoverable way to say "this engine is
bound to this database": db_path and schema were being passed to every
single call, which is exactly the "same parameters, many calls" signal
that means a class fits better than free functions.

The engine is driven entirely by whatever schema dict it's constructed
with -- table/id_column per object type, which fields are data vs. link
(and link cardinality/target), via_table/via_column for reverse ("many")
links, and a "security" block per object type describing how to find
that object's row-level access-control value: either a field on the
object itself, or by following a forward link to another object that
holds it. No table names, column names, or org-specific concepts are
hardcoded anywhere -- everything comes from the schema.

Used by: deployments/<org>/ontology_adapter.py (constructs one instance
         with this org's own db_path and schema), and directly by
         tests/unit/test_sql_adapter.py
"""

from contextlib import contextmanager
from pathlib import Path

from connectors.sqlite_connector import connect, run_query, run_query_one
from core.ontology.schema import get_field_info, is_link_field, get_link_target, is_searchable_field


class OntologyEngine:
    def __init__(self, db_path: Path, schema: dict):
        # db_path and schema stay fixed for the lifetime of this engine --
        # every search_object()/get_field() call reuses them, rather than
        # having every call re-pass the same two arguments.
        self.db_path = db_path
        self.schema = schema

    @contextmanager
    def _connection(self):
        # The only place in this class that OPENS or CLOSES a connection
        # -- other methods (like _get_security_value) still touch the
        # database, but only via a conn they're handed, never by calling
        # this themselves. One place guaranteeing the connection always
        # gets closed, instead of each entry-point method repeating its
        # own try/finally.
        conn = connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _type_schema(self, object_type: str) -> dict:
        # The single place that looks up one object type's schema entry.
        # Every method needing it goes through here, so "is this
        # object_type even known" is checked consistently everywhere --
        # previously a couple of internal methods skipped this check and
        # would have raised a raw, unhelpful KeyError instead.
        type_schema = self.schema.get(object_type)
        if type_schema is None:
            raise ValueError(f"Unknown object_type: {object_type}")
        return type_schema

    def _get_security_value(self, conn, object_type: str, object_id):
        # Resolves the row-level security value for one object, following
        # a via_field link if this object type doesn't hold it directly.
        # Assumes security chains terminate (no circular via_field refs).
        type_schema = self._type_schema(object_type)
        security = type_schema["security"]
        table = type_schema["table"]
        id_column = type_schema["id_column"]

        if "field" in security:
            row = run_query_one(
                conn, f"SELECT {security['field']} FROM {table} WHERE {id_column} = ?",
                (object_id,),
            )
            return row[security["field"]] if row else None

        if "via_field" in security:
            via_field = security["via_field"]
            target_type = type_schema["fields"][via_field]["target"]

            row = run_query_one(
                conn, f"SELECT {via_field} FROM {table} WHERE {id_column} = ?", (object_id,)
            )
            if row is None:
                return None
            return self._get_security_value(conn, target_type, row[via_field])

        raise ValueError(f"No security resolution declared for object_type {object_type!r}")

    def _security_allowed(self, conn, object_type: str, object_id,
                           requesting_user_security_value: str) -> bool:
        # The per-hop enforcement check. Re-run on every object touched --
        # by search_object() for every candidate, and by get_field() before
        # reading any field -- so a link hop can never bypass this boundary.
        security_value = self._get_security_value(conn, object_type, object_id)
        return security_value is not None and security_value == requesting_user_security_value

    def _filterable_columns(self, object_type: str) -> set:
        # Every column search_object() is allowed to filter by for this
        # object type -- the id_field always, plus whatever
        # is_searchable_field() says (see core/ontology/schema.py for
        # the actual rule).
        type_schema = self._type_schema(object_type)
        columns = {type_schema["id_field"]}
        for field_name, field_info in type_schema["fields"].items():
            if is_searchable_field(field_info):
                columns.add(field_name)
        return columns

    def search_object(self, requesting_user_security_value: str,
                       object_type: str, criteria: dict) -> list:
        # Finds object(s) of one type matching search criteria, returns
        # only their IDs -- and only the ones the requesting user is
        # allowed to see. Named "criteria" rather than "filter" so this
        # doesn't shadow Python's own builtin filter() function.
        type_schema = self._type_schema(object_type)

        valid_columns = self._filterable_columns(object_type)
        for key in criteria:
            if key not in valid_columns:
                raise ValueError(
                    f"Cannot filter {object_type} by {key!r} (valid: {sorted(valid_columns)})"
                )

        table = type_schema["table"]
        id_column = type_schema["id_column"]

        # Column NAMES are whitelisted above; VALUES are always bound params.
        where_clause = " AND ".join(f"{key} = ?" for key in criteria.keys())
        values = tuple(criteria.values())

        with self._connection() as conn:
            if where_clause:
                rows = run_query(
                    conn, f"SELECT {id_column} FROM {table} WHERE {where_clause}", values
                )
            else:
                rows = run_query(conn, f"SELECT {id_column} FROM {table}")

            candidate_ids = [row[id_column] for row in rows]
            return [
                candidate_id for candidate_id in candidate_ids
                if self._security_allowed(conn, object_type, candidate_id, requesting_user_security_value)
            ]

    def _resolve_reverse_link(self, conn, field_info: dict, object_id) -> list:
        # A reverse link (cardinality "many") isn't a real column -- find
        # it by querying the OTHER table for rows that point back at
        # this object.
        via_table = field_info["via_table"]
        via_column = field_info["via_column"]
        target_type = get_link_target(field_info)
        target_id_column = self.schema[target_type]["id_column"]

        rows = run_query(
            conn, f"SELECT {target_id_column} FROM {via_table} WHERE {via_column} = ?",
            (object_id,),
        )
        return [row[target_id_column] for row in rows]

    def get_field(self, requesting_user_security_value: str,
                  object_type: str, object_id, field_name: str):
        # Returns one field's value. If it's a link field, the value is
        # another object's ID (or list of IDs for a reverse link) -- the
        # caller can immediately pass that into search_object() or
        # get_field() again, which is what makes link traversal fall out
        # of this one method rather than needing a separate primitive.
        field_info = get_field_info(self.schema, object_type, field_name)
        type_schema = self._type_schema(object_type)

        with self._connection() as conn:
            if not self._security_allowed(conn, object_type, object_id, requesting_user_security_value):
                return None

            if is_link_field(field_info) and field_info.get("cardinality") == "many":
                return self._resolve_reverse_link(conn, field_info, object_id)

            # Plain data field OR forward link (cardinality "one") -- both
            # are just a literal column on this object's own row, read
            # identically, no special-casing needed for forward links.
            table = type_schema["table"]
            id_column = type_schema["id_column"]
            row = run_query_one(
                conn, f"SELECT {field_name} FROM {table} WHERE {id_column} = ?", (object_id,)
            )
            return row[field_name] if row else None
