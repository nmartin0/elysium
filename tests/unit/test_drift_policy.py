"""
What a sync does when the source changes shape -- decided, not emergent.

Before this, one drift shape had an answer and the rest had BEHAVIOUR.
Type drift raised; a vanished column produced whatever the adapter's
SELECT happened to do. Nobody decided that, and nobody could say what a
new shape would do without running it.

THE RULE FOR DESTRUCTIVE CHANGE IS FOUNDRY'S, and it is sharper than
"always refuse": in Object Storage v2 a schema change is breaking only
if the property HAS RECEIVED USER EDITS. The write log is the same
thing under another name.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.drift_policy import verdict_for_removed_column, verdict_for_type_change
from core.mirror.iceberg_sync import IcebergMirrorSync


class _FakeWriteLog:
    def __init__(self, counts):
        self._counts = counts

    def edits_touching_field(self, object_type, field_name):
        return self._counts


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, region TEXT)")
    conn.execute("INSERT INTO customers VALUES ('c1', 'Ada', 'us-west')")
    conn.commit()
    conn.close()
    return path


def _drop_region(source):
    conn = sqlite3.connect(source)
    conn.execute("ALTER TABLE customers DROP COLUMN region")
    conn.commit()
    conn.close()


def _sync(tmp_path, source, write_log=None):
    return IcebergMirrorSync(
        tmp_path / "mirror", {"primary": SQLiteReadAdapter({"path": source})},
        write_log=write_log,
    )


COLUMNS = ["customer_id", "name", "region"]
TYPES = {"customer_id": "string", "name": "string", "region": "string"}
FIELDS = {"region": "region"}


class TestRemovedColumn:
    def test_absorbs_when_nothing_ever_wrote_to_the_field(self, tmp_path, source):
        # FOUNDRY'S LINE. Refusing here freezes the mirror over a column
        # nobody used, and a frozen mirror goes stale while the source
        # moves on -- stale data that looks current is its own wrong.
        sync = _sync(tmp_path, source, _FakeWriteLog({"applied": 0, "pending": 0}))
        _drop_region(source)

        result = sync.sync_table("primary", "customers", "customer_id", COLUMNS, TYPES, FIELDS)

        # The sync SUCCEEDED without the dropped column, and the mirror
        # no longer carries it -- absorbed, not ignored.
        assert result.row_count == 1
        mirrored = sync._catalog.load_table("primary.customers").schema()
        assert "region" not in {field.name for field in mirrored.fields}

    def test_refuses_when_a_pending_write_depends_on_it(self, tmp_path, source):
        # A pending write is an OBLIGATION: proposed, undecided, and if
        # its field goes it can never be applied.
        sync = _sync(tmp_path, source, _FakeWriteLog({"applied": 0, "pending": 2}))
        _drop_region(source)

        with pytest.raises(ValueError, match="2 pending"):
            sync.sync_table("primary", "customers", "customer_id", COLUMNS, TYPES, FIELDS)

    def test_refuses_when_applied_history_depends_on_it(self, tmp_path, source):
        sync = _sync(tmp_path, source, _FakeWriteLog({"applied": 5, "pending": 0}))
        _drop_region(source)

        with pytest.raises(ValueError, match="5 applied"):
            sync.sync_table("primary", "customers", "customer_id", COLUMNS, TYPES, FIELDS)

    def test_refuses_when_it_could_not_check(self, tmp_path, source):
        # THE PROPERTY THAT MATTERS MOST. Absorbing on the strength of a
        # check that did not happen looks identical to "nothing was
        # written", and it is not the same claim.
        sync = _sync(tmp_path, source, write_log=None)
        _drop_region(source)

        with pytest.raises(ValueError, match="no write log was available"):
            sync.sync_table("primary", "customers", "customer_id", COLUMNS, TYPES, FIELDS)

    def test_the_refusal_leaves_the_mirror_serving(self, tmp_path, source):
        # A refused sync must not be a broken mirror. The last good
        # contents keep serving while the operator decides.
        sync = _sync(tmp_path, source, _FakeWriteLog({"applied": 0, "pending": 0}))
        sync.sync_table("primary", "customers", "customer_id", COLUMNS, TYPES, FIELDS)
        _drop_region(source)
        sync._write_log = _FakeWriteLog({"applied": 1, "pending": 0})

        with pytest.raises(ValueError):
            sync.sync_table("primary", "customers", "customer_id", COLUMNS, TYPES, FIELDS)

        rows = sync._catalog.load_table("primary.customers").scan().to_arrow().to_pydict()
        assert rows["region"] == ["us-west"]

    def test_a_refusal_wins_over_an_absorption(self):
        # Several columns can vanish at once. Absorbing some while
        # refusing another would leave the mirror half-migrated to a
        # shape nobody approved.
        refusing = verdict_for_removed_column(
            "s", "t", "col", "field", {"applied": 0, "pending": 1},
        )
        absorbing = verdict_for_removed_column(
            "s", "t", "other", "other_field", {"applied": 0, "pending": 0},
        )

        assert refusing.absorbed is False
        assert absorbing.absorbed is True

    def test_the_refusal_names_the_options(self):
        # An error saying only "drift detected" makes the operator find
        # the field, the counts and the remedy themselves.
        verdict = verdict_for_removed_column(
            "primary", "customers", "region", "region", {"applied": 1, "pending": 1},
        )

        assert "Restore the column upstream" in verdict.detail
        assert "ontology_schema.yaml" in verdict.detail


class TestTypeChange:
    def test_is_always_refused_even_with_no_writes(self):
        # Unlike a removal this does not soften: the column is still
        # THERE and still READ, so absorbing means serving values of a
        # type the ontology says they are not. That reaches every
        # reader, where a removal's damage is confined to writers.
        verdict = verdict_for_type_change("primary", "customers", "amount")

        assert verdict.absorbed is False
        assert "will not cast between them silently" in verdict.detail
