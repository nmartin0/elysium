"""
Readers pin a PUBLICATION, never whatever snapshot happens to be
current (PA001-G4).

THE FAILURE. On a FIRST build the rows are appended BEFORE they are
audited and tagged. A crash in between -- a power cut, a full disk, an
OSError out of the catalog -- leaves a table with a current snapshot,
NO published tag, and readers pinning the unaudited rows.

REPRODUCED: a first build interrupted after the append published
nothing, carried no tag at all, and readers still pinned it and served
its two rows.

PUBLICATION IS THE PROMISE. `published-N` is written by
_tag_publication only after the audit passes, so a table without one
has never made that promise. A type with no publication is ABSENT from
the pinning, exactly as a type with no gold table is, and GOLD-8's
read path turns that absence into a loud GoldPublicationMissing rather
than a quiet wrong answer.

ON THE HAPPY PATH IT IS THE SAME SNAPSHOT: publishing sets the current
snapshot to the audited one and tags it in a single commit. The
difference only shows when something went wrong -- which is why the
change was invisible to every existing test.

WHY THIS FILE EXISTS SEPARATELY FROM THE FIX. The fix reached `dev`
inside patch 420, whose message says "Documentation and tooling only".
It was uncommitted work in the tree when that patch was staged with
`git add -A`. The code is right; it arrived with no tests, no
controls, and a commit message that denies it exists. These are the
tests it should have had.
"""

import sqlite3

import pytest

import core.mirror.gold as gold
from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.gold import build_gold, published_snapshot_ids
from core.mirror.iceberg_sync import IcebergMirrorSync

TYPE = {
    "id_field": "id",
    "security": {"field": "region"},
    "storage": {"silo": "p", "table": "t", "id_column": "id"},
    "fields": {"id": {"type": "data"}, "v": {"type": "data"},
                "region": {"type": "data"}},
}


@pytest.fixture
def deployment(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT, region TEXT)")
    conn.executemany("INSERT INTO t VALUES (?,?,?)",
                     [("a", "1", "us-west"), ("b", "2", "us-west")])
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "m", {"p": SQLiteReadAdapter({"path": source})})
    sync.sync_table("p", "t", "id", ["id", "v", "region"], {})

    def publish():
        silver = sync.catalog.load_table("p.t").scan().to_arrow()
        return build_gold(sync.catalog, "Thing", TYPE, silver)

    def pinned():
        return published_snapshot_ids(sync.catalog, {"Thing": TYPE})

    def tags():
        table = sync.catalog.load_table("gold.Thing")
        return sorted(n for n in table.refs() if n.startswith("published-"))

    sync.publish, sync.pinned, sync.tags = publish, pinned, tags
    return sync


class TestACrashBeforeThePublication:
    def test_nothing_is_pinned(self, deployment, monkeypatch):
        """THE REGRESSION TEST. The rows are on disk and the table has
        a current snapshot; what it does NOT have is a publication."""
        def crash(table):
            raise OSError("power cut (injected)")
        monkeypatch.setattr(gold, "_tag_publication", crash)

        with pytest.raises(OSError):
            deployment.publish()

        assert deployment.pinned() == {}

    def test_the_unaudited_rows_really_are_there(self, deployment, monkeypatch):
        """Proving the test above is not passing for a trivial reason:
        the rows exist and are readable, and are still not served."""
        monkeypatch.setattr(gold, "_tag_publication",
                             lambda table: (_ for _ in ()).throw(OSError("crash")))
        with pytest.raises(OSError):
            deployment.publish()

        table = deployment.catalog.load_table("gold.Thing")
        assert table.current_snapshot() is not None
        assert table.scan().to_arrow().num_rows == 2
        assert deployment.tags() == []

    def test_a_later_good_build_recovers(self, deployment, monkeypatch):
        """A crash must not need a human to undo it."""
        monkeypatch.setattr(gold, "_tag_publication",
                             lambda table: (_ for _ in ()).throw(OSError("crash")))
        with pytest.raises(OSError):
            deployment.publish()
        monkeypatch.undo()

        deployment.publish()

        assert deployment.pinned() != {}


class TestTheHappyPathIsUnchanged:
    def test_a_clean_build_is_pinned(self, deployment):
        deployment.publish()

        assert "Thing" in deployment.pinned()

    def test_it_pins_exactly_the_published_tag(self, deployment):
        """The property that makes this safe to change at all: on a
        healthy table it is the SAME snapshot the old code chose."""
        deployment.publish()

        table = deployment.catalog.load_table("gold.Thing")
        by_tag = {name: ref.snapshot_id for name, ref in table.refs().items()
                  if name.startswith("published-")}
        assert deployment.pinned()["Thing"] in by_tag.values()

    def test_it_pins_the_NEWEST_publication(self, deployment):
        """Three publications; a reader gets the last one, not the
        first tag the dictionary happens to yield."""
        deployment.publish()
        deployment.publish()
        deployment.publish()

        table = deployment.catalog.load_table("gold.Thing")
        newest = max((int(n.rsplit("-", 1)[1]), r.snapshot_id)
                     for n, r in table.refs().items()
                     if n.startswith("published-"))[1]
        assert deployment.pinned()["Thing"] == newest

    def test_a_type_with_no_gold_table_is_simply_absent(self, deployment):
        assert "Missing" not in published_snapshot_ids(
            deployment.catalog, {"Missing": TYPE})
