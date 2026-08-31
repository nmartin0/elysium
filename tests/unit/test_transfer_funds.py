"""
Tests for TransferFunds -- the first REAL, deliberately-authored
MULTI-OBJECT action_type (two sub_writes, both Account), exercised
through the actual apply path (WriteMediator._apply_batch(),
DataMediator._locks_for_objects() with two genuinely different real
locks). Everything up to this point proving the sub_writes/write_log_
batches mechanism -- tests/unit/test_action_types_validation.py,
tests/unit/test_write_log_batches.py, tests/unit/test_confirm_and_
execute_batches.py, tests/unit/test_write_log_resume.py -- used only
synthetic, invented fixtures (Widget/Gadget/Account-in-name-only) to
prove the mechanism's own correctness in isolation, deliberately
before a real, schema-authored, model-invocable action existed to
design against. This file, and tests/integration/test_transfer_
funds_e2e.py (real Ollama, not runnable in every environment), are
that real proof.

Same-type sub_writes (Account -> Account) -- only execute:
TransferFunds is required by RBAC, not any write:<Type>.<field> grant;
the cross-TYPE RBAC path is already proven by tests/unit/test_write_
mediator.py's own synthetic fixtures, not this file's job to prove
again.

security: {field: region} directly on Account here, NOT a via_field
chain -- the real tests/integration/fixtures/ontology_schema.yaml
version uses via_field: owner_customer_id (a real security CHAIN,
already thoroughly proven by tests/unit/test_cross_silo_links.py and
this project's own MDO/cross-silo e2e tests). This file's own job is
narrower: prove the MULTI-OBJECT mechanism itself, not re-prove an
unrelated, already-proven MAC feature -- a direct field keeps that
one variable isolated, same discipline test_named_actions.py's own
Ticket fixture already uses.

henry: region us-west, accountant role (execute:TransferFunds + read)
nobody: region us-west, NO role -- RBAC denial test
wrong_region: region us-east, accountant role -- MAC denial test,
              proving action-level RBAC doesn't bypass MAC
"""

import sqlite3

import pytest

from core.deployment_loader import _build_adapters
from core.intermediate_layer.audit import AuditLog
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLog
from core.ontology.write_mediator import WriteMediator

TEST_SCHEMA = {
    "Account": {
        "storage": {"silo": "primary", "table": "accounts", "id_column": "account_id"},
        "id_field": "account_id",
        "security": {"field": "region"},
        "fields": {
            "region": {"type": "data"},
            "balance": {"type": "data"},
        },
    },
}

TEST_ACTION_TYPES = {
    "TransferFunds": {
        "affected_object_types": ["Account"],
        "parameters": {
            "from_account_id": {"type": "object_reference", "object_type": "Account", "required": True},
            "to_account_id": {"type": "object_reference", "object_type": "Account", "required": True},
            "new_from_balance": {"type": "number", "required": True},
            "new_to_balance": {"type": "number", "required": True},
        },
        "sub_writes": [
            {
                "object_type": "Account", "object_id": "parameter.from_account_id", "operation": "update",
                "mutations": [{"set": {"property": "balance", "value": "parameter.new_from_balance"}}],
            },
            {
                "object_type": "Account", "object_id": "parameter.to_account_id", "operation": "update",
                "mutations": [{"set": {"property": "balance", "value": "parameter.new_to_balance"}}],
            },
        ],
    },
}

TEST_ROLES = {
    "accountant": {"allowed_actions": [
        "execute:TransferFunds", "read:Account", "read:Account.account_id", "read:Account.balance",
    ]},
}

TEST_USERS = {
    "henry": {"region": "us-west", "role": "accountant"},
    "nobody": {"region": "us-west"},
    "wrong_region": {"region": "us-east", "role": "accountant"},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "region")


