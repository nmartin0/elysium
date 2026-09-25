"""
A failure building ONE gold table does not end the run (PA001-G5).

THE SHAPE OF THE BUG. `_build_gold` loops over every object type. The
try/except inside it guards READING silver -- "its silver table could
not be read" -- and stops there. The `build_gold(...)` call itself sits
OUTSIDE, so any exception raised while BUILDING propagated out of the
loop, out of _build_gold, and out of run_sync.

WHAT THAT COST, measured by injecting a single failure:

  - every LATER object type was never built at all
  - run_sync RAISED instead of returning a count
  - so _notify_mirror_health() and _evaluate_user_triggers(), which
    run after the gold phase, never ran either

That last one is the worst of the three. The mirror-health alert is
skipped in exactly the situation it exists for.

ONE BAD TYPE IS NOT EVERY TYPE. Each type has its own silver, its own
audit and its own publication. Refusing the others because a
neighbour failed discards work that was fine -- and gold is the ONLY
read path (GOLD-8), so an unbuilt type is an unanswerable question.

WHAT IS NOT CHANGED: a refused build is still counted as a failure and
still reported by name, so a broken type is loud. It is loud per type
rather than fatal to the run.
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

    def published(object_type):
        table = sync.catalog.load_table(f"gold.{object_type}")
        return sorted(n for n in table.refs() if n.startswith("published-"))

    sync.config, sync.published = config, published
    return sync, tmp_path


class TestOneTypeFailing:
    def test_the_run_returns_rather_than_raising(self, deployment, monkeypatch):
        """THE REGRESSION TEST: this used to propagate out of
        run_sync entirely."""
        sync, data_dir = deployment
        real = run_sync.build_gold

        def fail_alpha(catalog, object_type, *a, **k):
            if object_type == "Alpha":
                raise RuntimeError("anything at all (injected)")
            return real(catalog, object_type, *a, **k)
        monkeypatch.setattr(run_sync, "build_gold", fail_alpha)

        refused = run_sync._build_gold(sync, sync.config, data_dir)

        assert refused == 1

    def test_the_OTHER_type_is_still_published(self, deployment, monkeypatch):
        """Gold is the only read path, so an unbuilt type is an
        unanswerable question. One bad neighbour must not cause it."""
        sync, data_dir = deployment
        real = run_sync.build_gold

        def fail_alpha(catalog, object_type, *a, **k):
            if object_type == "Alpha":
                raise RuntimeError("injected")
            return real(catalog, object_type, *a, **k)
        monkeypatch.setattr(run_sync, "build_gold", fail_alpha)

        run_sync._build_gold(sync, sync.config, data_dir)

        assert sync.published("Beta") == ["published-1"]

    def test_the_failure_is_named(self, deployment, monkeypatch, capsys):
        """Loud per type, not silent. An operator needs to know WHICH
        type and WHY."""
        sync, data_dir = deployment
        real = run_sync.build_gold

        def fail_alpha(catalog, object_type, *a, **k):
            if object_type == "Alpha":
                raise RuntimeError("the reason (injected)")
            return real(catalog, object_type, *a, **k)
        monkeypatch.setattr(run_sync, "build_gold", fail_alpha)

        run_sync._build_gold(sync, sync.config, data_dir)

        printed = capsys.readouterr().err
        assert "gold.Alpha" in printed
        assert "the reason (injected)" in printed

    def test_a_failure_on_the_LAST_type_is_reported_too(self, deployment,
                                                         monkeypatch):
        """Order should not decide whether a failure is counted."""
        sync, data_dir = deployment
        real = run_sync.build_gold

        def fail_beta(catalog, object_type, *a, **k):
            if object_type == "Beta":
                raise RuntimeError("injected")
            return real(catalog, object_type, *a, **k)
        monkeypatch.setattr(run_sync, "build_gold", fail_beta)

        assert run_sync._build_gold(sync, sync.config, data_dir) == 1
        assert sync.published("Alpha") == ["published-1"]


class TestTheHealthyPath:
    def test_every_type_is_published(self, deployment):
        sync, data_dir = deployment

        refused = run_sync._build_gold(sync, sync.config, data_dir)

        assert refused == 0
        assert sync.published("Alpha") == ["published-1"]
        assert sync.published("Beta") == ["published-1"]

    def test_an_unreadable_silver_table_is_still_handled(self, deployment,
                                                          monkeypatch):
        """The guard that already existed, kept working. This is the
        case the original try/except was written for."""
        sync, data_dir = deployment
        real = sync.catalog.load_table

        def refuse_alpha(identifier, *a, **k):
            if identifier == "p.alpha":
                raise OSError("silver unreadable (injected)")
            return real(identifier, *a, **k)
        monkeypatch.setattr(sync._catalog, "load_table", refuse_alpha)

        refused = run_sync._build_gold(sync, sync.config, data_dir)

        assert refused == 1
