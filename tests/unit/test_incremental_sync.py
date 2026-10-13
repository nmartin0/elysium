"""
Reading only what changed since the last sync (R2).

What the owner chose on 13 October, and what these tests hold it to:
a table that names a cursor column is read `WHERE cursor >= mark` and
the rows are merged into bronze by id, AND it is still read in full on
a schedule, because a cursor cannot see a deleted row.

The promise that matters most is the boring one: after any mix of
changed-rows and full reads, the mirror holds what a full read would
have given it -- except deletions, which wait for the next full read,
and the tests say so rather than leave it to be discovered.
"""

import contextlib
import io
import logging
import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

import core.mirror.iceberg_sync as iceberg_sync
from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.incremental import (
    CURSOR_PROPERTY,
    FULL_READ_PROPERTY,
    MARK_PROPERTY,
    IncrementalPolicy,
    decode_mark,
    encode_mark,
    full_read_reason,
    incremental_policies,
    parse_duration,
    read_from,
)

COLUMNS = ["id", "name", "updated_at"]
POLICY = IncrementalPolicy(cursor="updated_at")


def _db(path, rows):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, name TEXT, updated_at TEXT)")
    connection.executemany("INSERT INTO t VALUES (?, ?, ?)", rows)
    connection.commit()
    connection.close()


def _run(path, *statements):
    connection = sqlite3.connect(path)
    for statement in statements:
        connection.execute(statement)
    connection.commit()
    connection.close()


