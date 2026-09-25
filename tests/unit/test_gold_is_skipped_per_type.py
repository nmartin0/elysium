"""
A table that failed to sync stops ITS type, not every type
(PA001-G9).

WHAT WAS WRONG. The gold phase was gated on `if failures == 0`, with
the reasoning that "gold built from a half-synced mirror would publish
a partial picture". The reasoning is right; the SCOPE was wrong. One
unrelated table failing skipped gold for EVERY type -- and SILENTLY.

MEASURED on a real deployment with one of its two tables removed:

    FAILED  primary_sql.customers: ... source column is gone ...
    1/2 tables synced successfully.

and then nothing at all about gold. No line saying it was skipped, no
line saying why.

WHAT THAT COST. Gold is the only read path since GOLD-8, so every type
kept serving its PREVIOUS publication while fresh silver sat unused,
with nothing in the output to suggest it. A deployment answering
yesterday's question today, confidently.

NOW: a type whose OWN tables all synced is built normally. A type
whose table failed is skipped BY NAME, with the reason. Its links are
still audited against the other types' PUBLISHED ids -- the same thing
that happens on any run where a neighbour simply did not change.
"""

import sqlite3
from types import SimpleNamespace

import pytest

import scripts.run_sync as run_sync
from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync

TYPES = {
    "Alpha": {"id_field": "id", "security": {"field": "region"},
               "storage": {"silo": "p", "table": "alpha", "id_column": "id"},
               "fields": {"id": {"type": "data"}, "v": {"type": "data"},
                           "region": {"type": "data"}}},
    "Beta": {"id_field": "id", "security": {"field": "region"},
              "storage": {"silo": "p", "table": "beta", "id_column": "id"},
              "fields": {"id": {"type": "data"}, "v": {"type": "data"},
                          "region": {"type": "data"}}},
}


@pytest.fixture
def deployment(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    for table in ("alpha", "beta"):
        conn.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, v TEXT, region TEXT)")
        conn.execute(f"INSERT INTO {table} VALUES ('x','1','us-west')")
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "m", {"p": SQLiteReadAdapter({"path": source})})
    for table in ("alpha", "beta"):
        sync.sync_table("p", table, "id", ["id", "v", "region"], {})

    config = SimpleNamespace(schema=TYPES, identity_inference=False,
                              retain_publications=30, mirror_storage={})

    def publications(object_type):
        table = sync.catalog.load_table(f"gold.{object_type}")
        return sorted((n for n in table.refs() if n.startswith("published-")),
                       key=lambda n: int(n.rsplit("-", 1)[1]))

    sync.config, sync.publications = config, publications
    return sync, tmp_path


class TestOneTableFailing:
    def test_the_UNAFFECTED_type_is_still_published(self, deployment):
        """THE REGRESSION TEST. Beta's silver is fresh and correct;
        Alpha's table failing must not cost Beta its publication."""
        sync, data_dir = deployment

        run_sync._build_gold(sync, sync.config, data_dir, unsynced={"p.alpha"})

        assert sync.publications("Beta") == ["published-1"]

    def test_the_affected_type_is_skipped(self, deployment):
        sync, data_dir = deployment

        run_sync._build_gold(sync, sync.config, data_dir, unsynced={"p.alpha"})

        assert not sync.catalog.table_exists("gold.Alpha")

    def test_the_skip_is_SAID_OUT_LOUD(self, deployment, capsys):
        """The whole of G9. A silent skip on the only read path means
        the deployment serves yesterday's answer with nothing in the
        output to suggest it."""
        sync, data_dir = deployment

        run_sync._build_gold(sync, sync.config, data_dir, unsynced={"p.alpha"})

        printed = capsys.readouterr().out
        assert "gold.Alpha" in printed
        assert "p.alpha" in printed
        assert "stale" in printed

    def test_it_is_not_counted_as_a_gold_failure(self, deployment):
        """The silver failure that caused it was already counted and
        named; counting it twice would overstate what went wrong."""
        sync, data_dir = deployment

        refused = run_sync._build_gold(sync, sync.config, data_dir,
                                        unsynced={"p.alpha"})

        assert refused == 0

    def test_a_type_is_skipped_on_its_ADDITIONAL_storage_too(self, tmp_path):
        """A fused type spans several tables, and any of them being
        stale makes the whole type stale."""
        source = tmp_path / "s2.db"
        conn = sqlite3.connect(source)
        for table in ("alpha", "extra"):
            conn.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, v TEXT, "
                         f"region TEXT)")
            conn.execute(f"INSERT INTO {table} VALUES ('x','1','us-west')")
        conn.commit()
        conn.close()
        sync = IcebergMirrorSync(tmp_path / "m2",
                                  {"p": SQLiteReadAdapter({"path": source})})
        for table in ("alpha", "extra"):
            sync.sync_table("p", table, "id", ["id", "v", "region"], {})
        types = {"Alpha": {**TYPES["Alpha"],
                            "additional_storage": {
                                "more": {"silo": "p", "table": "extra",
                                          "id_column": "id"}}}}
        config = SimpleNamespace(schema=types, identity_inference=False,
                                  retain_publications=30, mirror_storage={})

        run_sync._build_gold(sync, config, tmp_path, unsynced={"p.extra"})

        assert not sync.catalog.table_exists("gold.Alpha")


class TestNothingFailing:
    def test_every_type_is_published(self, deployment):
        sync, data_dir = deployment

        refused = run_sync._build_gold(sync, sync.config, data_dir, unsynced=set())

        assert refused == 0
        assert sync.publications("Alpha") == ["published-1"]
        assert sync.publications("Beta") == ["published-1"]

    def test_the_default_is_no_skipping(self, deployment):
        """Callers that pass nothing get the old, unfiltered
        behaviour."""
        sync, data_dir = deployment

        run_sync._build_gold(sync, sync.config, data_dir)

        assert sync.publications("Alpha") == ["published-1"]
