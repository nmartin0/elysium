"""
A second publication records its history, streamed or not (GOLD-4,
GOLD-7).

WHAT WAS BROKEN. The streaming path (GOLD-7) never materialises its
rows -- that is the point of it, measured at +81.8 MB materialised
against +11.0 MB streamed -- so `rows` is None for a single-source
type with no identity rule, which is most types. `record_publication`
then diffed against None, raised TypeError, and the failure was
SWALLOWED into a warning:

    gold.Customer published, but its history was not recorded:
    'NoneType' object is not iterable

The sync reported success. Every publication after the first recorded
NO HISTORY for every streamed type, and GOLD-4's entire purpose is
answering "what changed between publications".

WHY NO TEST SAW IT, which is the part worth keeping. A FIRST
publication has no history by definition, so `record_publication`
returns 0 before touching the rows. The bug needs a SECOND publication
to appear at all, and every existing test built gold once. It surfaced
when a real deployment ran `run_sync` twice.

THE FIX READS THE ROWS BACK rather than keeping them, and only when
there is a previous publication to diff against -- `previous_rows` is
already materialised for exactly that comparison, so the marginal cost
is one table, not two.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.gold import build_gold
from core.mirror.iceberg_sync import IcebergMirrorSync

TYPE = {
    "id_field": "id",
    "security": {"field": "region"},
    "storage": {"silo": "p", "table": "t", "id_column": "id"},
    "fields": {"id": {"type": "data"}, "name": {"type": "data"},
                "region": {"type": "data"}},
}


@pytest.fixture
def deployment(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, name TEXT, region TEXT)")
    conn.executemany("INSERT INTO t VALUES (?,?,?)",
                     [("a", "Ada", "us-west"), ("b", "Bram", "us-west")])
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "m", {"p": SQLiteReadAdapter({"path": source})})

    def publish():
        sync.sync_table("p", "t", "id", ["id", "name", "region"], {})
        silver = sync.catalog.load_table("p.t").scan().to_arrow()
        return build_gold(sync.catalog, "Thing", TYPE, silver)

    def change(sql):
        conn = sqlite3.connect(source)
        conn.execute(sql)
        conn.commit()
        conn.close()

    def history():
        return sync.catalog.load_table("gold_history.Thing").scan().to_arrow().to_pylist()

    sync.publish, sync.change, sync.history = publish, change, history
    return sync


class TestTheSecondPublication:
    def test_an_update_is_recorded(self, deployment):
        """THE REGRESSION TEST, and it needs two publications: the
        first has no history by definition, which is exactly why this
        went unseen."""
        deployment.publish()
        deployment.change("UPDATE t SET name='Ada L.' WHERE id='a'")

        result = deployment.publish()

        assert result.history_rows == 1
        assert [r["_change"] for r in deployment.history()] == ["UPDATE"]

    def test_an_insert_is_recorded(self, deployment):
        deployment.publish()
        deployment.change("INSERT INTO t VALUES ('c','Chidi','us-west')")

        deployment.publish()

        recorded = {(r["id"], r["_change"]) for r in deployment.history()}
        assert ("c", "INSERT") in recorded

    def test_a_delete_is_recorded(self, deployment):
        deployment.publish()
        deployment.change("DELETE FROM t WHERE id='b'")

        deployment.publish()

        recorded = {(r["id"], r["_change"]) for r in deployment.history()}
        assert ("b", "DELETE") in recorded

    def test_the_publication_still_succeeds(self, deployment):
        """History must never be the reason a publication fails --
        that guarantee is what let this hide, so it is pinned rather
        than removed."""
        deployment.publish()
        deployment.change("UPDATE t SET name='Ada L.' WHERE id='a'")

        result = deployment.publish()

        assert result.published


class TestNothingIsRecordedWhenNothingChanged:
    def test_an_unchanged_republication_records_no_rows(self, deployment):
        deployment.publish()

        result = deployment.publish()

        assert result.history_rows == 0


class TestTheFirstPublication:
    def test_does_not_read_the_table_back(self, deployment, monkeypatch):
        """WRITTEN BECAUSE A CONTROL PROVED NOTHING. Dropping the
        `previous_rows is not None` guard left every test passing,
        because record_publication returns 0 on a first build anyway.

        The guard is about COST, not correctness: streaming exists so
        a publication does not hold its table in memory, and reading
        it back on a FIRST build would pay that price for a diff that
        is never computed. What record_publication RECEIVES is the
        observable difference -- None with the guard, a materialised
        list without it."""
        import core.mirror.gold_history as history_module

        received = []
        real = history_module.record_publication

        def spy(catalog, object_type, id_field, previous_rows, current_rows,
                 published_at, snapshot_id):
            received.append(current_rows)
            return real(catalog, object_type, id_field, previous_rows,
                         current_rows, published_at, snapshot_id)
        monkeypatch.setattr(history_module, "record_publication", spy)

        deployment.publish()

        assert received == [None], (
            "the table was materialised for a first build, which has no "
            "history to compute")

    def test_has_no_history(self, deployment):
        """Writing every row as an INSERT would claim a change that
        did not happen."""
        result = deployment.publish()

        assert result.history_rows == 0
        assert not deployment.catalog.table_exists("gold_history.Thing")
