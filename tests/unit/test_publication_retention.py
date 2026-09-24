"""
How many publications gold keeps (OPEN_RISKS item 3).

THE RISK AS RECORDED: nothing expires anything, so a nightly
deployment accumulates named publications forever.

WHAT IS FIXED, AND WHAT IS NOT, because the difference matters. The
LIST OF NAMED PUBLICATIONS is now bounded, which is what an operator
navigates by. THE SNAPSHOTS THEMSELVES ARE NOT REMOVED, so this frees
no disk: PyIceberg 0.12 exposes ExpireSnapshots and it expires nothing
here -- tried through the table, through a transaction, with
older_than and with explicit by_ids, on snapshots that were neither
current nor referenced. Nine snapshots stayed nine every time.

IT IS STILL THE NECESSARY FIRST HALF: a tag PINS its snapshot, so
until the tags go, no expiry could remove anything even if it worked.

AND THE CHANGELOG IS UNAFFECTED, which is what makes forgetting safe.
The record of what CHANGED between publications lives in its own
append-only table (GOLD-4). Forgetting `published-3` loses the ability
to read the table AS IT WAS then; it loses nothing about what
happened.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.gold import DEFAULT_RETAINED_PUBLICATIONS, build_gold
from core.mirror.iceberg_sync import IcebergMirrorSync

TYPE = {
    "id_field": "id",
    "security": {"field": "v"},
    "storage": {"silo": "p", "table": "t", "id_column": "id"},
    "fields": {"id": {"type": "data"}, "v": {"type": "data"}},
}


@pytest.fixture
def mirrored(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t VALUES ('a', '1')")
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "mirror",
                              {"p": SQLiteReadAdapter({"path": source})})
    sync.sync_table("p", "t", "id", ["id", "v"], {"id": "string", "v": "string"})
    return sync


def _publish(sync, times, retain):
    silver = sync._catalog.load_table("p.t")
    for _ in range(times):
        result = build_gold(sync._catalog, "Thing", TYPE,
                             silver.scan().to_arrow(), retain_publications=retain)
    return result


def _tags(sync):
    gold = sync._catalog.load_table("gold.Thing")
    return sorted((name for name in gold.refs() if name.startswith("published-")),
                   key=lambda name: int(name.rsplit("-", 1)[1]))


class TestTheListStaysBounded:
    def test_older_publications_are_forgotten(self, mirrored):
        _publish(mirrored, times=8, retain=3)

        assert _tags(mirrored) == ["published-6", "published-7", "published-8"]

    def test_the_count_is_reported(self, mirrored):
        result = _publish(mirrored, times=5, retain=3)

        assert result.forgotten_publications == 1

    def test_nothing_is_forgotten_below_the_limit(self, mirrored):
        result = _publish(mirrored, times=3, retain=10)

        assert result.forgotten_publications == 0
        assert len(_tags(mirrored)) == 3

    def test_zero_keeps_everything(self, mirrored):
        """The old behaviour, still available to a deployment that
        wants every publication nameable forever."""
        _publish(mirrored, times=5, retain=0)

        assert len(_tags(mirrored)) == 5

    def test_a_NEGATIVE_limit_forgets_nothing(self, mirrored):
        """WRITTEN BECAUSE A CONTROL PROVED NOTHING. Removing the
        `retain <= 0` guard changed nothing for zero, because
        `tags[:-0]` is `tags[:0]` -- the empty list -- so zero keeps
        everything by accident of slicing rather than by intent.

        A NEGATIVE number is where it shows: without the guard,
        retain=-1 slices `tags[:1]` and forgets the OLDEST publication
        on every build, which is a config typo quietly eating history.
        """
        _publish(mirrored, times=4, retain=-1)

        assert len(_tags(mirrored)) == 4

    def test_the_default_is_a_month_of_nightlies(self):
        assert DEFAULT_RETAINED_PUBLICATIONS == 30


class TestTheNumberingKeepsGoing:
    """THE BUG RETENTION EXPOSED, in two places at once. The
    publication number was computed as one more than HOW MANY TAGS
    EXIST, which is the same answer until old ones start being
    forgotten -- and then, with three kept, the next publication was
    numbered four, collided with a tag already there, and the sequence
    STALLED AT 2, 3, 4 FOREVER while publishing happily."""

    def test_the_numbers_advance_past_what_was_forgotten(self, mirrored):
        _publish(mirrored, times=8, retain=3)

        assert _tags(mirrored)[-1] == "published-8"

    def test_no_number_is_ever_reused(self, mirrored):
        """A repeated number is worse than a large one: it makes two
        different tables answer to the same name."""
        seen = []
        silver = mirrored._catalog.load_table("p.t")
        for _ in range(10):
            build_gold(mirrored._catalog, "Thing", TYPE,
                        silver.scan().to_arrow(), retain_publications=2)
            seen.extend(name for name in _tags(mirrored) if name not in seen)

        assert len(seen) == len(set(seen)) == 10

    def test_BOTH_publication_paths_number_the_same_way(self, mirrored):
        """The first build appends and tags; every later one publishes
        through the audit branch. Each had its own copy of the rule,
        and the second was found only by counting tags after eight
        builds and seeing three."""
        _publish(mirrored, times=1, retain=3)
        first = _tags(mirrored)

        _publish(mirrored, times=1, retain=3)

        assert first == ["published-1"]
        assert _tags(mirrored) == ["published-1", "published-2"]


class TestWhatIsNotLost:
    def test_the_table_still_reads_after_forgetting(self, mirrored):
        _publish(mirrored, times=8, retain=2)

        gold = mirrored._catalog.load_table("gold.Thing")
        assert gold.scan().to_arrow().num_rows == 1

    def test_the_changelog_is_untouched(self, mirrored):
        """What CHANGED lives in its own append-only table, so
        forgetting a publication loses the ability to read the table as
        it was -- not the record of what happened."""
        _publish(mirrored, times=8, retain=2)

        # NOTHING CHANGED between these publications -- the source is
        # static -- so the changelog records nothing, and the absence
        # of the table IS the evidence: retention did not create,
        # touch, or remove it.
        from pyiceberg.exceptions import NoSuchTableError
        with pytest.raises(NoSuchTableError):
            mirrored._catalog.load_table("gold_history.Thing")

    def test_the_snapshots_themselves_remain(self, mirrored):
        """MEASURED, AND NOT A FIX: PyIceberg 0.12's ExpireSnapshots
        expires nothing here, so this frees no disk. Asserted so the
        day it starts working is a failing test rather than a
        surprise."""
        _publish(mirrored, times=6, retain=2)

        gold = mirrored._catalog.load_table("gold.Thing")
        assert len(gold.snapshots()) > len(_tags(mirrored))
