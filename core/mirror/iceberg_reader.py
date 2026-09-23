"""Reading an Iceberg namespace: the mechanics, shared (GOLD-3).

WHY THIS EXISTS SEPARATELY. Two things read Iceberg tables now -- the
MIRROR ADAPTER, which presents a source's copy to the ontology as if
it were the source, and the GOLD CONNECTOR, which presents gold. They
have different concerns and different interfaces, deliberately (the
owner, September 22: adapters are for reading the customer's systems;
reading our own lake is a connector's job).

WHAT THEY MUST NOT HAVE TWICE is the Iceberg part: the snapshot cache
that made mirrored reads 8-11x faster (E-10), the filter building that
learned to quantise decimals (F-20), and the literal handling that
learned the words a source writes for true and false (F-01). Every one
of those was a bug found and fixed once. A second copy would keep the
bug that the copy was made before.

So the MECHANICS live here, keyed by a catalog and a namespace, and
the two readers above are thin things that decide WHAT to ask for.
This module knows nothing about object types, security or the
ontology -- it takes a table name and returns rows.
"""

from collections.abc import Mapping
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
from pyiceberg.expressions.visitors import bind
from pyiceberg.io.pyarrow import expression_to_pyarrow

from core.filters import UnsupportedFilter
from core.mirror.snapshot_cache import SnapshotCache

# A table is read whole into the cache only up to this many rows, judged
# from its snapshot summary BEFORE reading. Beyond it, reads scan directly,
# with any limit pushed into the scan.
MAX_CACHED_ROWS = 200_000


