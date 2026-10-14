"""Erasure everywhere the mirror copied a person (R13), as the owner
decided it on 2026-10-12: rewritten everywhere, suppressed while the
source still returns them, and re-applied after a restore.

THE CHECK IS THE WAREHOUSE ITSELF, not the catalog's current view:
every Parquet file on disk is opened and searched. "Nothing in the lake
can show them again" is a claim about files -- an older snapshot, a
publication tag or an unreferenced file would each still hold them
while every current read looked clean.
"""

import contextlib
import io

import pyarrow.parquet as pq

from core.mirror.erasure import ErasureRegister, source_key_columns, table_key_columns
from scripts.backup_deployment import backup
from scripts.erase import run as erase
from scripts.restore_deployment import restore
from scripts.run_sync import run_sync

ADA = "cust_001"                 # two transactions: 1 and 2
ADA_EMAIL = "ada.okafor@example.com"


def _quiet(call, *args, **kwargs):
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(io.StringIO()):
        result = call(*args, **kwargs)
    return result, printed.getvalue()


def _files_holding(paths, value: str) -> list[str]:
    """Every Parquet file in the warehouse with `value` in any cell."""
    holding = []
    for parquet in (paths.data_dir / "mirror" / "warehouse").rglob("*.parquet"):
        table = pq.read_table(parquet)
        for column in table.column_names:
            if value in {str(cell) for cell in table.column(column).to_pylist()}:
                holding.append(str(parquet.relative_to(paths.data_dir)))
                break
    return holding


def _erase(paths, write=True):
    return _quiet(erase, "Customer", ADA, "test request", write=write, paths=paths,
                  requested_by="tester")


class TestWhereKeysLive:
    def test_every_layer_and_every_link_is_mapped(self, synced_deployment):
        from core.deployment_loader import load_deployment

        schema = load_deployment(synced_deployment.config_dir).schema

        assert source_key_columns(schema)[("primary_sql", "transactions")] == {
            "transaction_id": {"Transaction"}, "customer_id": {"Customer"}}
        assert table_key_columns(schema, "gold.Transaction") == {
            "transaction_id": {"Transaction"}, "customer_id": {"Customer"}}
        assert table_key_columns(schema, "gold_conflicts.Customer") == {"entity_id": {"Customer"}}


class TestErasing:
    def test_a_dry_run_counts_and_changes_nothing(self, synced_deployment):
        code, printed = _erase(synced_deployment, write=False)

        assert code == 0
        assert "Customer: 1" in printed and "Transaction: 2" in printed
        assert _files_holding(synced_deployment, ADA_EMAIL)

    def test_nothing_on_disk_holds_them_afterwards(self, synced_deployment):
        """THE PROPERTY. Before: bronze, silver, gold and their history
        hold the email. After: no file anywhere does -- and a person who
        was NOT erased is still there."""
        # A rename first, so the changelog and gold's history hold Ada too.
        import sqlite3
        with sqlite3.connect(synced_deployment.data_dir / "dev_fixtures" / "mediator.db") as conn:
            conn.execute("UPDATE customers SET name = 'Ada O.' WHERE customer_id = ?", (ADA,))
        _quiet(run_sync, synced_deployment)
        assert len(_files_holding(synced_deployment, ADA_EMAIL)) > 3

        code, printed = _erase(synced_deployment)

        assert code == 0, printed
        assert _files_holding(synced_deployment, ADA_EMAIL) == []
        assert _files_holding(synced_deployment, ADA) == []
        assert _files_holding(synced_deployment, "cust_002")      # THE CONTROL

    def test_the_register_holds_no_id(self, synced_deployment):
        """A list of who asked to be forgotten is personal data."""
        _erase(synced_deployment)

        raw = (synced_deployment.data_dir / "erasures.db").read_bytes()
        assert ADA.encode() not in raw

    def test_while_the_source_still_returns_them_every_sync_drops_them(self, synced_deployment):
        _erase(synced_deployment)

        _code, printed = _quiet(run_sync, synced_deployment)

        assert "still returned by a source" in printed
        assert _files_holding(synced_deployment, ADA_EMAIL) == []

    def test_once_the_source_erases_them_too_the_register_says_so(self, synced_deployment):
        import sqlite3

        _erase(synced_deployment)
        with sqlite3.connect(synced_deployment.data_dir / "dev_fixtures" / "mediator.db") as conn:
            conn.execute("DELETE FROM transactions WHERE customer_id = ?", (ADA,))
            conn.execute("DELETE FROM customers WHERE customer_id = ?", (ADA,))

        _code, printed = _quiet(run_sync, synced_deployment)

        assert "still returned by a source" not in printed
        assert all(erasure.source_cleared_at for erasure in
                   ErasureRegister(synced_deployment.data_dir / "erasures.db").erasures())


