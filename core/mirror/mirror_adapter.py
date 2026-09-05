"""
mirror_adapter.py  (reads from the local Iceberg mirror, satisfying the
same contract as a real, live silo adapter)

Phase 4 of the read-only mirror architecture (see ROADMAP.md). This is
a real ExternalReadAdapter -- the SAME four-method contract
adapters/sqlite_adapter.py's own SQLiteReadAdapter implements -- so
DataMediator, search_object(), get_field(), MDO resolution and reverse
links all work against it completely unchanged. Confirmed directly by
reading the real code before designing this: every read in
DataMediator resolves its adapter through _adapter_for() or
_resolve_shared_storage(), so swapping WHICH adapters the mediator
holds is genuinely the whole cutover. No read logic changes at all.

QUERIES VIA PYICEBERG, NOT DUCKDB'S ICEBERG EXTENSION -- a real,
verified choice rather than a limitation worked around. DuckDB can
genuinely write to and read Iceberg (v1.4.0+), but its own docs are
explicit that catalog-managed access -- the full feature set --
requires attaching an Iceberg REST catalog (Polaris, Lakekeeper, S3
Tables), and this project deliberately uses a SQLite catalog to avoid
running a separate catalog SERVICE. PyIceberg reads the catalog
natively and hands back an Arrow table; DuckDB can query THAT
directly if a future caller needs real SQL over it (verified
directly). So nothing here is blocked by that constraint.

PUSHDOWN IS REAL, not a scan-everything-then-filter fallback --
verified directly before relying on it: PyIceberg's own scan()
supports both row_filter (predicate pushdown) and selected_fields
(column projection). find_ids() pushes its criteria down as a real
Iceberg expression; every method projects only the columns it
actually needs.

EVERYTHING IS A STRING, matching what the sync writes. core/mirror/
iceberg_sync.py deliberately stores every column as a string (see its
own docstring for why: inferring types per-sync would let a table's
mirror schema CHANGE between runs purely because its data changed).
So criteria values are stringified here before comparison, and
returned ids are strings. A real, honest consequence stated plainly:
an id that is an integer in the source comes back as a string from
the mirror, so a caller comparing ids across the two modes must
account for that. This is exactly the kind of difference the
side-by-side verification in Phase 4 exists to surface.

NO SECURITY LOGIC HERE, same as every other adapter -- purely
mechanical. DataMediator has already made every RBAC/MAC decision
before calling anything on this class.

Used by: core/deployment_loader.py, when a deployment opts into
         mirror-backed reads
"""

from typing import Any

from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.exceptions import NoSuchNamespaceError, NoSuchTableError
from pyiceberg.expressions import And, BooleanExpression, EqualTo

from core.ontology.interface import ExternalReadAdapter


