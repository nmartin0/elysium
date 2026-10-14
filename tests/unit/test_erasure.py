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


def _notes(paths):
    from core.artifact_store import ArtifactStore, note_kind

    store = ArtifactStore(paths.data_dir / "artifacts.db")

    def write(object_type, object_id, text):
        store.save(note_kind(object_type, object_id), "note", "someone", {"text": text},
                   shared_role="customer_service")

    def about(object_type, object_id):
        return store.list_for("someone", "customer_service", kind=note_kind(object_type, object_id))

    return write, about


class TestWhatPeopleWroteAboutThem:
    """Decided 14 Oct: a note about an erased object goes with it."""

    def test_an_erasure_deletes_every_note_about_them(self, synced_deployment):
        write, about = _notes(synced_deployment)
        write("Customer", ADA, "Fee waived after the flood.")
        write("Transaction", "1", "Disputed.")
        write("Customer", "cust_002", "Prefers email.")

        _code, printed = _erase(synced_deployment)

        assert "2 notes" in printed
        assert about("Customer", ADA) == [] and about("Transaction", "1") == []
        assert about("Customer", "cust_002")                       # THE CONTROL

    def test_a_restore_does_not_bring_them_back(self, synced_deployment, tmp_path):
        write, about = _notes(synced_deployment)
        write("Customer", ADA, "Fee waived after the flood.")
        write("Customer", "cust_002", "Prefers email.")
        backup(synced_deployment.data_dir, tmp_path / "backup")
        _erase(synced_deployment)

        _quiet(restore, tmp_path / "backup", synced_deployment.data_dir, force=True)

        assert about("Customer", ADA) == []
        assert about("Customer", "cust_002")


class TestWhatPeopleRemembered:
    """E-14: a memory is a sentence about one object, so it goes with it."""

    def test_an_erasure_forgets_every_memory_about_them(self, synced_deployment):
        store = _memories(synced_deployment)
        store.add("Customer", ADA, "Disputed two charges.", {}, "someone")
        store.add("Transaction", "1", "Refunded.", {}, "someone")
        store.add("Customer", "cust_002", "Prefers email.", {}, "someone")

        _code, printed = _erase(synced_deployment)

        assert "2 memories" in printed
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




def _pending(object_type, object_id, *, user="asker", parameters=None):
    from datetime import UTC, datetime

    from core.intermediate_layer.auth import UserRecord
    from core.ontology.write_mediator import PendingWrite, SubWrite

    return PendingWrite(
        sub_writes=(SubWrite(object_type, object_id, "update", {"category": "x"}),),
        user_id=user, description=f"Recategorize {object_type} {object_id}",
        action_type_name="Recategorize", origin="agent", proposed_at=datetime.now(UTC),
        proposed_under_generation=1, parameters=parameters or {},
        proposer=UserRecord(user_id=user, role_name="customer_service", security_value="us-west"))


def _queue(paths):
    from core.intermediate_layer.audit import AuditLog
    from core.pending_write_persistence import PendingWritePersistence
    from core.pending_write_store import PendingWriteStore

    return PendingWriteStore(audit_log=AuditLog(paths.log_dir / "audit.log"),
                             persistence=PendingWritePersistence(
                                 paths.data_dir / "pending_writes.db"))