@pytest.fixture
def wm_and_log(tmp_path, isolated_audit_log):
    db = tmp_path / "a.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE accounts (account_id TEXT PRIMARY KEY, region TEXT, balance REAL);
        INSERT INTO accounts VALUES ('acc_checking', 'us-west', 500.0);
        INSERT INTO accounts VALUES ('acc_savings', 'us-west', 1000.0);
    """)
    conn.commit()
    conn.close()

    adapters = _build_adapters({"primary": {"adapter": "sqlite", "connection": {"path": db}}})
    write_log = WriteLog(tmp_path / "write_log.db")
    audit_log = AuditLog(isolated_audit_log / "audit.log")
    mediator = DataMediator(TEST_SCHEMA, adapters, {"Account": "primary"}, TEST_ROLES,
                             write_log=write_log, audit_log=audit_log)
    write_mediator = WriteMediator(mediator, TEST_ROLES, TEST_ACTION_TYPES)
    return write_mediator, write_log


def _propose_transfer(write_mediator, user_id="henry", from_id="acc_checking", to_id="acc_savings",
                       new_from=450.0, new_to=1050.0):
    return write_mediator.propose_action(_record(user_id), "TransferFunds", {
        "from_account_id": from_id, "to_account_id": to_id,
        "new_from_balance": new_from, "new_to_balance": new_to,
    })


def test_valid_transfer_succeeds_end_to_end(wm_and_log):
    write_mediator, _ = wm_and_log
    henry = _record("henry")
    pending = _propose_transfer(write_mediator)

    assert len(pending.sub_writes) == 2
    assert {sw.object_id for sw in pending.sub_writes} == {"acc_checking", "acc_savings"}

    outcome = write_mediator.confirm_and_execute(pending, approved=True)

    # object_ids in the SAME order sub_writes were declared -- list
    # order, not sorted-lock-acquisition order (see write_mediator.py's
    # own docstring on why these are two genuinely different orderings).
    assert outcome == {"status": "written", "object_ids": ["acc_checking", "acc_savings"]}

    # The REAL database, read back independently of the write path --
    # BOTH accounts, not just one, proving the multi-sub-write apply
    # loop genuinely touched both real rows.
    assert write_mediator.mediator.get_field(henry, "Account", "acc_checking", "balance") == 450.0
    assert write_mediator.mediator.get_field(henry, "Account", "acc_savings", "balance") == 1050.0


def test_rejected_transfer_leaves_both_accounts_unchanged(wm_and_log):
    write_mediator, _ = wm_and_log
    henry = _record("henry")
    pending = _propose_transfer(write_mediator)

    outcome = write_mediator.confirm_and_execute(pending, approved=False)

    assert outcome is None
    assert write_mediator.mediator.get_field(henry, "Account", "acc_checking", "balance") == 500.0
    assert write_mediator.mediator.get_field(henry, "Account", "acc_savings", "balance") == 1000.0


def test_rbac_denial_without_execute_grant(wm_and_log):
    write_mediator, _ = wm_and_log
    with pytest.raises(PermissionError):
        _propose_transfer(write_mediator, user_id="nobody")


def test_mac_denial_for_wrong_region(wm_and_log):
    # wrong_region HAS execute:TransferFunds -- proves action-level
    # RBAC alone can never bypass MAC; both accounts are region
    # us-west, wrong_region's own security_value is us-east.
    write_mediator, _ = wm_and_log
    with pytest.raises(PermissionError):
        _propose_transfer(write_mediator, user_id="wrong_region")


def test_transfer_to_the_same_account_twice_is_rejected(wm_and_log):
    # THE resolved-id duplicate check (WriteMediator.propose_action()'s
    # own "seen_object_refs" logic) -- found, while building this file,
    # to have NO existing test coverage anywhere in this project, only
    # the WEAKER, load-time structural check (core/ontology/action_
    # types.py) which can never catch this case at all: from_account_id
    # and to_account_id are DIFFERENT parameter expressions, so the
    # schema-load check sees no problem -- only real, resolved values
    # (both "acc_checking" here) reveal the genuine collision.
    write_mediator, _ = wm_and_log
    with pytest.raises(ValueError, match="both resolved to the identical Account 'acc_checking'"):
        _propose_transfer(write_mediator, from_id="acc_checking", to_id="acc_checking")


def test_transfer_batch_is_logged_with_both_sub_writes(wm_and_log, monkeypatch):
    # THE write_log_batches mechanism itself (built and proven earlier
    # only against synthetic Account/Widget-in-name-only fixtures --
    # see tests/unit/test_write_log_batches.py, tests/unit/test_
    # confirm_and_execute_batches.py), now exercised by a REAL action a
    # real model can actually invoke. Observed mid-apply via the same
    # spy technique test_confirm_and_execute_batches.py's own test_the_
    # per_object_row_is_correctly_batch_owned_mid_apply established.
    write_mediator, write_log = wm_and_log
    pending = _propose_transfer(write_mediator)

    observed = {}
    original_write_fields = write_mediator.mediator.adapters["primary"].write_fields

    def spy_write_fields(*args, **kwargs):
        if "pending_batches" not in observed:
            batches = write_log.get_pending_batches()
            if batches:
                observed["pending_batches"] = batches
        return original_write_fields(*args, **kwargs)

    monkeypatch.setattr(write_mediator.mediator.adapters["primary"], "write_fields", spy_write_fields)
    write_mediator.confirm_and_execute(pending, approved=True)

    assert len(observed["pending_batches"]) == 1
    batch = observed["pending_batches"][0]
    assert len(batch["sub_writes"]) == 2
    assert {sw["object_id"] for sw in batch["sub_writes"]} == {"acc_checking", "acc_savings"}
    # Resolved once, and applied -- no batch left pending afterward.
    assert write_log.get_pending_batches() == []


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# CONTEXT: this file exists to close a long-tracked item -- a real,
# deliberately-authored multi-object action_type, proving the whole
# sub_writes/write_log_batches mechanism end to end, not just against
# synthetic fixtures. See core/ontology/write_mediator.py's own AI-
# notes for the fuller history, and tests/integration/test_transfer_
# funds_e2e.py (real Ollama, this file's own direct counterpart) for
# the real-model half of the proof.
#
# DEFERRED (known, intentional, not yet built):
# - No dedicated multi-THREADED concurrency test here -- every test in
#   this file runs single-threaded; the sorted-order locking mechanism
#   is exercised structurally (two real locks acquired, in order) but
#   never under genuine concurrent contention. See core/ontology/
#   mediator.py's own AI-notes for where that separate, still-open
#   item stands.
# - test_transfer_to_the_same_account_twice_is_rejected is the FIRST
#   test anywhere in this project for the resolved-id duplicate check
#   in WriteMediator.propose_action() -- found, while building this
#   file, to have had NO coverage at all before now. Worth checking
#   whether a similarly uncovered gap exists elsewhere in propose_
#   action() if this file is ever revisited for a second real action.
