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

QUERIES VIA PYICEBERG, and no second query engine. DuckDB was
considered for the read side and rejected after measuring rather than
assuming: PyIceberg already serves every read this adapter performs,
with real predicate pushdown (row_filter) and column projection
(selected_fields). The one operation Iceberg's expression language
cannot express is substring search, done in Python below -- measured
at 16ms against 12ms in DuckDB over 100,000 rows, with Python faster
at smaller sizes where DuckDB's per-query overhead dominates. A 4ms
difference does not buy a dependency, a second engine, and two ways to
express every read. See ROADMAP.md's Phase 4 section for the full
measurements.

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
from pyiceberg.expressions import (
    And,
    BooleanExpression,
    EqualTo,
    GreaterThanOrEqual,
    In,
    LessThanOrEqual,
    NotIn,
)

from core.filters import UnsupportedFilter
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

    # Iceberg has In, NotIn and range comparisons natively. It has NO
    # substring predicate -- StartsWith is the closest and is not the
    # same thing -- so `contains` is absent and the mediator applies it
    # here in Python. Translating it to StartsWith would return a
    # SUBSET of the right rows and look like it worked.
    pushable_operators = frozenset({"equals", "in", "not_in", "range", "date_range"})

    def find_ids(self, object_type: str, conditions: list, type_config: dict) -> list[Any]:
        table_name = type_config["storage"]["table"]
        id_column = type_config["storage"]["id_column"]

        arrow = self._scan(
            table_name,
            selected_fields=(id_column,),
            row_filter=self._conditions_to_filter(conditions),
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

    def resolve_reverse_links_batch(self, object_ids: list, field_config: dict,
                                     target_id_column: str) -> dict:
        # One scan projecting the target id and the via column, then
        # grouped in Python. Iceberg's expression language has no IN
        # predicate over an arbitrary list, so the filter is applied
        # after the scan -- still ONE read rather than one per source
        # object, which is the property that matters here.
        if not object_ids:
            return {}

        via_table = field_config["via_table"]
        via_column = field_config["via_column"]
        result_column = field_config.get("via_target_column", target_id_column)
        arrow = self._scan(via_table, selected_fields=(result_column, via_column))
        if arrow is None:
            return {}

        wanted = {str(object_id) for object_id in object_ids}
        grouped: dict = {}
        for row in arrow.to_pylist():
            source = row[via_column]
            if str(source) not in wanted:
                continue
            grouped.setdefault(source, []).append(row[result_column])
        return grouped

    def health_check(self) -> None:
        # Listing namespaces proves the catalog is reachable without
        # reading any table. An empty mirror is HEALTHY -- it has not
        # been synced yet, which is an operational state, not a fault.
        self._catalog.list_namespaces()

    def read_fields_for_ids(self, table_name: str, id_column: str, object_ids: list,
                             columns: list[str], type_config: dict) -> list[dict]:
        # Iceberg's expression language has no IN predicate over an
        # arbitrary list, so the filter is applied after a PROJECTED
        # scan -- the same compromise resolve_reverse_links_batch()
        # makes. Still narrower than read_all_rows(), which projects
        # nothing.
        if not object_ids:
            return []
        arrow = self._scan(table_name, selected_fields=tuple(dict.fromkeys([id_column, *columns])))
        if arrow is None:
            return []
        wanted = {str(object_id) for object_id in object_ids}
        return [row for row in arrow.to_pylist() if str(row[id_column]) in wanted]

    def read_all_rows(self, table_name: str, columns: list[str], type_config: dict) -> list[dict]:
        # Implemented for contract completeness rather than for a real
        # caller: the sync reads from the customer's own source, never
        # from the mirror it writes. A mirror-to-mirror copy is not a
        # thing this system does. Kept honest rather than raising
        # NotImplementedError, since it is trivially expressible here
        # and a future caller (a re-export, a diff tool) would
        # reasonably expect it to work.
        if not columns:
            return []
        arrow = self._scan(table_name, selected_fields=tuple(columns))
        if arrow is None:
            return []
        return arrow.to_pylist()

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

        # Built once, with the filter folded in -- the previous version
        # called table.scan() twice when a filter was present and threw
        # the first result away. Harmless but wasteful, and misleading
        # to read.
        if row_filter is None:
            scan = table.scan(selected_fields=selected_fields)
        else:
            scan = table.scan(selected_fields=selected_fields, row_filter=row_filter)
        return scan.to_arrow()

    def _conditions_to_filter(self, conditions: list):
        """Filter conditions as an Iceberg expression.

        Iceberg has In, NotIn and range comparisons natively, so most
        of the vocabulary pushes down. It has NO substring predicate --
        StartsWith is the closest, and is not the same thing -- so
        `contains` is declined and the mediator applies it in Python.

        Declining is honest. Translating `contains` to StartsWith would
        return a subset of the right rows and look like it worked,
        which is the failure mode this project keeps finding: a wrong
        answer that reports success.
        """
        if not conditions:
            return None

        terms: list[BooleanExpression] = []
        for condition in conditions:
            terms.append(self._term_for(condition))

        combined = terms[0]
        for term in terms[1:]:
            combined = And(combined, term)
        return combined

    def _term_for(self, condition):
        field, operator, value = condition.field, condition.operator, condition.value

        if operator == "equals":
            return EqualTo(term=field, literal=str(value))  # type: ignore[call-arg]
        if operator == "in":
            return In(term=field, literals=[str(item) for item in value])  # type: ignore[call-arg]
        if operator == "not_in":
            return NotIn(term=field, literals=[str(item) for item in value])  # type: ignore[call-arg]
        if operator in ("range", "date_range"):
            low = value.get("min") if operator == "range" else value.get("start")
            high = value.get("max") if operator == "range" else value.get("end")
            bounds = []
            if low is not None:
                bounds.append(GreaterThanOrEqual(term=field, literal=low))  # type: ignore[call-arg]
            if high is not None:
                bounds.append(LessThanOrEqual(term=field, literal=high))  # type: ignore[call-arg]
            return bounds[0] if len(bounds) == 1 else And(bounds[0], bounds[1])

        # `contains` and anything added later that Iceberg cannot
        # express.
        raise UnsupportedFilter(
            f"the mirror cannot express {operator!r}"
        )