class TestARestore:
    def test_an_older_backup_does_not_bring_them_back(self, synced_deployment, tmp_path):
        """The backup predates the erasure and holds Ada. The register in
        place is kept, every erasure marked unpurged, and the next sync
        rewrites the restored lake."""
        backup(synced_deployment.data_dir, tmp_path / "backup")
        _erase(synced_deployment)

        restored, _ = _quiet(restore, tmp_path / "backup", synced_deployment.data_dir,
                             force=True)
        assert restored["erasures_reapplied"] > 0
        assert _files_holding(synced_deployment, ADA_EMAIL)        # back, for now

        _quiet(run_sync, synced_deployment)

        assert _files_holding(synced_deployment, ADA_EMAIL) == []

    def test_the_register_is_the_newer_one(self, synced_deployment, tmp_path):
        """A register restored from before the erasure would not know of
        it; the one in place is a superset and is the one kept."""
        backup(synced_deployment.data_dir, tmp_path / "backup")
        _erase(synced_deployment)

        _quiet(restore, tmp_path / "backup", synced_deployment.data_dir, force=True)

        assert ErasureRegister(synced_deployment.data_dir / "erasures.db").erasures()



def _memories(paths):
    from core.memory.store import MemoryStore

    return MemoryStore(paths.data_dir / "memories.db")


class TestWhatPeopleRemembered:
    """E-14: a memory is a sentence about one object, so it goes with it."""

    def test_an_erasure_forgets_every_memory_about_them(self, synced_deployment):
        store = _memories(synced_deployment)
        store.add("Customer", ADA, "Disputed two charges.", {}, "someone")
        store.add("Transaction", "1", "Refunded.", {}, "someone")
        store.add("Customer", "cust_002", "Prefers email.", {}, "someone")

        _code, printed = _erase(synced_deployment)

        assert "2 memory(ies)" in printed
        assert store.about("Customer", ADA) == [] and store.about("Transaction", "1") == []
        assert store.about("Customer", "cust_002")                  # THE CONTROL

    def test_a_restore_does_not_bring_them_back(self, synced_deployment, tmp_path):
        store = _memories(synced_deployment)
        store.add("Customer", ADA, "Disputed two charges.", {}, "someone")
        store.add("Customer", "cust_002", "Prefers email.", {}, "someone")
        backup(synced_deployment.data_dir, tmp_path / "backup")
        _erase(synced_deployment)

        _quiet(restore, tmp_path / "backup", synced_deployment.data_dir, force=True)

        assert store.about("Customer", ADA) == []
        assert store.about("Customer", "cust_002")




def test_the_server_will_not_serve_a_lake_with_unapplied_erasures(synced_deployment):
    """After a restore the lake may hold them until the next sync; the
    server refuses to start until then rather than serve them once."""
    import pytest

    from api.app import create_app

    ErasureRegister(synced_deployment.data_dir / "erasures.db").record(
        [("Customer", ADA)], "tester", "test")

    with pytest.raises(RuntimeError, match="run_sync"):
        create_app(synced_deployment)


def test_the_list_says_what_happened_without_an_id(synced_deployment):
    from scripts.erase import list_erasures

    _erase(synced_deployment)
    _code, printed = _quiet(list_erasures, synced_deployment)

    assert "test request" in printed and "tester" in printed and "Transaction" in printed
    assert ADA not in printed


class TestBothReadPathsSuppress:
    """THE SECOND READ PATH (found 14 Oct, by a control that never fired).
    A sync reads the source in batches; when bronze cannot be written it
    reads it again whole, through _read_source_rows. Erased keys are
    dropped on both. The control for R13 was anchored on the fallback
    and so broke a path no test took -- this is the test for it, and the
    control now points at each path separately."""

    def test_the_fallback_read_drops_erased_keys_too(self, tmp_path):
        import sqlite3

        from adapters.sqlite_adapter import SQLiteReadAdapter
        from core.mirror.iceberg_sync import IcebergMirrorSync

        source = tmp_path / "s.db"
        with sqlite3.connect(source) as conn:
            conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT)")
            conn.executemany("INSERT INTO customers VALUES (?, ?)",
                             [("cust_001", "Ada"), ("cust_002", "Ben")])
        adapter = SQLiteReadAdapter({"path": source})
        sync = IcebergMirrorSync(tmp_path / "m", {"p": adapter})

        def key_hash(object_type, value):
            return f"{object_type}:{value}"

        sync.suppression = {("p", "customers"): (
            {"customer_id": {"Customer"}}, key_hash, {"Customer": {"Customer:cust_001"}})}
        sync._current_silo = "p"

        rows = sync._read_source_rows(adapter, "customers", "customer_id",
                                      ["customer_id", "name"])

        assert [row["customer_id"] for row in rows] == ["cust_002"]
        assert sync.erased_still_in_source == {"Customer:cust_001"}