class TestEverythingButTheAuditLog:
    """Decided 14 Oct: frozen sets, the write log, waiting writes, paused
    questions and answer notifications forget them too. The audit log
    keeps that an erasure happened, and not of whom."""

    def test_a_frozen_set_loses_them_and_the_criteria_that_found_them(self, synced_deployment):
        from core.frozen_sets import FrozenSetStore

        store = FrozenSetStore(synced_deployment.data_dir / "frozen_sets.db")
        mixed = store.freeze("someone", "Ada and Bram", "Customer", [ADA, "cust_002"],
                             origin={"filters": [{"field": "name", "operator": "in",
                                                  "value": ["Ada Okafor", "Bram Feldman"]}]})
        other = store.freeze("someone", "Chidi", "Customer", ["cust_003"],
                             origin={"filters": [{"field": "region", "value": "us-east"}]})
        named = store.freeze("someone", "Ada's", "Transaction", ["5"],
                             origin={"filters": [{"field": "customer_id", "value": ADA}]})

        _erase(synced_deployment)

        assert store.get("someone", mixed).member_ids == ["cust_002"]
        assert store.get("someone", mixed).origin == {}
        assert store.get("someone", named).origin == {}        # an id in the criteria
        assert store.get("someone", named).member_ids == ["5"]  # not Ada's transaction
        assert store.get("someone", other).origin              # THE CONTROL

    def test_the_write_log_forgets_their_edits_and_keeps_the_rest(self, synced_deployment):
        from core.ontology.write_log import WriteLogWriter

        log = WriteLogWriter(synced_deployment.data_dir / "write_log.db")
        batch = log.log_pending_batch(
            [{"object_type": "Transaction", "object_id": "1"},
             {"object_type": "Transaction", "object_id": "5"}], "someone", "Ada's and Chidi's")
        log.log_pending_update("Transaction", "1", {"category": "x"}, {}, "someone",
                               "Ada's and Chidi's", batch_id=batch)
        log.log_pending_update("Transaction", "5", {"category": "x"}, {}, "someone",
                               "Ada's and Chidi's", batch_id=batch)
        log.log_pending_update("Customer", ADA, {"email": "x"}, {}, "someone", "Ada's email")
        log.log_pending_update("Customer", "cust_002", {"email": "y"}, {}, "someone", "Bram's")

        _erase(synced_deployment)

        assert log.get_pending_changes("Customer", ADA) is None
        assert log.get_pending_changes("Transaction", "1") is None
        assert log.get_pending_changes("Customer", "cust_002") == {"email": "y"}  # CONTROL
        [kept] = [b for b in log.get_pending_batches() if b["id"] == batch]
        assert [sub["object_id"] for sub in kept["sub_writes"]] == ["5"]
        assert "Ada" not in kept["description"]

    def test_a_waiting_write_about_them_is_withdrawn_and_audited_without_them(
            self, synced_deployment):
        queue = _queue(synced_deployment)
        about_ada = queue.store(_pending("Transaction", "1"))
        names_ada = queue.store(_pending("Transaction", "5", parameters={"customers": [ADA]}))
        other = queue.store(_pending("Transaction", "5", user="other"))

        _erase(synced_deployment)

        waiting = {write_id for write_id, _ in queue.awaiting(lambda pending: True)}
        assert waiting == {other}
        log = (synced_deployment.log_dir / "audit.log").read_text()
        assert about_ada in log and names_ada in log and '"write_withdrawn_erased"' in log
        assert ADA not in log.split('"write_withdrawn_erased"', 1)[1]

    def test_a_paused_question_that_read_them_is_dropped_and_its_asker_told(
            self, synced_deployment):
        from core.notifications import NotificationStore
        from core.paused_queries import PausedQueryStore

        questions = PausedQueryStore(synced_deployment.data_dir / "paused_queries.db")
        questions.save("w1", "asker", "Ada's email, and recategorize 5?",
                       [{"step": "search_object", "object_type": "Customer",
                         "filter": {"name": "Ada Okafor"}, "result": [ADA]}], 2)
        questions.save("w2", "other", "Chidi's region?",
                       [{"step": "get_field", "object_type": "Customer",
                         "object_id": "cust_003", "field_name": "region", "result": "us-east"}], 1)

        _erase(synced_deployment)

        assert questions.take("w1") is None
        assert questions.take("w2") is not None                   # THE CONTROL
        notices = NotificationStore(synced_deployment.data_dir / "notifications.db")
        [told] = notices.for_user("asker")
        assert "erased" in told.summary and "Ada" not in told.summary

    def test_an_answer_built_from_them_is_forgotten(self, synced_deployment):
        from core.notifications import NotificationStore

        notices = NotificationStore(synced_deployment.data_dir / "notifications.db")
        notices.notify("asker", "query_answer", "Answer to: Ada's email?",
                       detail="ada.okafor@example.com", subjects=[("Customer", ADA)])
        notices.notify("asker", "query_answer", "Answer to: Chidi?", detail="us-east",
                       subjects=[("Customer", "cust_003")])

        _erase(synced_deployment)

        assert [n.summary for n in notices.for_user("asker")] == ["Answer to: Chidi?"]

    def test_a_merge_proposal_naming_them_goes_with_its_decisions(self, synced_deployment):
        from core.identity_decisions import APPROVED, MergeDecisionStore

        store = MergeDecisionStore(synced_deployment.data_dir / "identity_decisions.db")
        theirs = store.propose("Customer", f"primary:{ADA}", "crm:77", 0.9)
        store.decide(theirs, APPROVED, "reviewer")
        other = store.propose("Customer", "primary:cust_002", "crm:78", 0.9)

        _erase(synced_deployment)

        assert [p.proposal_id for p in store.proposals()] == [other]

    def test_the_audit_log_says_an_erasure_happened_and_not_of_whom(self, synced_deployment):
        import json

        _code, printed = _erase(synced_deployment)

        entries = [json.loads(line) for line in
                   (synced_deployment.log_dir / "audit.log").read_text().splitlines()]
        [erasure] = [e for e in entries if e.get("stage") == "erasure"]
        assert erasure["requested_by"] == "tester"
        assert erasure["object_types"] == {"Customer": 1, "Transaction": 2}
        assert ADA not in json.dumps(erasure) and "Okafor" not in json.dumps(erasure)

    def test_a_restore_forgets_them_in_every_store_again(self, synced_deployment, tmp_path):
        from core.frozen_sets import FrozenSetStore

        store = FrozenSetStore(synced_deployment.data_dir / "frozen_sets.db")
        set_id = store.freeze("someone", "Ada and Bram", "Customer", [ADA, "cust_002"])
        queue = _queue(synced_deployment)
        queue.store(_pending("Transaction", "1"))
        backup(synced_deployment.data_dir, tmp_path / "backup")
        _erase(synced_deployment)

        _quiet(restore, tmp_path / "backup", synced_deployment.data_dir, force=True)

        assert store.get("someone", set_id).member_ids == ["cust_002"]
        assert _queue(synced_deployment).awaiting(lambda pending: True) == []


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
