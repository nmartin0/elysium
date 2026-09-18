"""
What changed between two syncs, and in which direction.

WHY A CHANGELOG, and it is not performance. A source database holds
"now". It has no record that a customer's region was us-west last
March, and no re-sync recovers what it has since overwritten. If that
history matters, only we can keep it.

This is the point at which the mirror stops being a CACHE and becomes a
SYSTEM OF RECORD, which is why durable storage landed first.

NOT CHANGE DATA CAPTURE. Real CDC receives a feed from the source; this
diffs two snapshots we took ourselves -- Foundry's documented fallback
for exactly our case, where "my source system sends a full snapshot
every sync" and "transforms apply CDC to detect inserts, updates, and
deletes, then write only the changes as APPEND transactions".

THE LIMIT THAT FOLLOWS is inherent rather than a gap: bronze keeps two
snapshots, so only consecutive syncs can be compared. A missed sync
loses the intervening state permanently. Diffing sees where the data
got to, never the path it took.
"""

import pytest

from core.mirror.changelog import (
    DELETE,
    INSERT,
    MAX_DELETED_FRACTION,
    UPDATE,
    diff_snapshots,
)


def _rows(*pairs):
    return [{"id": i, "a": a} for i, a in pairs]


def _by_change(changes):
    return {row["_change"] for row in changes.rows}


class TestTheThreeDirections:
    def test_a_new_row_is_an_insert(self):
        changes = diff_snapshots(_rows(("1", "x")), _rows(("1", "x"), ("2", "y")), "id")

        assert len(changes.rows) == 1
        assert changes.rows[0]["_change"] == INSERT
        assert changes.rows[0]["id"] == "2"

    def test_a_changed_value_is_an_update(self):
        changes = diff_snapshots(_rows(("1", "x")), _rows(("1", "CHANGED")), "id")

        assert len(changes.rows) == 1
        assert changes.rows[0]["_change"] == UPDATE
        assert changes.rows[0]["a"] == "CHANGED"

    def test_a_vanished_row_is_a_delete(self):
        changes = diff_snapshots(_rows(("1", "x"), ("2", "y")), _rows(("1", "x")), "id")

        assert len(changes.rows) == 1
        assert changes.rows[0]["_change"] == DELETE

    def test_a_delete_carries_the_row_as_it_last_stood(self):
        """The only version of it that will ever exist again.

        Recording just the id would make the changelog useless for the
        question it exists to answer -- what did this look like before
        it went.

        Enough surviving rows that the partial-read guard does not
        fire: a first version deleted the only row, which IS a mass
        disappearance and was correctly refused.
        """
        previous = _rows(("1", "final value"), ("2", "b"), ("3", "c"), ("4", "d"))
        changes = diff_snapshots(previous, _rows(("2", "b"), ("3", "c"), ("4", "d")), "id")

        assert changes.rows[0]["a"] == "final value"

    def test_an_unchanged_row_is_not_recorded(self):
        # THE CONTROL. A changelog that recorded every row every sync
        # would be a slower copy of the table it sits beside.
        changes = diff_snapshots(_rows(("1", "x"), ("2", "y")), _rows(("1", "x"), ("2", "y")), "id")

        assert changes.is_empty

    def test_all_three_can_happen_in_one_sync(self):
        changes = diff_snapshots(
            _rows(("1", "x"), ("2", "y"), ("3", "z")),
            _rows(("1", "CHANGED"), ("2", "y"), ("4", "new")),
            "id",
        )

        assert _by_change(changes) == {UPDATE, INSERT, DELETE}