class Recording(SQLiteReadAdapter):
    """Says which way the sync read, and with what mark."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reads = []

    def iter_all_rows(self, *args, **kwargs):
        self.reads.append(("all", None))
        yield from super().iter_all_rows(*args, **kwargs)

    def iter_rows_since(self, table_name, columns, cursor_column, since, **kwargs):
        self.reads.append(("since", since))
        yield from super().iter_rows_since(table_name, columns, cursor_column, since, **kwargs)


@pytest.fixture
def mirror(tmp_path):
    source = tmp_path / "s.db"
    _db(source, [("1", "Ann", "2026-10-01T09:00"), ("2", "Bo", "2026-10-02T09:00"),
                 ("3", "Cy", "2026-10-03T09:00")])
    adapter = Recording({"path": source})
    sync = IcebergMirrorSync(tmp_path / "m", {"s": adapter})
    sync.incremental = {("s", "t"): POLICY}
    sync.source, sync.adapter = source, adapter
    return sync


def _sync(sync):
    return sync.sync_table("s", "t", "id", COLUMNS, {"id": "string", "name": "string"})


def _silver(sync):
    rows = sync._catalog.load_table("s.t").scan().to_arrow().to_pylist()
    return {row["id"]: row["name"] for row in rows}


def _changes(sync):
    try:
        table = sync._catalog.load_table("changelog_s.t")
    except Exception:  # noqa: BLE001 - no changelog yet is an answer
        return []
    return sorted((row["id"], row["_change"]) for row in table.scan().to_arrow().to_pylist())


def _bronze_properties(sync):
    return sync._catalog.load_table("bronze_s.t").properties


class TestTheFirstSyncIsFull:
    def test_it_reads_everything_and_records_the_mark(self, mirror):
        result = _sync(mirror)

        assert mirror.adapter.reads == [("all", None)]
        assert result.read == "full (first sync)"
        properties = _bronze_properties(mirror)
        assert properties[CURSOR_PROPERTY] == "updated_at"
        assert decode_mark(properties[MARK_PROPERTY]) == "2026-10-03T09:00"
        assert FULL_READ_PROPERTY in properties


class TestTheNextSyncReadsOnlyWhatChanged:
    def test_a_change_and_an_insert_arrive_and_nothing_else_is_read(self, mirror):
        _sync(mirror)
        _run(mirror.source,
             "UPDATE t SET name = 'Ann B', updated_at = '2026-10-04T09:00' WHERE id = '1'",
             "INSERT INTO t VALUES ('4', 'Di', '2026-10-05T09:00')")

        result = _sync(mirror)

        assert mirror.adapter.reads[-1] == ("since", "2026-10-03T09:00")
        # THREE: the two that moved, and row 3 again -- it holds the mark,
        # and the boundary is inclusive.
        assert result.read == ("3 row(s) at or after updated_at 2026-10-03T09:00 "
                               "(full read every 7 days)")
        assert _silver(mirror) == {"1": "Ann B", "2": "Bo", "3": "Cy", "4": "Di"}
        assert ("1", "UPDATE") in _changes(mirror) and ("4", "INSERT") in _changes(mirror)
        assert decode_mark(_bronze_properties(mirror)[MARK_PROPERTY]) == "2026-10-05T09:00"

    def test_the_boundary_is_inclusive(self, mirror):
        """A row written after the last read WITH THE SAME cursor value
        as the mark is read, not skipped -- `>=`, not `>`."""
        _sync(mirror)
        _run(mirror.source, "INSERT INTO t VALUES ('5', 'Ed', '2026-10-03T09:00')")

        _sync(mirror)

        assert _silver(mirror)["5"] == "Ed"

    def test_nothing_changed_writes_nothing(self, mirror):
        _sync(mirror)
        snapshots = len(list(mirror._catalog.load_table("s.t").snapshots()))

        result = _sync(mirror)

        assert result.unchanged
        assert len(list(mirror._catalog.load_table("s.t").snapshots())) == snapshots


class TestADeletionWaitsForTheFullRead:
    def test_it_is_not_seen_by_a_changed_rows_read(self, mirror):
        _sync(mirror)
        _run(mirror.source, "DELETE FROM t WHERE id = '2'")

        _sync(mirror)

        assert "2" in _silver(mirror), "a cursor read cannot see a deletion; this one claims to"

    def test_the_scheduled_full_read_sees_it(self, mirror, monkeypatch):
        _sync(mirror)
        _run(mirror.source, "DELETE FROM t WHERE id = '2'")
        later = datetime.now(UTC) + timedelta(days=8)
        monkeypatch.setattr(iceberg_sync, "now_utc", lambda: later)

        result = _sync(mirror)

        assert result.read.startswith("full (scheduled")
        assert "2" not in _silver(mirror)
        assert ("2", "DELETE") in _changes(mirror)

    def test_asking_for_a_full_read_sees_it(self, mirror):
        _sync(mirror)
        _run(mirror.source, "DELETE FROM t WHERE id = '2'")
        mirror.force_full_read = True

        result = _sync(mirror)

        assert result.read == "full (a full read was asked for)"
        assert "2" not in _silver(mirror)


class TestWhenAChangedRowsReadWouldBeWrong:
    def test_a_new_cursor_column_reads_in_full(self, mirror):
        _sync(mirror)
        mirror.incremental = {("s", "t"): IncrementalPolicy(cursor="name")}

        result = _sync(mirror)

        assert result.read == "full (the cursor column changed)"

    def test_a_cursor_the_source_lacks_reads_in_full(self, mirror):
        mirror.incremental = {("s", "t"): IncrementalPolicy(cursor="modified")}

        result = _sync(mirror)

        assert result.read == "full (the source has no column 'modified')"

    def test_an_adapter_that_cannot_reads_in_full_and_says_why(self, mirror, monkeypatch):
        from core.ontology.interface import ExternalReadAdapter

        _sync(mirror)
        monkeypatch.setattr(Recording, "iter_rows_since", ExternalReadAdapter.iter_rows_since)
        _run(mirror.source, "UPDATE t SET name = 'Ann B', updated_at = '2026-10-04' WHERE id = '1'")

        result = _sync(mirror)

        assert result.read == "full (Recording cannot read changed rows only)"
        assert _silver(mirror)["1"] == "Ann B"

    def test_rows_with_no_cursor_are_reported(self, tmp_path, caplog):
        source = tmp_path / "n.db"
        _db(source, [("1", "Ann", None), ("2", "Bo", "2026-10-02")])
        sync = IcebergMirrorSync(tmp_path / "nm", {"s": SQLiteReadAdapter({"path": source})})
        sync.incremental = {("s", "t"): POLICY}

        with caplog.at_level(logging.WARNING):
            _sync(sync)

        assert "1 row(s) have no updated_at" in caplog.text


class TestWhatIsCarriedForward:
    def test_a_locale_still_applies_to_rows_that_were_not_re_read(self, tmp_path):
        """DEP-1 reads only the columns the source sent as TEXT, decided
        from the rows read. A changed-rows read sees a few rows; the
        answer for the rest is carried on bronze."""
        source = tmp_path / "l.db"
        connection = sqlite3.connect(source)
        connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, amount TEXT, updated_at TEXT)")
        connection.executemany("INSERT INTO t VALUES (?, ?, ?)",
                               [("1", "1.234,5", "a"), ("2", "2,5", "b")])
        connection.commit()
        connection.close()
        sync = IcebergMirrorSync(tmp_path / "lm", {"s": SQLiteReadAdapter({"path": source})},
                                  on_type_mismatch="quarantine")
        sync.incremental = {("s", "t"): POLICY}
        sync.locales = {"s": "pt_BR"}
        columns, types = ["id", "amount", "updated_at"], {"id": "string", "amount": "number"}
        sync.sync_table("s", "t", "id", columns, types)
        # THE ONLY ROW RE-READ HAS NO AMOUNT, so nothing in this read
        # says `amount` arrives as text -- only what bronze carried does.
        _run(source, "UPDATE t SET amount = NULL, updated_at = 'c' WHERE id = '2'")

        sync.sync_table("s", "t", "id", columns, types)

        rows = {row["id"]: row["amount"]
                for row in sync._catalog.load_table("s.t").scan().to_arrow().to_pylist()}
        assert rows == {"1": 1234.5, "2": None}


class TestTheDeclaration:
    def test_a_full_declaration_reads(self):
        policies = incremental_policies(
            {"p": {"incremental": {"t": {"cursor": "updated_at", "full_read_every": "2d",
                                         "lookback": "5m"}}}}, {("p", "t")})

        assert policies == {("p", "t"): IncrementalPolicy(
            "updated_at", timedelta(days=2), timedelta(minutes=5))}

    def test_the_defaults(self):
        policy = incremental_policies({"p": {"incremental": {"t": {"cursor": "v"}}}})[("p", "t")]
        assert policy.full_read_every == timedelta(days=7) and policy.lookback == timedelta(0)

    @pytest.mark.parametrize("entry, says", [
        ({}, "cursor must name"),
        ({"cursor": ""}, "cursor must name"),
        ({"cursor": "v", "every": "1d"}, "unknown key"),
        ({"cursor": "v", "full_read_every": 7}, "must be a duration"),
        ({"cursor": "v", "full_read_every": "0d"}, "longer than zero"),
        ({"cursor": "v", "lookback": "5 minutes"}, "must be a duration"),
    ])
    def test_a_bad_entry_is_refused(self, entry, says):
        with pytest.raises(ValueError, match=says):
            incremental_policies({"p": {"incremental": {"t": entry}}})

    def test_a_table_the_sync_does_not_read_is_refused_naming_those_it_does(self):
        with pytest.raises(ValueError, match=r"reads no table 'tranactions'.*\['customers'\]"):
            incremental_policies({"p": {"incremental": {"tranactions": {"cursor": "v"}}}},
                                 {("p", "customers")})

    def test_a_join_table_cannot_be_declared(self):
        from core.deployment_loader import _incremental_policies

        # THE EXPANDED FORM the loader validates: a many-to-many field
        # carries via_table, via_column and via_target_column.
        object_types = {
            "Customer": {"storage": {"silo": "p", "table": "customers", "id_column": "id"},
                         "fields": {"id": {"column": "id"},
                                    "tags": {"type": "link", "target": "Tag",
                                             "via_table": "customer_tags",
                                             "via_column": "customer_id",
                                             "via_target_column": "tag_id"}}},
            "Tag": {"storage": {"silo": "p", "table": "tags", "id_column": "id"},
                    "fields": {"id": {"column": "id"}}},
        }
        from core.mirror.sync_targets import resolve_sync_targets

        assert ("p", "customer_tags") in {
            (t.silo_name, t.table_name) for t in resolve_sync_targets({"object_types": object_types})
        }, "the fixture must really declare a join table, or this proves nothing"
        silos = {"p": {"incremental": {"customer_tags": {"cursor": "v"}}}}

        with pytest.raises(ValueError, match="reads no table 'customer_tags'"):
            _incremental_policies(silos, object_types)

    @pytest.mark.parametrize("text, said", [
        ("7d", "7 days"), ("1d", "1 day"), ("36h", "36 hours"), ("5m", "5 minutes"),
        ("90s", "90 seconds")])
    def test_a_duration_is_said_in_its_own_unit(self, text, said):
        from core.mirror.incremental import describe_span

        assert describe_span(parse_duration(text, "x")) == said

    @pytest.mark.parametrize("text, expected", [
        ("30s", timedelta(seconds=30)), ("5m", timedelta(minutes=5)),
        ("12h", timedelta(hours=12)), (" 7d ", timedelta(days=7))])
    def test_durations(self, text, expected):
        assert parse_duration(text, "x") == expected


class TestTheMarkKeepsItsType:
    @pytest.mark.parametrize("value", [
        datetime(2026, 10, 13, 9, 30, tzinfo=UTC), datetime(2026, 10, 13, 9, 30),
        date(2026, 10, 13), 42, Decimal("10.50"), 1.5, "2026-10-13T09:30"])
    def test_it_round_trips(self, value):
        decoded = decode_mark(encode_mark(value))
        assert decoded == value and type(decoded) is type(value)

    def test_a_boolean_is_not_a_cursor(self):
        assert encode_mark(True) is None

    def test_lookback_moves_a_timestamp_mark_only(self):
        mark = datetime(2026, 10, 13, 9, 30)
        assert read_from(mark, timedelta(minutes=5)) == datetime(2026, 10, 13, 9, 25)
        assert read_from(42, timedelta(minutes=5)) == 42


class TestWhyAFullRead:
    NOW = datetime(2026, 10, 13, tzinfo=UTC)

    def _properties(self, **overrides):
        return {CURSOR_PROPERTY: "updated_at", MARK_PROPERTY: encode_mark("x"),
                FULL_READ_PROPERTY: (self.NOW - timedelta(days=1)).isoformat(), **overrides}

    def test_a_recent_full_read_allows_a_changed_rows_read(self):
        assert full_read_reason(POLICY, self._properties(), self.NOW, COLUMNS) is None

    def test_a_week_old_full_read_is_due(self):
        old = (self.NOW - timedelta(days=7)).isoformat()
        assert full_read_reason(POLICY, self._properties(**{FULL_READ_PROPERTY: old}),
                                self.NOW, COLUMNS).startswith("scheduled (7 days")

    def test_no_mark_means_full(self):
        assert full_read_reason(POLICY, self._properties(**{MARK_PROPERTY: ""}),
                                self.NOW, COLUMNS) == "no mark recorded yet"

    def test_an_undeclared_table_is_full(self):
        assert full_read_reason(None, self._properties(), self.NOW, COLUMNS) == \
            "not declared incremental"


def test_run_sync_reads_a_declared_table_by_its_changes(synced_deployment):
    """THE WIRING, end to end: data_silos.yaml's declaration reaches the
    sync, the first run after declaring reads in full and says why, the
    next reads changes, and `--full` reads everything again."""
    from scripts.run_sync import run_sync

    silos = synced_deployment.config_dir / "data_silos.yaml"
    silos.write_text(silos.read_text().replace(
        '      path: "dev_fixtures/mediator.db"',
        '      path: "dev_fixtures/mediator.db"\n'
        '    incremental:\n'
        '      transactions:\n'
        '        cursor: transaction_date', 1))

    def printed(**kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert run_sync(synced_deployment, **kwargs) == 0
        return next(line for line in out.getvalue().splitlines()
                    if line.startswith("synced  primary_sql.transactions"))

    assert "read full (first read since it was declared incremental)" in printed()
    assert "row(s) at or after transaction_date" in printed()
    assert "read full (a full read was asked for)" in printed(full=True)
