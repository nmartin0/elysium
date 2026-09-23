"""Reading GOLD, from inside Elysium (GOLD-3b).

NOT AN ADAPTER, DELIBERATELY. The owner, September 22: adapters are
strictly for reading the customer's source databases, as the first
step of the pipeline; reading our own lake is a connector's job,
because the concerns are different.

    AN ADAPTER faces a system Elysium does not control: credentials, a
    network, per-silo concurrency limits, health checks that can fail
    for a dozen reasons, unknown column types, schema DRIFT, and data
    that must be treated as untrusted. It is read-only by
    construction, and that is a security property.

    A CONNECTOR faces data Elysium wrote itself: no credentials, no
    network, no drift -- the schema is ours, generated from the
    declaration -- a snapshot PINNED per generation, and a cache keyed
    by that snapshot. It needs none of the adapter's apparatus and
    should not inherit it.

WHAT IT SHARES ANYWAY is the Iceberg machinery, through
IcebergNamespaceReader: the snapshot cache (E-10), the decimal
quantising (F-20) and the true/false literals (F-01). Those are one
implementation on purpose -- see iceberg_reader.py -- because a second
copy keeps whichever bug the copy was made before.

WHAT IT IS ASKED, AND IN WHOSE TERMS. The mediator hands it a
type_config from the GOLD VIEW (core/ontology/gold_view.py), where a
table is an OBJECT TYPE, a column is a PROPERTY, and a reverse link
names the target's gold table. So the connector never sees a silo, a
source table or a source column name: those words have no meaning
here.

WHAT IT DOES NOT DO, and the difference is the point:

    no drift detection    gold's schema is generated from the
                          declaration; a mismatch is a bug in us, not
                          news about somebody else's database.
    no write path         gold is derived. A write goes to the
                          customer's database through the adapter
                          (decision D3).
    no source health      there is no remote end to be unreachable.
                          The failure mode is "gold has not been
                          published yet", which is a different
                          sentence and deserves one.
"""

from typing import Any

from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.exceptions import NoSuchNamespaceError, NoSuchTableError
from pyiceberg.expressions import EqualTo, In

from core.mirror.iceberg_reader import IcebergNamespaceReader
from core.ontology.gold_view import GOLD_NAMESPACE
from core.ontology.interface import StorageUnavailable

# Read in batches, as the mirror adapter does: an In() with fifty
# thousand literals is a filter no engine enjoys.
MAX_IDS_PER_SCAN = 500


class GoldPublicationMissing(StorageUnavailable):
    """An object type has no published gold table to read.

    Its own class because the answer differs from every other storage
    failure: nothing is broken and nothing is unreachable -- gold has
    simply not been built for this type yet, and the fix is to run a
    sync rather than to go looking at a database.
    """


