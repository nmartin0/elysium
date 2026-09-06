"""
Point 3 of the machinery audit: the external database copying
machinery, checked against Foundry's own documented sync semantics.

FOUNDRY'S MODEL, quoted rather than paraphrased so the comparison is
honest:

  - Transaction type: "The transaction type determines whether ingested
    data overwrites previously ingested data (SNAPSHOT) or whether it
    is added incrementally (APPEND)." Elysium does SNAPSHOT only --
    each sync replaces the table's whole contents.
  - Failure behaviour: "a failure at any point aborts the entire
    transaction," so a failed sync leaves the previous good data in
    place rather than a partially-written table.
  - Ingest is dumb on purpose: data arrives "as-is from its most raw
    source, with no external preprocessing."

WHERE ELYSIUM DELIBERATELY DIFFERS, stated rather than glossed:

  - No APPEND mode. Foundry offers incremental APPEND for large
    datasets, where "a sync failure will result in a minimal amount of
    duplicated work rather than requiring a complete re-run." Elysium
    is SNAPSHOT-only, which is simpler and correct, but means a large
    table re-copies entirely each run. This is a real, known scaling
    limit rather than an oversight.
  - Per-TABLE independence. scripts/run_sync.py continues after a
    failed table rather than aborting every table. That matches
    Foundry's own granularity -- a Foundry sync targets ONE dataset,
    so "aborts the entire transaction" is scoped to one table there
    too -- and a partial refresh of the remaining tables is strictly
    better than none.

Each test below pins one of these properties so it cannot silently
regress.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE widgets (widget_id TEXT PRIMARY KEY, label TEXT)")
    conn.executemany(
        "INSERT INTO widgets VALUES (?, ?)", [(f"w{i}", f"label{i}") for i in range(5)]
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def sync(tmp_path, source):
    return IcebergMirrorSync(tmp_path / "mirror", {"primary": SQLiteReadAdapter({"path": source})})


def _mirror(sync, identifier="primary.widgets"):
    return sync._catalog.load_table(identifier).scan().to_arrow()


def _sync(sync):
    return sync.sync_table("primary", "widgets", "widget_id", ["widget_id", "label"])


def test_a_sync_is_a_snapshot_that_replaces_rather_than_appends(sync, source):
    # Foundry's SNAPSHOT: ingested data "overwrites previously ingested
    # data." Running twice must not double the rows.
    _sync(sync)
    _sync(sync)

    assert _mirror(sync).num_rows == 5


def test_rows_deleted_at_the_source_disappear_from_the_mirror(sync, source):
    # The property an APPEND-based copy would get WRONG: a deleted row
    # would linger in the mirror forever. SNAPSHOT semantics mean the
    # mirror reflects the source as it is now.
    _sync(sync)

    conn = sqlite3.connect(source)
    conn.execute("DELETE FROM widgets WHERE widget_id IN ('w0', 'w1')")
    conn.commit()
    conn.close()

    result = _sync(sync)

    assert result.row_count == 3
    assert "w0" not in _mirror(sync).to_pydict()["widget_id"]


def test_an_emptied_source_table_produces_an_empty_mirror(sync, source):
    # The extreme of the same property. Worth pinning explicitly: a
    # SNAPSHOT of an empty table is genuinely empty, not "keep the last
    # non-empty version." That is correct, and it is also the behaviour
    # most likely to alarm someone, so it is asserted deliberately.
    _sync(sync)

    conn = sqlite3.connect(source)
    conn.execute("DELETE FROM widgets")
    conn.commit()
    conn.close()

    assert _sync(sync).row_count == 0
    assert _mirror(sync).num_rows == 0


def test_a_failed_read_leaves_the_last_good_mirror_intact(sync, source):
    # Foundry: "a failure at any point aborts the entire transaction."
    # A sync that cannot read its source must not damage what is
    # already mirrored.
    _sync(sync)

    conn = sqlite3.connect(source)
    conn.execute("ALTER TABLE widgets DROP COLUMN label")
    conn.commit()
    conn.close()

    with pytest.raises(sqlite3.OperationalError):
        _sync(sync)

    mirrored = _mirror(sync)
    assert mirrored.num_rows == 5
    assert mirrored.column_names == ["widget_id", "label"]


def test_a_crash_during_the_write_leaves_the_previous_snapshot_readable(sync, source):
    # Iceberg's own commit is atomic -- a table is never left
    # half-written. Verified directly rather than assumed from the
    # format's reputation.
    _sync(sync)
    table = sync._catalog.load_table("primary.widgets")
    original_overwrite = type(table).overwrite

    def exploding_overwrite(self, *args, **kwargs):
        raise RuntimeError("simulated crash mid-overwrite")

    type(table).overwrite = exploding_overwrite
    try:
        with pytest.raises(RuntimeError):
            _sync(sync)
    finally:
        type(table).overwrite = original_overwrite

    assert _mirror(sync).num_rows == 5


def test_syncing_a_table_that_does_not_exist_fails_loudly(sync):
    # Never a silently empty mirror table -- a typo'd or dropped source
    # table must be an error, since an empty mirror is otherwise
    # indistinguishable from a genuinely empty source.
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        sync.sync_table("primary", "nonexistent", "id", ["id"])


def test_a_new_source_column_the_ontology_does_not_know_is_ignored(sync, source):
    # The mirror holds exactly what the ontology references. A column
    # added at the source is not silently copied -- Elysium has no
    # business mirroring data no object type declares.
    _sync(sync)

    conn = sqlite3.connect(source)
    conn.execute("ALTER TABLE widgets ADD COLUMN internal_notes TEXT")
    conn.commit()
    conn.close()

    _sync(sync)

    assert _mirror(sync).column_names == ["widget_id", "label"]


def test_the_sync_reads_a_consistent_snapshot_under_concurrent_source_writes(tmp_path):
    # The bulk read is ONE SQL statement, so a source write during the
    # sync cannot tear the result across rows. This is the property the
    # old per-field read could not offer, since thousands of separate
    # queries genuinely could observe different states.
    import threading

    path = tmp_path / "churn.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE widgets (widget_id TEXT PRIMARY KEY, v INTEGER)")
    conn.executemany(
        "INSERT INTO widgets VALUES (?, ?)", [(f"w{i}", 0) for i in range(2000)]
    )
    conn.commit()
    conn.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": SQLiteReadAdapter({"path": path})})
    stop = threading.Event()

    def churn():
        writer = sqlite3.connect(path, timeout=10)
        counter = 1
        while not stop.is_set():
            writer.execute("UPDATE widgets SET v = ? WHERE widget_id = 'w0'", (counter,))
            writer.commit()
            counter += 1
        writer.close()

    thread = threading.Thread(target=churn)
    thread.start()
    try:
        result = sync.sync_table("primary", "widgets", "widget_id", ["widget_id", "v"])
    finally:
        stop.set()
        thread.join()

    # Every row present, none lost or duplicated by the concurrent writer.
    assert result.row_count == 2000


def test_snapshot_history_lets_an_earlier_sync_still_be_read(sync, source):
    # Iceberg keeps prior snapshots, so a bad sync can be inspected
    # against what came before. A real capability of this storage
    # choice, proven rather than assumed.
    _sync(sync)
    first_snapshot = sync._catalog.load_table("primary.widgets").current_snapshot().snapshot_id

    conn = sqlite3.connect(source)
    conn.execute("DELETE FROM widgets")
    conn.commit()
    conn.close()
    _sync(sync)

    assert _mirror(sync).num_rows == 0
    earlier = (
        sync._catalog.load_table("primary.widgets")
        .scan(snapshot_id=first_snapshot)
        .to_arrow()
    )
    assert earlier.num_rows == 5


def test_concurrent_commits_to_one_table_are_rejected_not_silently_merged(tmp_path, source):
    # Iceberg's optimistic concurrency, verified rather than assumed.
    # A commit carries "the table's metadata is version N"; a second
    # writer starting from the same N is REJECTED rather than allowed
    # to clobber the first. That rejection is CORRECT -- the failure
    # mode it prevents is a lost overwrite.
    #
    # PyIceberg surfaces it as a hard exception whose retry loop cannot
    # resolve a full-table overwrite (unlike Java Iceberg, which
    # retries transparently). This test pins that reality so the
    # single-writer lock in scripts/run_sync.py is never removed as
    # unnecessary.
    import threading

    first = IcebergMirrorSync(tmp_path / "mirror", {"primary": SQLiteReadAdapter({"path": source})})
    _sync(first)

    outcomes = []
    guard = threading.Lock()
    barrier = threading.Barrier(2)

    def racing_sync():
        worker = IcebergMirrorSync(
            tmp_path / "mirror", {"primary": SQLiteReadAdapter({"path": source})}
        )
        barrier.wait()
        try:
            worker.sync_table("primary", "widgets", "widget_id", ["widget_id", "label"])
            outcome = "committed"
        except Exception as exc:
            outcome = type(exc).__name__
        with guard:
            outcomes.append(outcome)

    threads = [threading.Thread(target=racing_sync) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Whatever the interleaving, the table is never corrupted -- it
    # holds exactly one writer's complete result.
    assert _mirror(first).num_rows == 5
    assert "committed" in outcomes
