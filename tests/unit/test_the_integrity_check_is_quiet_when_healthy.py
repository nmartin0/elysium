"""
The integrity check reports nothing on a healthy deployment
(PA001-I1, PA001-F6.4).

WHAT IT DID. `_split_tables` sorted every table that was not
`bronze_*` or `changelog_*` into SILVER, and the check then reported
each one as a silver table with no bronze twin:

    gold.Thing: no bronze table, so its rows cannot be traced back to
    what the source said

Gold is DERIVED from silver and has no bronze twin BY DESIGN. Neither
does gold_history. Neither does a quarantine table. So a deployment
doing exactly what it should be doing reported one problem per gold
table, every time anyone looked.

WHY THIS MATTERS MORE THAN ITS MEDIUM RATING, in the audit's own
words: "a check that always reports problems on a healthy deployment
trains operators to ignore it, which is how F1 and F2 go unnoticed".
F1 and F2 were real -- a source column silently freezing the pipeline,
and a bronze failure serving stale data -- and that is exactly how
they hid. Behind a check nobody believed.

AND THE LAYERS ARE NAMED CONSTANTS NOW (PA001-F6.4). They were
hand-written prefixes in this file, so renaming a namespace anywhere
else would silently re-sort its tables into silver and bring the false
alarm straight back.

WHAT IS DELIBERATELY UNCHANGED: a SILVER table with no bronze is still
a problem, and still reported. The check was not wrong about what it
was looking for -- only about what it was looking at.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.gold import build_gold
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.integrity import check_mirror

TYPE = {
    "id_field": "id", "security": {"field": "region"},
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
        build_gold(sync.catalog, "Thing", TYPE,
                    sync.catalog.load_table("p.t").scan().to_arrow())

    def change(value):
        conn = sqlite3.connect(source)
        conn.execute("UPDATE t SET v=? WHERE id='a'", (value,))
        conn.commit()
        conn.close()

    def resync():
        sync.sync_table("p", "t", "id", ["id", "v", "region"], {})

    sync.publish, sync.change, sync.resync = publish, change, resync
    return sync


class TestAHealthyDeploymentIsSilent:
    def test_after_a_sync_and_a_publication(self, deployment):
        """THE REGRESSION TEST. This reported one problem per gold
        table."""
        deployment.publish()

        assert check_mirror(deployment.catalog).problems == []

    def test_after_several_publications(self, deployment):
        """gold_history appears on the SECOND publication, and it has
        no bronze twin either."""
        deployment.publish()
        deployment.change("two")
        deployment.resync()
        deployment.publish()

        report = check_mirror(deployment.catalog)
        namespaces = {n[0] for n in deployment.catalog.list_namespaces()}
        assert "gold_history" in namespaces, "the fixture did not exercise history"
        assert report.problems == []

    def test_with_a_quarantine_table(self, deployment, tmp_path):
        """A quarantined row is a deliberate outcome, not a fault, and
        its table has no bronze twin."""
        source = tmp_path / "q.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE q (id TEXT, v TEXT, region TEXT)")
        conn.executemany("INSERT INTO q VALUES (?,?,?)",
                         [("good", "0", "us-west"),
                          ("dup", "1", "us-west"), ("dup", "2", "us-west")])
        conn.commit()
        conn.close()
        sync = IcebergMirrorSync(tmp_path / "qm",
                                  {"p": SQLiteReadAdapter({"path": source})})
        sync.sync_table("p", "q", "id", ["id", "v", "region"], {})

        namespaces = {n[0] for n in sync.catalog.list_namespaces()}
        if not any(n.startswith("quarantine_") for n in namespaces):
            pytest.skip("this fixture produced no quarantine table")
        assert check_mirror(sync.catalog).problems == []


class TestARealProblemIsStillReported:
    def test_a_silver_table_with_no_bronze(self, deployment):
        """The check was not wrong about what it was looking FOR."""
        deployment.publish()
        deployment.catalog.drop_table("bronze_p.t")

        problems = check_mirror(deployment.catalog).problems

        assert any("p.t" in p and "no bronze" in p for p in problems)

    def test_and_it_names_the_silver_table_not_a_gold_one(self, deployment):
        deployment.publish()
        deployment.catalog.drop_table("bronze_p.t")

        problems = check_mirror(deployment.catalog).problems

        assert not any("gold." in p for p in problems)


class TestARowCountMismatchIsStillReported:
    """WRITTEN BECAUSE A CONTROL PROVED NOTHING. The tests above drop
    the bronze TABLE, which a different check catches, so
    short-circuiting the row-count comparison changed nothing. This
    exercises the comparison itself."""

    def test_silver_serving_fewer_rows_than_bronze(self, deployment):
        """Rows missing for no declared reason -- not quarantined, not
        a vanished table. That is the fault this check exists for."""
        deployment.publish()
        silver = deployment.catalog.load_table("p.t")
        one_row = silver.scan().to_arrow().slice(0, 1)
        silver.overwrite(one_row)

        problems = check_mirror(deployment.catalog).problems

        assert any("serving 1 rows against 2 fetched" in p for p in problems)

    def test_quarantine_does_not_hide_a_real_shortfall(self, tmp_path):
        """The fix must not become a blanket excuse: quarantine
        accounts for the rows it HOLDS, and no more."""
        source = tmp_path / "m.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE q (id TEXT, v TEXT, region TEXT)")
        conn.executemany("INSERT INTO q VALUES (?,?,?)",
                         [("good", "0", "us-west"), ("also", "9", "us-west"),
                          ("dup", "1", "us-west"), ("dup", "2", "us-west")])
        conn.commit()
        conn.close()
        sync = IcebergMirrorSync(tmp_path / "mm",
                                  {"p": SQLiteReadAdapter({"path": source})})
        sync.sync_table("p", "q", "id", ["id", "v", "region"], {})
        silver = sync.catalog.load_table("p.q")
        silver.overwrite(silver.scan().to_arrow().slice(0, 1))

        problems = check_mirror(sync.catalog).problems

        assert any("p.q" in p and "serving" in p for p in problems)


class TestTheLayersAreNamedConstants:
    def test_the_namespaces_come_from_their_own_modules(self):
        """PA001-F6.4. Hand-written prefixes here would drift the
        moment a namespace was renamed elsewhere, and the symptom
        would be this same false alarm returning quietly."""
        from core.mirror.gold_history import CHANGELOG_NAMESPACE
        from core.mirror.integrity import NON_SOURCE_NAMESPACES
        from core.mirror.quarantine_report import QUARANTINE_PREFIX
        from core.ontology.gold_view import GOLD_NAMESPACE

        assert GOLD_NAMESPACE in NON_SOURCE_NAMESPACES
        assert CHANGELOG_NAMESPACE in NON_SOURCE_NAMESPACES
        assert QUARANTINE_PREFIX in NON_SOURCE_NAMESPACES
