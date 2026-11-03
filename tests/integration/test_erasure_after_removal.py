"""Erasure after a whole type has been removed from the ontology.

Removal keeps the type's lake tables on purpose (core/ontology/removal.py),
and erasure used to find a table's key columns from the types that still
exist -- so the day Tag was removed, every later erasure silently skipped
its tables and the people in them stayed for good. Each table now records
its own key columns at every sync (erasure.KEY_COLUMNS_PROPERTY); erasure
falls back to that record, and REFUSES LOUDLY, naming the table, for a
table that holds data and has no record (written before it existed).

THE CHECK IS THE WAREHOUSE'S FILES, as in tests/unit/test_erasure.py.
"""

import contextlib
import io
import logging
import sqlite3

import pyarrow.parquet as pq

from core.deployment_loader import load_deployment
from core.mirror.catalog import open_mirror_catalog
from core.mirror.erasure import (
    KEY_COLUMNS_PROPERTY,
    ErasureRegister,
    apply_erasures,
    recorded_key_columns,
)
from scripts.erase import run as erase
from tests.integration.test_removal_from_the_ui import (  # noqa: F401 - fixtures
    _remove_tag_and_sync_again,
    _sync,
    lake,
    tag_lake,
)

TAG_TABLES = ("bronze_primary_sql.tags", "primary_sql.tags", "gold.Tag", "gold_history.Tag",
              "changelog_primary_sql.tags", "bronze_primary_sql.customer_tags",
              "primary_sql.customer_tags", "gold.customer_tags")


def _source(paths):
    return sqlite3.connect(paths.data_dir / "dev_fixtures" / "mediator.db")


def _a_tag(paths):
    """(tag_id, label as the source now has it) of the tag the helper renamed."""
    with _source(paths) as source:
        return source.execute("SELECT tag_id, label FROM tags ORDER BY tag_id LIMIT 1").fetchone()


def _files_holding(paths, value) -> list[str]:
    holding = []
    for parquet in (paths.data_dir / "mirror" / "warehouse").rglob("*.parquet"):
        table = pq.read_table(parquet)
        for column in table.column_names:
            if value in {str(cell) for cell in table.column(column).to_pylist()}:
                holding.append(str(parquet.relative_to(paths.data_dir)))
                break
    return holding


def _erase(paths, object_type, object_id):
    printed, errors = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(errors):
        code = erase(object_type, object_id, "test request", write=True, paths=paths,
                     requested_by="tester")
    return code, printed.getvalue(), errors.getvalue()


def _rows(paths, identifier):
    catalog = open_mirror_catalog(paths.data_dir / "mirror")
    return catalog.load_table(identifier).scan().to_arrow().to_pylist()


def _forget_what_tables_recorded(paths, identifiers):
    """The lake as a sync BEFORE the property existed left it."""
    catalog = open_mirror_catalog(paths.data_dir / "mirror")
    for identifier in identifiers:
        with catalog.load_table(identifier).transaction() as tx:
            tx.remove_properties(KEY_COLUMNS_PROPERTY)