class TestThePartialReadGuard:
    """Deletions are INFERRED, and that is the dangerous part.

    Our sources do not report deletions, so absence from the new
    snapshot is the only signal. Sound when a sync read the whole
    table; catastrophic when one partially failed -- a read returning
    half the rows would be recorded as half the table being deleted,
    and a changelog is the one thing in the mirror a re-sync cannot
    repair.
    """

    def test_a_mass_disappearance_records_nothing(self):
        previous = _rows(*[(str(n), f"v{n}") for n in range(100)])
        current = _rows(("1", "v1"))

        changes = diff_snapshots(previous, current, "id")

        assert changes.suspected_partial_read
        assert changes.is_empty

    def test_a_plausible_number_of_deletions_is_recorded(self):
        # THE CONTROL. A guard that refused everything would silently
        # stop recording deletions altogether, which is the failure it
        # was meant to prevent, arrived at from the other side.
        previous = _rows(*[(str(n), f"v{n}") for n in range(100)])
        current = _rows(*[(str(n), f"v{n}") for n in range(90)])

        changes = diff_snapshots(previous, current, "id")

        assert not changes.suspected_partial_read
        assert len([r for r in changes.rows if r["_change"] == DELETE]) == 10

    def test_the_threshold_is_measured_against_what_was_there_before(self):
        """Not against what came back.

        A read returning NOTHING is exactly the case this exists to
        catch, and dividing by the current count would raise
        ZeroDivisionError on it.
        """
        previous = _rows(*[(str(n), f"v{n}") for n in range(10)])

        changes = diff_snapshots(previous, [], "id")

        assert changes.suspected_partial_read

    def test_an_empty_table_that_stays_empty_is_not_suspicious(self):
        changes = diff_snapshots([], [], "id")

        assert not changes.suspected_partial_read
        assert changes.is_empty

    def test_the_threshold_is_where_it_claims_to_be(self):
        # Exactly at the limit is allowed; beyond it is not.
        previous = _rows(*[(str(n), f"v{n}") for n in range(10)])
        at_limit = _rows(*[(str(n), f"v{n}") for n in range(int(10 * MAX_DELETED_FRACTION))])

        assert not diff_snapshots(previous, at_limit, "id").suspected_partial_read


class TestIdentifierPairing:
    """Foundry's "identifier changelog (recommended)", which we qualify
    for because every object type declares an id_field.

    It is "more performant" than the net-changes mode and gives "richer
    semantics, including update-before and update-after records" -- the
    concrete difference being that an edit reads as one UPDATE rather
    than a DELETE and an INSERT that nothing connects.
    """

    def test_an_edit_is_one_update_not_a_delete_and_an_insert(self):
        changes = diff_snapshots(_rows(("1", "before")), _rows(("1", "after")), "id")

        assert _by_change(changes) == {UPDATE}

    def test_ids_are_compared_as_strings(self):
        # A source returning 1 where the mirror holds "1" is the same
        # row, and treating it as two would record a phantom delete
        # alongside a phantom insert on every sync.
        changes = diff_snapshots([{"id": 1, "a": "x"}], [{"id": "1", "a": "x"}], "id")

        assert changes.is_empty


def test_a_first_sync_reports_everything_as_inserted():
    """Honest rather than silent, and the CALLER decides.

    Writing a whole table as inserts would be a lie and an expensive
    one, so the sync skips the first run -- but this function reports
    what it actually sees rather than guessing at the caller's
    intent.
    """
    changes = diff_snapshots([], _rows(("1", "x"), ("2", "y")), "id")

    assert _by_change(changes) == {INSERT}
    assert len(changes.rows) == 2