class GoldConnector:
    """Reads published gold tables, in the ontology's own terms."""

    # Local Parquet through PyIceberg: genuinely fine concurrently,
    # with no remote end to rate-limit.
    max_concurrent_reads = None

    # WHAT IT CAN EXPRESS, and it must SAY SO. The mediator pushes only
    # the operators a reader declares, and applies the rest itself --
    # it does not ask and retry. Declaring nothing is therefore not
    # "safe": it means every filter is applied in memory, against raw
    # storage values, which is both slow and WRONG for a decimal, where
    # 49.990000000 does not equal the string '49.99'.
    #
    # FOUND BY THE PARITY TEST (GOLD-3): a decimal filter returned two
    # rows from the mirror and none from gold, because this line was
    # missing. The same engine answers both, so the same set applies.
    pushable_operators = frozenset({"equals", "in", "not_in", "range", "date_range"})

    def __init__(self, catalog: SqlCatalog, snapshot_ids: "dict[str, int] | None" = None):
        # SNAPSHOTS PINNED PER GENERATION. A request reads the
        # publication its generation was built against, so a build
        # finishing mid-request cannot move the ground under it --
        # which is what Iceberg's reader semantics give us, stated as
        # a decision rather than inherited by luck (D3's second half).
        self._reader = IcebergNamespaceReader(catalog, GOLD_NAMESPACE, snapshot_ids)

    # -- the reads the mediator makes ------------------------------

    def find_ids(self, object_type: str, conditions: list, type_config: dict,
                 limit: int | None = None) -> list[Any]:
        table_name = type_config["storage"]["table"]
        id_column = type_config["storage"]["id_column"]
        arrow = self._reader._scan(
            table_name,
            selected_fields=(id_column,),
            row_filter=self._reader._conditions_to_filter(
                conditions, self._reader._decimal_columns(table_name),
            ),
            limit=limit,
        )
        if arrow is None:
            raise GoldPublicationMissing(
                f"{object_type} has no published gold table. Run a sync to build it."
            )
        return [row[id_column] for row in arrow.to_pylist()]

    def find_ids_matching_text(self, object_type: str, columns: list[str], query_text: str,
                                type_config: dict) -> list[Any]:
        """Free text across the named properties, matched in memory.

        The same approach the mirror adapter takes, and for the same
        reason: Iceberg has no LIKE, and an exact-match filter would
        answer a different question from the one asked.
        """
        table_name = type_config["storage"]["table"]
        id_column = type_config["storage"]["id_column"]
        wanted = [column for column in columns if column != id_column]
        arrow = self._reader._scan(table_name, selected_fields=(id_column, *wanted))
        if arrow is None:
            raise GoldPublicationMissing(
                f"{object_type} has no published gold table. Run a sync to build it."
            )
        needle = query_text.casefold()
        found = []
        for row in arrow.to_pylist():
            for column in wanted:
                value = row.get(column)
                if value is not None and needle in str(value).casefold():
                    found.append(row[id_column])
                    break
        return found

    def get_raw_field(self, object_type: str, object_id: Any, field_name: str,
                       type_config: dict) -> Any:
        table_name = type_config["storage"]["table"]
        id_column = type_config["storage"]["id_column"]
        arrow = self._reader._scan(
            table_name,
            selected_fields=(field_name,),
            row_filter=EqualTo(term=id_column, literal=str(object_id)),  # type: ignore[call-arg]
            limit=1,
        )
        if arrow is None or arrow.num_rows == 0:
            return None
        return arrow.to_pylist()[0].get(field_name)

    def read_fields_for_ids(self, table_name: str, id_column: str, object_ids: list,
                             columns: list[str], type_config: dict) -> list[dict]:
        if not object_ids:
            return []
        selected = tuple(dict.fromkeys([id_column, *columns]))
        rows: list[dict] = []
        wanted = [str(object_id) for object_id in object_ids]
        for start in range(0, len(wanted), MAX_IDS_PER_SCAN):
            batch = wanted[start:start + MAX_IDS_PER_SCAN]
            arrow = self._reader._scan(
                table_name,
                selected_fields=selected,
                row_filter=In(term=id_column, literals=batch),  # type: ignore[call-arg,arg-type]
            )
            if arrow is not None:
                rows.extend(arrow.to_pylist())
        return rows

    def read_all_rows(self, table_name: str, columns: list[str],
                       type_config: dict) -> list[dict]:
        arrow = self._reader._scan(table_name, selected_fields=tuple(columns))
        return [] if arrow is None else arrow.to_pylist()

    def resolve_reverse_links_batch(self, object_ids: list, field_config: dict,
                                     target_id_column: str) -> dict:
        """Every target pointing back at each of these objects.

        THE RE-KEYED PART. via_table here is the TARGET'S OBJECT TYPE
        and via_column is the target's PROPERTY that holds the foreign
        key, because the gold view rebound both -- where a source
        adapter would have been handed a physical table and column.
        """
        if not object_ids:
            return {}
        via_table = field_config["via_table"]
        via_column = field_config["via_column"]
        result_column = field_config.get("via_target_column", target_id_column)
        arrow = self._reader._scan(via_table, selected_fields=(result_column, via_column))
        if arrow is None:
            return {}
        wanted = {str(object_id) for object_id in object_ids}
        grouped: dict = {}
        for row in arrow.to_pylist():
            source = row[via_column]
            if source is None or str(source) not in wanted:
                continue
            grouped.setdefault(str(source), []).append(row[result_column])
        return grouped

    def resolve_reverse_link(self, object_id: Any, field_config: dict,
                              target_id_column: str) -> list[Any]:
        return self.resolve_reverse_links_batch(
            [object_id], field_config, target_id_column,
        ).get(str(object_id), [])

    def columns_present(self, table_name: str) -> set[str]:
        """What GOLD holds for this type, as of the pinned publication.

        A table absent from the catalog answers with an empty set, and
        the caller reads that as "every declared property is missing",
        which is accurate for a type gold has not published.
        """
        try:
            table = self._reader._catalog.load_table(f"{GOLD_NAMESPACE}.{table_name}")
        except (NoSuchTableError, NoSuchNamespaceError):
            return set()
        return {field.name for field in table.schema().fields}

    def health_check(self) -> None:
        """Is the lake readable at all.

        Deliberately NOT "is every type published": a type without a
        publication is answered where it is asked, by
        GoldPublicationMissing, which names the type and says what to
        do. A health check that failed for one unbuilt type would take
        the whole deployment down for a condition affecting one.
        """
        try:
            self._reader._catalog.list_namespaces()
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            raise StorageUnavailable(f"the lake could not be read: {exc}") from exc