class TestAfterTheTypeIsRemoved:
    def test_erasing_a_removed_type_s_person_reaches_every_layer(self, tag_lake):  # noqa: F811
        """THE SCENARIO: real sync, remove Tag, erase one tag. Before the
        record, this answered 'No object type' and left every table."""
        _remove_tag_and_sync_again(tag_lake)
        tag_id, label = _a_tag(tag_lake)
        assert "Tag" not in load_deployment(tag_lake.config_dir).schema
        for table in TAG_TABLES:                      # NOT VACUOUS: each holds the tag first
            assert any(str(row.get("tag_id")) == str(tag_id)
                       for row in _rows(tag_lake, table)), table
        original = label.removesuffix("x")
        assert _files_holding(tag_lake, original)     # the changelog's before

        code, printed, errors = _erase(tag_lake, "Tag", str(tag_id))

        assert code == 0, printed + errors
        for table in TAG_TABLES:
            assert all(str(row.get("tag_id")) != str(tag_id)
                       for row in _rows(tag_lake, table)), table
        assert _files_holding(tag_lake, label) == []
        assert _files_holding(tag_lake, original) == []
        with _source(tag_lake) as source:
            other = source.execute("SELECT label FROM tags WHERE tag_id != ? LIMIT 1",
                                   (tag_id,)).fetchone()[0]
        assert _files_holding(tag_lake, other)                    # THE CONTROL

    def test_erasing_a_customer_reaches_the_removed_types_tables(self, tag_lake):  # noqa: F811
        """The join table of the removed link holds customer ids: erasing a
        customer afterwards must take their rows, which it skipped."""
        _remove_tag_and_sync_again(tag_lake)
        with _source(tag_lake) as source:
            customer = source.execute("SELECT customer_id FROM customer_tags LIMIT 1").fetchone()[0]
        assert any(row["customer_id"] == customer
                   for row in _rows(tag_lake, "primary_sql.customer_tags"))

        code, printed, errors = _erase(tag_lake, "Customer", customer)

        assert code == 0, printed + errors
        for table in ("bronze_primary_sql.customer_tags", "primary_sql.customer_tags",
                      "gold.customer_tags"):
            assert all(row["customer_id"] != customer for row in _rows(tag_lake, table)), table
        assert _files_holding(tag_lake, customer) == []

    def test_a_sync_after_the_removal_does_not_forget_what_was_recorded(self, tag_lake):  # noqa: F811
        _remove_tag_and_sync_again(tag_lake)
        catalog = open_mirror_catalog(tag_lake.data_dir / "mirror")

        recorded = recorded_key_columns(catalog.load_table("gold.Tag"))
        assert recorded == {"tag_id": {"Tag"}}
        assert recorded_key_columns(catalog.load_table("primary_sql.customer_tags")) == {
            "customer_id": {"Customer"}, "tag_id": {"Tag"}}


class TestATableWrittenBeforeTheRecordExisted:
    def test_it_is_reported_unreachable_and_logged_not_skipped(self, tag_lake, caplog):  # noqa: F811
        _remove_tag_and_sync_again(tag_lake)
        legacy = ["bronze_primary_sql.tags", "primary_sql.tags", "gold.Tag", "gold_history.Tag",
                  "changelog_primary_sql.tags"]
        _forget_what_tables_recorded(tag_lake, legacy)
        config = load_deployment(tag_lake.config_dir)
        catalog = open_mirror_catalog(tag_lake.data_dir / "mirror")
        register = ErasureRegister(tag_lake.data_dir / "erasures.db")
        register.record([("Customer", "no-such-customer")], "tester", "test")

        with caplog.at_level(logging.WARNING, logger="core.mirror.erasure"):
            result = apply_erasures(catalog, config.schema, register,
                                    tag_lake.data_dir / "mirror")

        assert sorted(result.unreachable_tables) == sorted(legacy)
        assert "could not search" in caplog.text and "gold.Tag" in caplog.text

    def test_the_command_says_so_and_does_not_report_success(self, tag_lake):  # noqa: F811
        _remove_tag_and_sync_again(tag_lake)
        _forget_what_tables_recorded(tag_lake, ["gold.Tag"])
        with _source(tag_lake) as source:
            customer = source.execute("SELECT customer_id FROM customer_tags LIMIT 1").fetchone()[0]

        code, _printed, errors = _erase(tag_lake, "Customer", customer)

        assert code == 2
        assert "NOT COMPLETE" in errors and "gold.Tag" in errors
        # What it COULD reach, it still erased.
        assert all(row["customer_id"] != customer
                   for row in _rows(tag_lake, "primary_sql.customer_tags"))

    def test_the_removed_type_cannot_even_be_named_when_no_table_recorded_it(self, tag_lake):  # noqa: F811
        _remove_tag_and_sync_again(tag_lake)
        catalog = open_mirror_catalog(tag_lake.data_dir / "mirror")
        _forget_what_tables_recorded(tag_lake, [
            ".".join(parts) for namespace in catalog.list_namespaces()
            for parts in catalog.list_tables(namespace)])

        code, _printed, errors = _erase(tag_lake, "Tag", "1")

        assert code == 1 and "No object type" in errors

    def test_the_next_sync_records_it_for_a_type_that_still_exists(self, tag_lake):  # noqa: F811
        _sync(tag_lake)
        _forget_what_tables_recorded(tag_lake, ["gold.Customer", "primary_sql.customers"])
        catalog = open_mirror_catalog(tag_lake.data_dir / "mirror")
        assert recorded_key_columns(catalog.load_table("gold.Customer")) == {}

        _sync(tag_lake)

        for identifier in ("gold.Customer", "primary_sql.customers"):
            assert recorded_key_columns(catalog.load_table(identifier)) == {
                "customer_id": {"Customer"}}, identifier
