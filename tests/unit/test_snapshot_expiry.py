"""
Expiring the snapshots that forgetting a publication released
(PA001-M1).

I GOT THIS WRONG, IN PUBLIC, AND AN AUDIT CAUGHT IT. Patch 397 said
PyIceberg 0.12 cannot expire snapshots and called it "measured rather
than assumed". It was measured -- through the WRONG ENTRY POINT.
`ExpireSnapshots(table.transaction()).commit()` is a silent no-op: 15
snapshots stayed 15. `table.maintenance.expire_snapshots()` is the
public one, and takes the same table from 15 to 3.

SIX PLACES IN THIS REPOSITORY SAID IT COULD NOT BE DONE, and every one
of them said "checked, not assumed". The same wrong check, repeated
until it read like corroboration. A claim is only as good as its entry
point.

AND THE CONCLUSION WAS RIGHT FOR THE WRONG REASON. Patch 397 said
retention frees no disk. It does not -- measured again here: 15
snapshots become 3 while the Parquet files stay at 10 and the new
metadata file makes the directory 7.7 KB LARGER. What expiry bounds is
METADATA, and that is worth having: over 40 publications, 79 snapshots
and a 62 KB metadata.json become 5 and 20 KB, and load_table drops from
1.9 ms to 1.0 ms. Every generation build loads every table.

THE SAFETY RULES ARE THE REPOSITORY'S OWN, written down before the
capability existed (tests/unit/test_snapshot_retention_guard.py,
HOT_RELOAD_PLAN.md step 5h): never reclaim the CURRENT snapshot, and
expire by AGE with a margin longer than the longest possible request.
That guard was written to fail the moment expiry appeared. It did not
fail here only because the implementation obeys it.
"""

import sqlite3

import pytest

import core.mirror.iceberg_sync as iceberg_sync
from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.gold import build_gold
from core.mirror.iceberg_sync import IcebergMirrorSync

TYPE = {
    "id_field": "id",
    "security": {"field": "v"},
    "storage": {"silo": "p", "table": "t", "id_column": "id"},
    "fields": {"id": {"type": "data"}, "v": {"type": "data"}},
}


@pytest.fixture
def published(tmp_path):
    """Eight publications with three retained, so five tags were
    forgotten and their snapshots are expirable."""
    def build(publications=8, retain=3):
        source = tmp_path / f"s{publications}{retain}.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t VALUES ('a', '1')")
        conn.commit()
        conn.close()
        sync = IcebergMirrorSync(tmp_path / f"m{publications}{retain}",
                                  {"p": SQLiteReadAdapter({"path": source})})
        sync.sync_table("p", "t", "id", ["id", "v"],
                        {"id": "string", "v": "string"})
        silver = sync._catalog.load_table("p.t")
        for _ in range(publications):
            build_gold(sync._catalog, "Thing", TYPE, silver.scan().to_arrow(),
                        retain_publications=retain)
        return sync
    return build


def _gold(sync):
    return sync._catalog.load_table("gold.Thing")


def _tags(table):
    return sorted(n for n in table.refs() if n.startswith("published-"))


class TestTheAgeMargin:
    """The safety property, and it is the DEFAULT behaviour."""

    def test_nothing_is_expired_within_the_margin(self, published):
        """A snapshot a running request might be pinned to is never
        taken away underneath it. Seven days against a request bounded
        by max_hops and the timeout: unreachable, not merely
        unlikely."""
        sync = published()

        assert len(_gold(sync).snapshots()) > len(_tags(_gold(sync)))

    def test_the_margin_is_the_repository_s_own_constant(self):
        """Not a second number invented here. The guard test requires
        exactly this name."""
        assert iceberg_sync.RETENTION_MARGIN_MS == 7 * 24 * 60 * 60 * 1000


class TestOnceSnapshotsAreOldEnough:
    """With the margin at zero, every released snapshot goes."""

    @pytest.fixture(autouse=True)
    def _no_margin(self, monkeypatch):
        monkeypatch.setattr(iceberg_sync, "RETENTION_MARGIN_MS", 0)

    def test_the_released_snapshots_are_expired(self, published):
        sync = published(publications=8, retain=3)

        gold = _gold(sync)
        assert len(gold.snapshots()) == 3

    def test_every_retained_publication_still_resolves(self, published):
        """THE PROPERTY THAT MAKES IT SAFE: a tag pins its snapshot, so
        expiry can only reclaim what forgetting a publication
        released."""
        sync = published(publications=8, retain=3)

        gold = _gold(sync)
        assert _tags(gold) == ["published-6", "published-7", "published-8"]
        assert all(gold.snapshot_by_name(name) for name in _tags(gold))

    def test_the_current_snapshot_survives(self, published):
        """The guard's primary rule. The library enforces it -- current
        is a ref head -- but a rule nobody asserts is a rule nobody
        notices breaking."""
        sync = published(publications=8, retain=3)

        assert _gold(sync).current_snapshot() is not None

    def test_the_table_still_reads(self, published):
        sync = published(publications=8, retain=3)

        assert _gold(sync).scan().to_arrow().num_rows == 1

    def test_nothing_is_expired_when_no_tag_was_forgotten(self, published):
        """Expiry runs only where retention released something, so a
        deployment keeping every publication is untouched."""
        sync = published(publications=3, retain=10)

        gold = _gold(sync)
        assert len(_tags(gold)) == 3 and len(gold.snapshots()) > 3


class TestItNeverFailsAPublish:
    def test_an_expiry_failure_is_logged_and_swallowed(self, published, monkeypatch,
                                                        caplog):
        """Retention is housekeeping. A publish that succeeded must not
        be reported as failed because the tidying afterwards did not."""
        import core.mirror.gold as gold_module

        def explode(table):
            raise OSError("catalog unavailable (injected)")

        monkeypatch.setattr(gold_module, "_expire_unreferenced", explode)

        with caplog.at_level("WARNING"):
            sync = published(publications=5, retain=2)

        assert _gold(sync).scan().to_arrow().num_rows == 1


class TestWhatExpiryDoesNotDo:
    def test_it_reclaims_no_data_files(self, published, monkeypatch):
        """MEASURED, AND THE OPPOSITE OF THE NATURAL ASSUMPTION.
        Patch 397 concluded "frees no disk" for the wrong reason; the
        conclusion survives the correction. Reclaiming the files needs
        an orphan sweep, which pyiceberg does not have yet
        (apache/iceberg-python #3361)."""
        monkeypatch.setattr(iceberg_sync, "RETENTION_MARGIN_MS", 0)
        sync = published(publications=8, retain=3)

        warehouse = sync._catalog.properties["warehouse"].replace("file://", "")
        from pathlib import Path
        parquet = list(Path(warehouse).rglob("*.parquet"))

        assert len(_gold(sync).snapshots()) == 3
        assert len(parquet) > 3, "if this ever fails, an orphan sweep landed upstream"