class TestWiredIntoTheSync:
    """The diff reaching a table, which the unit tests above cannot see.

    Four times this session a component has been right and the wire to
    it missing. These go through sync_table.
    """

    @staticmethod
    def _make(tmp_path, rows):
        import sqlite3

        source = tmp_path / "source.db"
        connection = sqlite3.connect(source)
        connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, a TEXT)")
        connection.executemany("INSERT INTO t VALUES (?, ?)", rows)
        connection.commit()
        connection.close()
        return source

    @staticmethod
    def _sync(tmp_path, source):
        from adapters.sqlite_adapter import SQLiteReadAdapter
        from core.mirror.iceberg_sync import IcebergMirrorSync

        return IcebergMirrorSync(tmp_path / "mirror", {"s": SQLiteReadAdapter({"path": source})})

    @staticmethod
    def _run(sync):
        sync.sync_table("s", "t", "id", ["id", "a"], {"id": "string", "a": "string"})

    def _changelog(self, sync):
        return sync._catalog.load_table("changelog_s.t").scan().to_arrow().to_pydict()

    def test_the_first_sync_writes_no_changelog(self, tmp_path):
        """A whole table recorded as inserts would be a lie, and an
        expensive one -- it would double the storage of every new
        deployment to say nothing.
        """
        from pyiceberg.exceptions import NoSuchNamespaceError, NoSuchTableError

        sync = self._sync(tmp_path, self._make(tmp_path, [("1", "x")]))
        self._run(sync)

        with pytest.raises((NoSuchTableError, NoSuchNamespaceError)):
            sync._catalog.load_table("changelog_s.t")

    def test_a_change_between_syncs_is_recorded(self, tmp_path):
        import sqlite3

        source = self._make(tmp_path, [("1", "x"), ("2", "y")])
        sync = self._sync(tmp_path, source)
        self._run(sync)

        connection = sqlite3.connect(source)
        connection.execute("UPDATE t SET a = 'CHANGED' WHERE id = '1'")
        connection.commit()
        connection.close()
        self._run(sync)

        recorded = self._changelog(sync)
        assert recorded["_change"] == [UPDATE]
        assert recorded["a"] == ["CHANGED"]

    def test_it_appends_rather_than_replacing(self, tmp_path):
        """THE ONE TABLE IN THE MIRROR THAT ONLY GROWS.

        Every other answers "what is there now" and is rebuilt. This
        answers "what happened", and a sync that overwrote it would
        destroy the history on the very next run.
        """
        import sqlite3

        source = self._make(tmp_path, [("1", "x"), ("2", "y")])
        sync = self._sync(tmp_path, source)
        self._run(sync)

        for value in ("first", "second"):
            connection = sqlite3.connect(source)
            connection.execute("UPDATE t SET a = ? WHERE id = '1'", (value,))
            connection.commit()
            connection.close()
            self._run(sync)

        # SORTED, because Iceberg does not promise scan order and an
        # ordering difference is not a missing entry. What matters is
        # that BOTH survived -- an overwrite would have left one.
        assert sorted(self._changelog(sync)["a"]) == ["first", "second"]

    def test_an_unchanged_sync_adds_nothing(self, tmp_path):
        # The sync skips the write entirely when nothing changed, so
        # the changelog should never even be reached.
        from pyiceberg.exceptions import NoSuchNamespaceError, NoSuchTableError

        sync = self._sync(tmp_path, self._make(tmp_path, [("1", "x")]))
        self._run(sync)
        self._run(sync)

        with pytest.raises((NoSuchTableError, NoSuchNamespaceError)):
            sync._catalog.load_table("changelog_s.t")

    def test_every_entry_says_when_it_was_noticed(self, tmp_path):
        # When we NOTICED, not when it happened -- the source does not
        # tell us the latter, and inventing it would be worse than
        # admitting the difference.
        import sqlite3

        source = self._make(tmp_path, [("1", "x"), ("2", "y")])
        sync = self._sync(tmp_path, source)
        self._run(sync)

        connection = sqlite3.connect(source)
        connection.execute("UPDATE t SET a = 'CHANGED' WHERE id = '1'")
        connection.commit()
        connection.close()
        self._run(sync)

        assert self._changelog(sync)["_recorded_at"][0].startswith("20")

    def test_a_numeric_column_does_not_make_every_row_look_changed(self, tmp_path):
        """THE BUG A TEST CAUGHT AND REASONING DID NOT.

        The previous snapshot is read from BRONZE, which stores strings;
        the current rows come from the ADAPTER, which returns the
        source's own types. So 10.5 never equalled "10.5", and every
        row of any numeric table was recorded as changed on every sync
        -- measured at three UPDATEs when one value had moved.
        """
        import sqlite3

        source = tmp_path / "numeric.db"
        connection = sqlite3.connect(source)
        connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, amount REAL)")
        connection.executemany(
            "INSERT INTO t VALUES (?, ?)", [("1", 10.5), ("2", 20.5), ("3", 30.5)])
        connection.commit()
        connection.close()

        from adapters.sqlite_adapter import SQLiteReadAdapter
        from core.mirror.iceberg_sync import IcebergMirrorSync

        sync = IcebergMirrorSync(tmp_path / "mirror", {"s": SQLiteReadAdapter({"path": source})})
        types = {"id": "string", "amount": "number"}
        sync.sync_table("s", "t", "id", ["id", "amount"], types)

        connection = sqlite3.connect(source)
        connection.execute("UPDATE t SET amount = 99.9 WHERE id = '1'")
        connection.commit()
        connection.close()
        sync.sync_table("s", "t", "id", ["id", "amount"], types)

        assert len(self._changelog(sync)["_change"]) == 1