class MirrorReadAdapter(ExternalReadAdapter):
    # Reads from local Parquet through PyIceberg -- genuinely fine
    # concurrently, no per-backend limit to declare.
    max_concurrent_reads = None

    def __init__(self, catalog: SqlCatalog, silo_name: str):
        # Takes an already-built catalog rather than building its own:
        # one catalog is shared by every silo's adapter, since they all
        # read the same mirror. silo_name is what maps this adapter to
        # its own Iceberg namespace -- the same 1:1 silo-to-namespace
        # layout core/mirror/iceberg_sync.py writes.
        self._catalog = catalog
        self.silo_name = silo_name

    def find_ids(self, object_type: str, criteria: dict, type_config: dict) -> list[Any]:
        table_name = type_config["storage"]["table"]
        id_column = type_config["storage"]["id_column"]

        arrow = self._scan(
            table_name,
            selected_fields=(id_column,),
            row_filter=self._criteria_to_filter(criteria),
        )
        if arrow is None:
            return []
        return arrow.column(id_column).to_pylist()

    def find_ids_matching_text(self, object_type: str, columns: list[str], query_text: str,
                                type_config: dict) -> list[Any]:
        table_name = type_config["storage"]["table"]
        id_column = type_config["storage"]["id_column"]

        if not columns:
            return []

        # Matches SQLiteReadAdapter's own semantics deliberately: a
        # CONTAINS match, ORed across every column, case-insensitive.
        # Done in Python over the projected columns rather than pushed
        # down, because Iceberg's own expression language has no
        # substring predicate -- an honest limitation of the format,
        # not an oversight here. Only the id column plus the searched
        # columns are read, never the whole row, so the cost is real
        # but bounded.
        #
        # No LIKE-wildcard escaping needed at all, unlike the SQLite
        # path: a Python substring check treats % and _ as the literal
        # characters they are, so the entire class of bug that
        # escaping exists to prevent simply cannot occur here.
        arrow = self._scan(table_name, selected_fields=(id_column, *columns))
        if arrow is None:
            return []

        needle = query_text.casefold()
        rows = arrow.to_pylist()
        return [
            row[id_column]
            for row in rows
            if any(
                row.get(column) is not None and needle in str(row[column]).casefold()
                for column in columns
            )
        ]

    def get_raw_field(self, object_type: str, object_id: Any, field_name: str, type_config: dict) -> Any:
        table_name = type_config["storage"]["table"]
        id_column = type_config["storage"]["id_column"]

        arrow = self._scan(
            table_name,
            selected_fields=(field_name,),
            # The type: ignore[call-arg] on every EqualTo call in this
            # file marks a real mypy/Pydantic inference limitation, not
            # a genuine error: PyIceberg's EqualTo is a Pydantic model,
            # so mypy infers a field-based __init__ that doesn't match
            # the real one. Verified directly at runtime that
            # EqualTo(term=..., literal=...) is the correct, working
            # form, and that omitting `literal` genuinely raises.
            row_filter=EqualTo(term=id_column, literal=str(object_id)),  # type: ignore[call-arg]
        )
        if arrow is None or arrow.num_rows == 0:
            # Matches SQLiteReadAdapter exactly: a missing row is None,
            # never an error.
            return None
        return arrow.column(field_name)[0].as_py()

    def resolve_reverse_link(self, object_id: Any, field_config: dict, target_id_column: str) -> list[Any]:
        via_table = field_config["via_table"]
        via_column = field_config["via_column"]

        arrow = self._scan(
            via_table,
            selected_fields=(target_id_column,),
            row_filter=EqualTo(term=via_column, literal=str(object_id)),  # type: ignore[call-arg]
        )
        if arrow is None:
            return []
        return arrow.column(target_id_column).to_pylist()

    def _scan(self, table_name: str, selected_fields: tuple[str, ...], row_filter=None):
        try:
            table = self._catalog.load_table(f"{self.silo_name}.{table_name}")
        except (NoSuchTableError, NoSuchNamespaceError):
            # A table the mirror has never synced. Returning None (and
            # so, empty results) rather than raising is deliberate and
            # matches how the live path behaves for a genuinely empty
            # table -- but it is also exactly the case the Phase 4
            # side-by-side verification is meant to catch, since an
            # un-synced table looks identical to an empty one from
            # here. The sync itself fails loudly when a table it
            # EXPECTED is missing (see scripts/run_sync.py); that is
            # where that error genuinely belongs.
            return None

        scan = table.scan(selected_fields=selected_fields)
        if row_filter is not None:
            scan = table.scan(selected_fields=selected_fields, row_filter=row_filter)
        return scan.to_arrow()

    def _criteria_to_filter(self, criteria: dict):
        # Every value stringified, matching what the sync writes -- see
        # this module's own docstring.
        if not criteria:
            return None
        terms: list[BooleanExpression] = [
            EqualTo(term=column, literal=str(value))  # type: ignore[call-arg]
            for column, value in criteria.items()
        ]
        if len(terms) == 1:
            return terms[0]
        combined = terms[0]
        for term in terms[1:]:
            combined = And(combined, term)
        return combined
