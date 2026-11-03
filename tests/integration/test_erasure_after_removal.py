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
import yaml

from core.deployment_loader import load_deployment
from core.mirror.catalog import open_mirror_catalog
from core.mirror.erasure import (
    KEY_COLUMNS_PROPERTY,
    ErasureRegister,
    apply_erasures,
    recorded_columns,
    recorded_key_columns,
    survey,
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


def _erase(paths, object_type, object_id, reachable_now=True):
    """`reachable_now`: pass --erase-reachable-now. The tests about what an
    erasure CAN do in a damaged lake need it; the ones about refusing do not."""
    printed, errors = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(errors):
        code = erase(object_type, object_id, "test request", write=True, paths=paths,
                     requested_by="tester", erase_reachable_now=reachable_now)
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
        # A column the ontology no longer maps is a removed type's, not a re-pointed one.
        assert survey(catalog, load_deployment(tag_lake.config_dir).schema, {"Customer", "Tag"}).stale == []


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
        assert "could not be searched" in caplog.text and "gold.Tag" in caplog.text

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

        assert code == 1
        assert "not an object type of the ontology" in errors
        # HONEST, not "no such type": the tables erasure cannot search are named, with the remedy.
        assert "gold.Tag" in errors and "gold_history.Tag" in errors
        assert "Restore the type and sync" in errors and "--adopt" in errors and "drop it in the lake" in errors
        assert "primary_sql.customers" not in errors              # known to the ontology

    def test_the_next_sync_records_it_and_calls_it_complete_because_every_column_is_mapped(
            self, tag_lake):  # noqa: F811
        _sync(tag_lake)
        _forget_what_tables_recorded(tag_lake, ["gold.Customer", "primary_sql.customers"])
        catalog = open_mirror_catalog(tag_lake.data_dir / "mirror")
        assert recorded_key_columns(catalog.load_table("gold.Customer")) == {}

        _sync(tag_lake)

        for identifier in ("gold.Customer", "primary_sql.customers"):
            assert recorded_key_columns(catalog.load_table(identifier)) == {
                "customer_id": {"Customer"}}, identifier
        # Whatever its age: every column it has is one the ontology maps, so nothing can hide there.
        schema = load_deployment(tag_lake.config_dir).schema
        assert not {"gold.Customer", "primary_sql.customers"} & set(survey(catalog, schema).partly_known)


class TestWhatTheRegisterAndTheSyncSay:
    def _incomplete_erasure(self, paths):
        _remove_tag_and_sync_again(paths)
        _forget_what_tables_recorded(paths, ["gold.Tag", "primary_sql.tags"])
        with _source(paths) as source:
            customer = source.execute("SELECT customer_id FROM customer_tags LIMIT 1").fetchone()[0]
        return customer, _erase(paths, "Customer", customer)

    def test_a_dry_run_names_what_the_write_could_not_search(self, tag_lake):  # noqa: F811
        _remove_tag_and_sync_again(tag_lake)
        _forget_what_tables_recorded(tag_lake, ["gold.Tag"])
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(io.StringIO()):
            code = erase("Customer", "cust_001", "test", write=False, paths=tag_lake)

        assert code == 0
        assert "WARNING" in printed.getvalue() and "gold.Tag" in printed.getvalue()
        assert "Dry run" in printed.getvalue()

    def test_the_register_says_incomplete_and_the_list_shows_it(self, tag_lake):  # noqa: F811
        _customer, (code, _out, _err) = self._incomplete_erasure(tag_lake)
        register = ErasureRegister(tag_lake.data_dir / "erasures.db")

        assert code == 2
        assert register.incomplete() == ["gold.Tag", "primary_sql.tags"]
        assert not register.unpurged()                    # applied to what could be searched
        from scripts.erase import list_erasures
        listed = io.StringIO()
        with contextlib.redirect_stdout(listed):
            list_erasures(tag_lake)
        assert "INCOMPLETE: gold.Tag, primary_sql.tags" in listed.getvalue()

    def test_every_later_sync_says_so_and_it_clears_when_they_can_be_searched(self, tag_lake):  # noqa: F811
        from scripts.run_sync import run_sync

        self._incomplete_erasure(tag_lake)
        errors = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
            run_sync(tag_lake)
        assert "gold.Tag" in errors.getvalue() and "WARNING erasure" in errors.getvalue()

        catalog = open_mirror_catalog(tag_lake.data_dir / "mirror")
        for name in ("gold.Tag", "primary_sql.tags"):
            catalog.drop_table(name)                      # the remedy the message names
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            run_sync(tag_lake)
        assert ErasureRegister(tag_lake.data_dir / "erasures.db").incomplete() == []


def _remove_tag_through_the_ui(paths, strip=False, notices=None, before_removal=None):
    """Sync, optionally make every table as an older sync left it, then remove
    Tag as a person would -- and NO sync afterwards."""
    from api.app import create_app
    from tests.integration.test_removal_from_the_ui import TAG, TAGS_LINK, TestClient, _deprecate, _login
    from tests.integration.test_removal_from_the_ui import _remove as remove

    _sync(paths)
    if strip:
        catalog = open_mirror_catalog(paths.data_dir / "mirror")
        _forget_what_tables_recorded(paths, [".".join(parts) for namespace in catalog.list_namespaces()
                                             for parts in catalog.list_tables(namespace)])
    client = TestClient(create_app(paths))
    client.app.state.user_directory.create_user("ops", "correct-pw", "us-west", "remover")
    _login(client, "ops", "correct-pw")
    if before_removal is not None:
        before_removal(client)
    for what in (TAGS_LINK, TAG):
        _deprecate(client, what)
        response = remove(client, what)
        assert response.status_code == 200, response.text
        if notices is not None:
            notices.append(response.json().get("notice"))
    return client


class TestRemovingATypeRecordsItsTablesFirst:
    def test_a_removal_through_the_ui_leaves_no_hole_in_old_tables(self, tag_lake):  # noqa: F811
        """Every table is as a sync before the record left it; Tag goes through
        the UI; no sync follows. Erasure still reaches Tag's tables."""
        _remove_tag_through_the_ui(tag_lake, strip=True)
        tag_id, _label = _a_tag(tag_lake)

        code, printed, errors = _erase(tag_lake, "Tag", str(tag_id))

        for table in ("bronze_primary_sql.tags", "primary_sql.tags", "gold.Tag"):
            assert all(str(row.get("tag_id")) != str(tag_id) for row in _rows(tag_lake, table)), table
        # Every column of every Tag table was mapped when the removal recorded them, so nothing of
        # Tag is partly known: the erasure is complete however old the tables were.
        assert code == 0, printed + errors
        assert "no key columns known" not in errors and "NOT COMPLETE" not in errors

    def test_a_removal_with_an_unreadable_lake_goes_ahead_and_says_what_it_could_not_record(
            self, tag_lake, monkeypatch):  # noqa: F811
        import api.routes

        def unreadable(request):
            raise OSError("the lake is not there")
        monkeypatch.setattr(api.routes, "_mirror_catalog_for", unreadable)
        notices: list = []

        client = _remove_tag_through_the_ui(tag_lake, notices=notices)

        assert "Tag" not in client.app.state.generation.config.schema
        assert all(notice and "could not be read" in notice and "--adopt" in notice for notice in notices)
        assert "the lake is not there" not in " ".join(notices)

    def test_a_removal_while_a_sync_runs_does_not_touch_the_lake_and_says_so(
            self, tag_lake, monkeypatch):  # noqa: F811
        import contextlib as _contextlib

        import api.routes
        import core.mirror.sync_lock

        recorded: list = []
        monkeypatch.setattr("core.mirror.erasure.record_key_columns",
                            lambda *args, **kwargs: recorded.append(args))

        @_contextlib.contextmanager
        def busy(lock_path):
            yield False
        notices: list = []

        _remove_tag_through_the_ui(
            tag_lake, notices=notices,
            before_removal=lambda client: monkeypatch.setattr(core.mirror.sync_lock, "single_writer", busy))

        assert api.routes and recorded == []
        assert all(notice and "A sync was running" in notice and "--adopt-all-current" in notice
                   for notice in notices)

    def test_approving_a_waiting_change_records_the_tables_first_too(self, tag_lake, monkeypatch):  # noqa: F811
        """Every path that can drop a type takes the record first, not only the removal."""
        import api.routes

        calls: list = []
        real = api.routes._record_erasure_keys_before
        monkeypatch.setattr(api.routes, "_record_erasure_keys_before",
                            lambda request: calls.append("recorded") or real(request))
        policy = yaml.safe_load((tag_lake.config_dir / "policy.yaml").read_text())
        policy["roles"]["approver"] = {"allowed_actions": ["manage:roles"]}
        (tag_lake.config_dir / "policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False))
        client = _remove_tag_through_the_ui(tag_lake)
        calls.clear()
        ontology = (tag_lake.config_dir / "ontology_schema.yaml").read_text()
        from core.config_editing import digest
        from core.config_proposals import ConfigProposalStore
        from tests.integration.test_removal_from_the_ui import _csrf_headers, _login
        proposal_id = ConfigProposalStore(
            tag_lake.data_dir / "config_proposals.db").propose(
            "shape", "a note", {"ontology_schema.yaml": ontology + "\n# a note\n"},
            {"ontology_schema.yaml": digest(ontology)}, "test", "ops")
        client.cookies.clear()
        client.app.state.user_directory.create_user("boss", "correct-pw", "us-west", "approver")
        _login(client, "boss", "correct-pw")

        response = client.post(f"/api/admin/config-proposals/{proposal_id}/approve",
                               headers=_csrf_headers(client))

        assert response.status_code == 200, response.text
        assert calls == ["recorded"]

    def test_a_removal_that_could_record_carries_no_notice(self, tag_lake):  # noqa: F811
        notices: list = []
        _remove_tag_through_the_ui(tag_lake, notices=notices)

        assert notices == [None, None]


class TestAdoptingALegacyTable:
    def test_keys_and_ids_for_one_column_are_both_kept_and_a_link_alone_makes_a_key(self, tag_lake):  # noqa: F811
        from scripts.erase import adopt

        _remove_tag_and_sync_again(tag_lake)
        catalog = open_mirror_catalog(tag_lake.data_dir / "mirror")
        with contextlib.redirect_stdout(io.StringIO()):
            assert adopt("gold.Tag", "tag_id=Customer", "tag_id=Tag", None, False, paths=tag_lake) == 0
            assert recorded_key_columns(catalog.load_table("gold.Tag"))["tag_id"] == {"Customer", "Tag"}
            assert adopt("gold_history.Tag", None, None, "tag_id=Tag:Customer", False, paths=tag_lake) == 0
        assert "Customer" in recorded_key_columns(catalog.load_table("gold_history.Tag"))["tag_id"]

    def test_the_operators_statement_makes_the_tables_searchable_and_complete(self, tag_lake):  # noqa: F811
        from scripts.erase import adopt

        _remove_tag_and_sync_again(tag_lake)
        legacy = ["bronze_primary_sql.tags", "primary_sql.tags", "gold.Tag", "gold_history.Tag",
                  "changelog_primary_sql.tags"]
        _forget_what_tables_recorded(tag_lake, legacy)
        tag_id, _label = _a_tag(tag_lake)
        refused, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(refused), contextlib.redirect_stderr(errors):
            assert adopt("gold.NoSuch", "tag_id=Tag", None, None, False, paths=tag_lake) == 1
            assert adopt("gold.Tag", "nope=Tag", None, None, False, paths=tag_lake) == 1
            assert adopt("gold.Tag", None, None, None, False, paths=tag_lake) == 1
        assert "No table 'gold.NoSuch'" in errors.getvalue() and "no column 'nope'" in errors.getvalue()

        with contextlib.redirect_stdout(io.StringIO()):
            for identifier in legacy:
                column = "tag_id"
                assert adopt(identifier, f"{column}=Tag", f"{column}=Tag", None, False, paths=tag_lake) == 0
        code, printed, errors = _erase(tag_lake, "Tag", str(tag_id))

        assert code == 0, printed + errors
        for table in legacy:
            assert all(str(row.get("tag_id")) != str(tag_id) for row in _rows(tag_lake, table)), table


class TestWriteRefusesWhileATableCannotBeFullySearched:
    def _damaged(self, paths):
        _remove_tag_and_sync_again(paths)
        _forget_what_tables_recorded(paths, ["gold.Tag"])
        with _source(paths) as source:
            return source.execute("SELECT customer_id FROM customer_tags LIMIT 1").fetchone()[0]

    def test_it_erases_nothing_and_says_to_resolve_them_first(self, tag_lake):  # noqa: F811
        customer = self._damaged(tag_lake)

        code, _printed, errors = _erase(tag_lake, "Customer", customer, reachable_now=False)

        assert code == 3 and "NOT ERASED" in errors and "gold.Tag" in errors     # 3: refused, nothing erased
        assert "--adopt-all-current" in errors and "--erase-reachable-now" in errors
        assert "--adopt-none" in errors
        assert any(row["customer_id"] == customer for row in _rows(tag_lake, "primary_sql.customer_tags"))
        assert ErasureRegister(tag_lake.data_dir / "erasures.db").erasures() == []

    def test_the_override_erases_what_can_be_reached_and_records_it_incomplete(self, tag_lake):  # noqa: F811
        customer = self._damaged(tag_lake)

        code, _printed, errors = _erase(tag_lake, "Customer", customer, reachable_now=True)

        assert code == 2 and "NOT COMPLETE" in errors
        assert all(row["customer_id"] != customer for row in _rows(tag_lake, "primary_sql.customer_tags"))
        assert ErasureRegister(tag_lake.data_dir / "erasures.db").incomplete() == ["gold.Tag"]

    def test_the_dry_run_says_what_write_would_do(self, tag_lake):  # noqa: F811
        customer = self._damaged(tag_lake)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(io.StringIO()):
            code = erase("Customer", customer, "test", write=False, paths=tag_lake)

        assert code == 0 and "--write would REFUSE and erase nothing" in printed.getvalue()

    def test_a_healthy_lake_is_not_refused(self, tag_lake):  # noqa: F811
        _remove_tag_and_sync_again(tag_lake)
        with _source(tag_lake) as source:
            customer = source.execute("SELECT customer_id FROM customer_tags LIMIT 1").fetchone()[0]

        code, printed, errors = _erase(tag_lake, "Customer", customer, reachable_now=False)

        assert code == 0, printed + errors


class TestAdoptingEverythingTheOntologyMaps:
    def test_it_needs_the_confirmation_and_never_adopts_a_table_the_ontology_does_not_know(
            self, tag_lake):  # noqa: F811
        from scripts.erase import adopt_everything_current

        _remove_tag_and_sync_again(tag_lake)
        catalog = open_mirror_catalog(tag_lake.data_dir / "mirror")
        everything = [".".join(parts) for namespace in catalog.list_namespaces()
                      for parts in catalog.list_tables(namespace)]
        _forget_what_tables_recorded(tag_lake, everything)
        said, errors = io.StringIO(), io.StringIO()

        with contextlib.redirect_stdout(said), contextlib.redirect_stderr(errors):
            assert adopt_everything_current(False, paths=tag_lake) == 1
            assert not recorded_columns(catalog.load_table("primary_sql.customers")).present
            assert adopt_everything_current(True, paths=tag_lake) == 0

        mapped = recorded_columns(catalog.load_table("primary_sql.customers"))
        assert mapped.complete and mapped.adopted and "no object type was ever removed" in mapped.statement
        for unknown in ("gold.Tag", "primary_sql.tags", "gold.customer_tags"):
            assert not recorded_columns(catalog.load_table(unknown)).present, unknown
        assert "STILL UNRESOLVED" in said.getvalue() and "gold.Tag" in said.getvalue()
        # and so the lake is still not erasable in one go: it says why
        customer = "cust_001"
        code, _printed, refused = _erase(tag_lake, "Customer", customer, reachable_now=False)
        assert code == 3 and "gold.Tag" in refused


class TestVouchingForUnmappedColumnsNeedsATypedPhrase:
    """--including-unmapped-columns vouches that columns the ontology does not
    map hold no person's id, which nothing can check. So it prints each table
    and column it is about to vouch for and wants the phrase, typed or given
    with --typed-confirmation (no terminal)."""

    PHRASE = "I VOUCH FOR THESE COLUMNS"

    def _forgotten(self, tag_lake):  # noqa: F811
        _remove_tag_and_sync_again(tag_lake)
        catalog = open_mirror_catalog(tag_lake.data_dir / "mirror")
        everything = [".".join(parts) for namespace in catalog.list_namespaces()
                      for parts in catalog.list_tables(namespace)]
        _forget_what_tables_recorded(tag_lake, everything)
        from pyiceberg.types import StringType

        with catalog.load_table("primary_sql.customers").update_schema() as columns:
            columns.add_column("legacy_memo", StringType())     # a column no ontology field maps
        return catalog

    def _command(self, tag_lake, monkeypatch, *flags, typed=None, terminal=False):  # noqa: F811
        """The real main(): argument parsing, the prompt, the adoption."""
        import sys

        import scripts.erase as erase_script

        monkeypatch.setattr(erase_script, "resolve_runtime_paths", lambda: tag_lake)
        monkeypatch.setattr(sys, "argv", ["erase", "--adopt-all-current",
                                          "--confirm-no-type-was-ever-removed", *flags])
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        if terminal:
            monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
            monkeypatch.setattr("builtins.input", lambda _prompt="": typed)
        printed, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(errors):
            code = erase_script.main()
        return code, printed.getvalue(), errors.getvalue()

    def _unmapped_table(self, catalog):
        from core.mirror.erasure import preview_adopt_all_current

        config = load_deployment(self._paths.config_dir)
        plan, _ = preview_adopt_all_current(catalog, config.schema, True)
        with_columns = {table: columns for table, columns in plan.items() if columns}
        assert with_columns, "the fixture lake has no table with unmapped columns"
        return sorted(with_columns)[0], with_columns

    def test_the_flag_phrase_adopts_and_the_listing_names_every_table_and_column(
            self, tag_lake, monkeypatch):  # noqa: F811
        self._paths = tag_lake
        catalog = self._forgotten(tag_lake)
        table, with_columns = self._unmapped_table(catalog)

        code, printed, errors = self._command(tag_lake, monkeypatch, "--including-unmapped-columns",
                                              "--typed-confirmation", self.PHRASE)

        assert code == 0, printed + errors
        assert recorded_columns(catalog.load_table(table)).adopted
        assert f"{table}: {', '.join(with_columns[table])}" in printed

    def test_nothing_is_adopted_without_the_exact_phrase(self, tag_lake, monkeypatch):  # noqa: F811
        self._paths = tag_lake
        catalog = self._forgotten(tag_lake)
        table, _ = self._unmapped_table(catalog)

        for flags, kwargs in (
                (("--including-unmapped-columns",), {}),                                    # no terminal, no flag
                (("--including-unmapped-columns", "--typed-confirmation", ""), {}),         # empty
                (("--including-unmapped-columns", "--typed-confirmation", "i vouch for these columns"), {}),
                (("--including-unmapped-columns",), {"terminal": True, "typed": "yes"}),    # typed, wrong
                (("--including-unmapped-columns",), {"terminal": True, "typed": ""}),
                (("--typed-confirmation", self.PHRASE), {}),                                # flag without its form
        ):
            code, _printed, _errors = self._command(tag_lake, monkeypatch, *flags, **kwargs)
            assert code == 1, (flags, kwargs)
            assert not recorded_columns(catalog.load_table(table)).present, (flags, kwargs)
            assert not recorded_columns(catalog.load_table("primary_sql.customers")).present

    def test_the_phrase_typed_at_a_terminal_adopts(self, tag_lake, monkeypatch):  # noqa: F811
        self._paths = tag_lake
        catalog = self._forgotten(tag_lake)
        table, _ = self._unmapped_table(catalog)

        code, printed, errors = self._command(tag_lake, monkeypatch, "--including-unmapped-columns",
                                              terminal=True, typed=self.PHRASE)

        assert code == 0, printed + errors
        assert recorded_columns(catalog.load_table(table)).adopted

    def test_the_form_without_unmapped_columns_asks_for_no_phrase(self, tag_lake, monkeypatch):  # noqa: F811
        self._paths = tag_lake
        catalog = self._forgotten(tag_lake)

        code, printed, errors = self._command(tag_lake, monkeypatch)

        assert code == 0, printed + errors
        assert recorded_columns(catalog.load_table("gold.Customer")).adopted
        assert not recorded_columns(catalog.load_table("primary_sql.customers")).present   # its legacy_memo