class IcebergNamespaceReader:
    """Scans, filters and caches within ONE Iceberg namespace."""

    def __init__(self, catalog: SqlCatalog, namespace: str,
                 snapshot_ids: "Mapping[str, int] | None" = None):
        self._catalog = catalog
        self.namespace = namespace
        # PINNED, or not: a generation pins the snapshot it was built
        # against so a reload cannot move the ground under a request
        # mid-flight. Absent, every read sees the table's current
        # state, which is what a test or a one-off script wants.
        self._snapshot_ids = dict(snapshot_ids or {})
        self._snapshot_cache = SnapshotCache()
        # Tables measured too big to hold in memory, per snapshot: asked
        # once, remembered, so a large table is not re-measured on every
        # read (E-10).
        self._too_large_to_cache: set[tuple[str, int]] = set()

    def _cached_table(self, table_name: str):
        """(arrow table, iceberg schema) for this table at the snapshot
        this adapter reads, from the cache or read whole into it -- or None
        when it cannot be served that way, and _scan reads directly.

        A PINNED snapshot already cached needs no catalog access at all.
        A table whose snapshot reports more than MAX_CACHED_ROWS rows is
        never read whole: its summary is consulted BEFORE any data, so the
        limit pushed into a direct scan keeps meaning what it says.
        """
        pinned = self._snapshot_ids.get(table_name)
        if pinned is not None:
            hit = self._snapshot_cache.get((table_name, pinned))
            if hit is not None:
                return hit
        try:
            table = self._catalog.load_table(f"{self.namespace}.{table_name}")
        except (NoSuchTableError, NoSuchNamespaceError):
            return None
        snapshot = table.snapshot_by_id(pinned) if pinned is not None else table.current_snapshot()
        if snapshot is None:
            return None
        key = (table_name, snapshot.snapshot_id)
        hit = self._snapshot_cache.get(key)
        if hit is not None:
            return hit
        if key in self._too_large_to_cache:
            return None
        summary = snapshot.summary
        records = summary.get("total-records") if summary is not None else None
        if records is None or int(records) > MAX_CACHED_ROWS:
            self._too_large_to_cache.add(key)
            return None
        # The schema the snapshot was WRITTEN with, not today's.
        schema = next((s for s in table.schemas().values() if s.schema_id == snapshot.schema_id),
                      table.schema())
        arrow = table.scan(snapshot_id=snapshot.snapshot_id).to_arrow()
        if not self._snapshot_cache.put(key, (arrow, schema), arrow.nbytes):
            self._too_large_to_cache.add(key)
        return arrow, schema
    def _scan(self, table_name: str, selected_fields: tuple[str, ...], row_filter=None,
              limit: int | None = None):
        cached = self._cached_table(table_name)
        if cached is not None:
            arrow, schema = cached
            names = {field.name for field in schema.fields}
            if set(selected_fields) <= names:
                # PYICEBERG'S OWN CONVERSION -- what its reader applies to
                # every batch -- so the rows are the ones a scan returns;
                # checked filter by filter in tests/unit/test_mirror_cache.py.
                if row_filter is not None:
                    arrow = arrow.filter(expression_to_pyarrow(bind(schema, row_filter, case_sensitive=True)))
                # The TABLE's column order, as a scan returns them.
                arrow = arrow.select([field.name for field in schema.fields if field.name in selected_fields])
                if limit is not None and limit > 0:
                    arrow = arrow.slice(0, limit)
                return arrow
        try:
            table = self._catalog.load_table(f"{self.namespace}.{table_name}")
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
        # The pinned snapshot, or the table's current state when this
        # adapter has no pin for it -- a table synced for the first
        # time AFTER this generation was built has no id here, and
        # reading its current state is better than reading nothing.
        snapshot_id = self._snapshot_ids.get(table_name)
        scan_kwargs: dict[str, Any] = {"selected_fields": selected_fields}
        if limit is not None and limit > 0:
            # PYICEBERG TAKES A LIMIT NATIVELY, so this stops rows
            # being read rather than trimming them afterwards -- which
            # is the whole point, and would not have been true if the
            # cap had to be applied to a materialised table.
            scan_kwargs["limit"] = limit
        if row_filter is not None:
            scan_kwargs["row_filter"] = row_filter
        if snapshot_id is not None:
            scan_kwargs["snapshot_id"] = snapshot_id
        return table.scan(**scan_kwargs).to_arrow()
    def _decimal_columns(self, table_name: str) -> set:
        """Which columns of one mirrored table are decimals.

        READ FROM THE TABLE, not from the ontology. The scale that
        matters is the one the data is STORED at, and a filter has to
        match it exactly -- pyiceberg refuses a mismatch rather than
        widening.
        """
        try:
            cached = self._cached_table(table_name)
            schema = cached[1] if cached is not None else \
                self._catalog.load_table(f"{self.namespace}.{table_name}").schema()
            return {
                column.name for column in schema.fields
                if str(column.field_type).startswith("decimal")
            }
        except Exception:  # noqa: BLE001 - a filter still works unquantized
            return set()
    def _conditions_to_filter(self, conditions: list,
                              decimal_columns: set | None = None):
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

        # WHICH COLUMNS ARE DECIMALS, from the MIRROR'S OWN schema
        # rather than the ontology's. The scale that matters is the
        # one the data is stored at, and this adapter reads the
        # table anyway.
        decimal_columns = decimal_columns or set()
        terms: list[BooleanExpression] = []
        for condition in conditions:
            terms.append(self._term_for(condition, decimal_columns))

        combined = terms[0]
        for term in terms[1:]:
            combined = And(combined, term)
        return combined
    def _decimal_literal(self, field: str, value, decimal_columns: set):
        """A decimal comparison at the SCALE THE COLUMN USES.

        PyIceberg refuses a mismatch outright: filtering `amount ==
        49.99` against a decimal(38, 9) column raised "could not
        convert 49.99 into a decimal(38, 9), scales differ 9 <> 2".

        So a person filtering on a price had to type NINE DECIMAL
        PLACES, or get an error naming a storage detail they never
        chose. Found by a test of the trigger evaluator, not by the
        decimal work that introduced it -- the live path coerces on
        READ and nothing coerced on FILTER.

        UNRECOGNISED VALUES PASS THROUGH UNCHANGED. A value that is
        not a number is somebody else's error to report, and
        swallowing it here would turn a clear message into an empty
        result.
        """
        from decimal import Decimal, InvalidOperation

        from core.ontology.field_types import DECIMAL_SCALE

        if field not in decimal_columns:
            return str(value)
        try:
            return str(Decimal(str(value)).quantize(
                Decimal(1).scaleb(-DECIMAL_SCALE),
            ))
        except (InvalidOperation, ValueError, ArithmeticError):
            return str(value)
    def _term_for(self, condition, decimal_columns: set | None = None):
        # DEFAULTS TO NONE so a caller that knows of no decimal columns
        # -- including the vocabulary test, which checks every operator
        # is handled or declined -- can build a term without inventing
        # a schema.
        decimal_columns = decimal_columns or set()
        field, operator, value = condition.field, condition.operator, condition.value

        if operator == "equals":
            return EqualTo(  # type: ignore[call-arg]
                term=field,
                literal=self._decimal_literal(field, value, decimal_columns),
            )
        # THROUGH _decimal_literal, LIKE equals (001's F-20). These used
        # str(item), so on a decimal column pyiceberg refused the
        # literal outright -- "could not convert 49.99 into a
        # decimal(38, 9), scales differ 9 <> 2". Reproduced on the
        # shipped deployment: `amount equals 49.99` returned 2 rows
        # while `amount in [49.99]` raised. A chart's "keep"
        # cross-filter IS an `in`, so clicking a bar on a money chart
        # was an error.
        if operator == "in":
            return In(  # type: ignore[call-arg]
                term=field,
                literals=[self._decimal_literal(field, item, decimal_columns) for item in value],
            )
        if operator == "not_in":
            return NotIn(  # type: ignore[call-arg]
                term=field,
                literals=[self._decimal_literal(field, item, decimal_columns) for item in value],
            )
        if operator in ("range", "date_range"):
            low = value.get("min") if operator == "range" else value.get("start")
            high = value.get("max") if operator == "range" else value.get("end")
            # ANNOTATED because the two bounds are different types and
            # mypy otherwise infers the list from whichever is appended
            # first.
            bounds: list[BooleanExpression] = []
            # AND THE BOUNDS TOO: a raw bound against a decimal column
            # is refused the same way. Nothing reaches this today --
            # validate_filter declines `range` on a decimal field (see
            # the roadmap's open question about filtering money by
            # amount) -- so this is the operator being made correct
            # before that question is answered, not a fix for a live
            # path.
            if low is not None:
                bounds.append(GreaterThanOrEqual(  # type: ignore[call-arg]
                    term=field, literal=self._decimal_literal(field, low, decimal_columns),
                ))
            if high is not None:
                bounds.append(LessThanOrEqual(  # type: ignore[call-arg]
                    term=field, literal=self._decimal_literal(field, high, decimal_columns),
                ))
            return bounds[0] if len(bounds) == 1 else And(bounds[0], bounds[1])

        # `contains` and anything added later that Iceberg cannot
        # express.
        raise UnsupportedFilter(
            f"the mirror cannot express {operator!r}"
        )
