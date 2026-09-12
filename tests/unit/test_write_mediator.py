"""
Tests for core/ontology/write_mediator.py's propose_action() -- the
highest-stakes new code in this project, so this gets real, dedicated
coverage. Migrated from propose_write() (action-types-redesign branch,
migration pass) -- propose_write() itself is removed once every real
caller has moved to propose_action(), matching Palantir's own actions-
only model (edits via other means are locked down by default and not
recommended for new usage, per their own docs, verified directly).

RBAC granularity moves from FIELD-level to ACTION-level: there is no
"multi-field all-or-nothing" concept anymore, since a named action's
mutations are declared once, at schema-authoring time, not assembled
per-call from field grants -- the original test_propose_write_multi_
field_is_all_or_nothing has no meaningful analog here and is dropped,
not migrated. Its actual INTENT (RBAC is genuinely granular, not just
"any grant on this type unlocks everything") is preserved instead by
dave's role: execute:RenameAuthor but NOT execute:CreateAuthor.

alice: org-a, role=editor       -- execute:RenameAuthor, execute:CreateAuthor
bob:   org-b, role=editor       -- different org -- MAC boundary test
carol: org-a, NO role           -- same org as alice -- RBAC-only denial test
dave:  org-a, role=rename_only  -- execute:RenameAuthor but NOT execute:CreateAuthor
"""

from dataclasses import FrozenInstanceError

import pytest

from adapters.sqlite_adapter import SQLiteWriteAdapter
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLogWriter
from core.ontology.write_mediator import WriteMediator

TEST_USERS = {
    "alice": {"org_id": "org-a", "role": "editor"},
    "bob": {"org_id": "org-b", "role": "editor"},
    "carol": {"org_id": "org-a"},  # deliberately no role
    "dave": {"org_id": "org-a", "role": "rename_only"},
    "erin": {"org_id": "org-a", "role": "process_auditor"},
}

TEST_ROLES = {
    "editor": {"allowed_actions": [
        "read:Author", "read:Author.name", "execute:RenameAuthor", "execute:CreateAuthor",
    ]},
    "rename_only": {"allowed_actions": ["read:Author", "execute:RenameAuthor"]},
    # discover:action_types, and DELIBERATELY no execute: grant at
    # all -- proves the two axes are genuinely separate (see
    # visible_action_types()'s own docstring for the full reasoning).
    "process_auditor": {"allowed_actions": ["discover:action_types"]},
}

TEST_ACTION_TYPES = {
    "RenameAuthor": {
        "affected_object_types": ["Author"],
        "parameters": {
            "author_id": {"type": "object_reference", "object_type": "Author", "required": True},
            "new_name": {"type": "string", "required": True},
        },
        "sub_writes": [{
            "object_type": "Author",
            "object_id": "parameter.author_id",
            "operation": "update",
            "mutations": [{"set": {"property": "name", "value": "parameter.new_name"}}],
        }],
    },
    "CreateAuthor": {
        "affected_object_types": ["Author"],
        "parameters": {
            "author_id": {"type": "object_reference", "object_type": "Author", "required": True},
            "name": {"type": "string", "required": True},
        },
        "sub_writes": [{
            "object_type": "Author",
            "object_id": "parameter.author_id",
            "operation": "create",
            "mutations": [
                {"set": {"property": "author_id", "value": "parameter.author_id"}},
                {"set": {"property": "name", "value": "parameter.name"}},
                # "user.security_value" -- the ACTING user's own org_id,
                # substituted automatically. Discovered as a genuinely
                # necessary, previously-missing mechanism while building
                # THIS test: without it, a create action's mutations had
                # no safe way to populate the security field at all -- a
                # real NOT NULL constraint failure, not a hypothetical.
                {"set": {"property": "org_id", "value": "user.security_value"}},
            ],
        }],
    },
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "org_id")


@pytest.fixture
def wm(test_db_path, test_schema, tmp_path) -> WriteMediator:
    adapter = SQLiteWriteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["storage"]["silo"] for object_type, type_def in test_schema.items()}
    write_log = WriteLogWriter(tmp_path / "write_log.db")
    mediator = DataMediator(test_schema, {"test_silo": adapter}, silo_for_type, TEST_ROLES, write_log=write_log)
    return WriteMediator(mediator, {"test_silo": adapter}, TEST_ROLES, TEST_ACTION_TYPES, generation=1)


def test_visible_action_types_without_discover_grant_shows_only_executable_actions(wm):
    # alice (editor) has execute: for BOTH RenameAuthor and
    # CreateAuthor -- unchanged, existing behavior.
    assert set(wm.visible_action_types(_record("alice")).keys()) == {"RenameAuthor", "CreateAuthor"}


def test_visible_action_types_without_discover_grant_and_partial_execute_shows_only_that_one(wm):
    # dave (rename_only) has execute:RenameAuthor but NOT
    # execute:CreateAuthor -- proves the existing, execute:-filtered
    # path is genuinely unaffected by this addition.
    assert set(wm.visible_action_types(_record("dave")).keys()) == {"RenameAuthor"}


def test_visible_action_types_no_role_shows_nothing(wm):
    assert wm.visible_action_types(_record("carol")) == {}


def test_visible_action_types_with_discover_grant_shows_the_whole_catalog(wm):
    # erin (process_auditor) holds discover:action_types and
    # DELIBERATELY no execute: grant at all -- still sees BOTH real
    # action types, proving discovery is genuinely independent of any
    # execute: grant, not just a superset built from executable ones.
    result = wm.visible_action_types(_record("erin"))
    assert set(result.keys()) == {"RenameAuthor", "CreateAuthor"}
    assert result["RenameAuthor"] == TEST_ACTION_TYPES["RenameAuthor"]


def test_discover_grant_alone_does_not_authorize_invoking_anything(wm):
    # THE real security proof: erin can SEE RenameAuthor's full shape
    # (previous test) but propose_action() itself -- the actual,
    # unchanged authorization gate -- still, correctly, refuses to let
    # her invoke it. Discovery and execution are genuinely separate;
    # this grant alone unlocks neither.
    with pytest.raises(PermissionError):
        wm.propose_action(
            _record("erin"), "RenameAuthor", {"author_id": "auth_001", "new_name": "Erin's Edit"}, origin="human",
        )


def test_propose_action_denied_without_role_rbac(wm):
    with pytest.raises(PermissionError):
        wm.propose_action(
            _record("carol"), "RenameAuthor", {"author_id": "auth_001", "new_name": "Someone Else"}, origin="human",
        )


def test_propose_action_denied_cross_org_even_with_role_granted_mac(wm):
    with pytest.raises(PermissionError):
        wm.propose_action(
            _record("bob"), "RenameAuthor", {"author_id": "auth_001", "new_name": "Hacked"}, origin="human",
        )


def test_propose_action_denied_for_ungranted_action_even_with_a_different_action_granted(wm):
    # dave has execute:RenameAuthor but NOT execute:CreateAuthor -- the
    # ACTION-level analog of the original field-level granularity
    # test: one grant on this object type does not unlock every
    # action that happens to touch it.
    with pytest.raises(PermissionError):
        wm.propose_action(_record("dave"), "CreateAuthor", {"name": "New Author"}, origin="human")


def test_propose_action_succeeds_for_own_org_object(wm):
    pending = wm.propose_action(
        _record("alice"), "RenameAuthor", {"author_id": "auth_001", "new_name": "Ada L."}, origin="human",
    )
    assert pending.sub_writes[0].object_type == "Author"
    assert pending.user_id == "alice"
    assert pending.sub_writes[0].changes == {"name": "Ada L."}


def test_pending_write_is_immutable(wm):
    # Both levels, deliberately -- PendingWrite AND each of its own
    # SubWrite entries are separately frozen dataclasses now (see
    # PendingWrite's own docstring for why the shape split into two).
    pending = wm.propose_action(
        _record("alice"), "RenameAuthor", {"author_id": "auth_001", "new_name": "Ada L."}, origin="human",
    )
    with pytest.raises(FrozenInstanceError):
        pending.sub_writes = ()
    with pytest.raises(FrozenInstanceError):
        pending.sub_writes[0].changes = {"name": "TAMPERED"}


def test_rejected_action_does_not_touch_database(wm):
    pending = wm.propose_action(
        _record("alice"), "RenameAuthor",
        {"author_id": "auth_001", "new_name": "Should Not Apply"}, origin="human",
    )
    result = wm.confirm_and_execute(pending, approved=False)
    assert result is None

    real_value = wm.mediator.get_field(_record("alice"), "Author", "auth_001", "name")
    assert real_value == "Ada Lovelace"


def test_approved_action_actually_updates_the_database(wm):
    pending = wm.propose_action(
        _record("alice"), "RenameAuthor",
        {"author_id": "auth_001", "new_name": "Ada, Countess of Lovelace"}, origin="human",
    )
    result = wm.confirm_and_execute(pending, approved=True)
    assert result == {"status": "written", "object_ids": ["auth_001"]}

    real_value = wm.mediator.get_field(_record("alice"), "Author", "auth_001", "name")
    assert real_value == "Ada, Countess of Lovelace"


def test_approved_create_action_actually_creates_a_new_row(wm):
    # A genuinely NEW piece of coverage the original propose_write()
    # file never had -- a successful "create" operation actually
    # reaching the database, not just the denial case above. Also
    # surfaced a real, pre-existing limitation along the way: Author's
    # author_id is a TEXT primary key, not an integer autoincrement
    # column, so create_object()'s lastrowid fallback can't produce a
    # meaningful ID at all unless the action's own mutations supply
    # one explicitly -- not specific to named actions, just the first
    # time anything actually created an Author through to completion.
    pending = wm.propose_action(
        _record("alice"), "CreateAuthor", {"author_id": "auth_003", "name": "Grace Hopper"}, origin="human")
    assert pending.sub_writes[0].operation == "create"

    result = wm.confirm_and_execute(pending, approved=True)
    assert result == {"status": "written", "object_ids": ["auth_003"]}

    real_value = wm.mediator.get_field(_record("alice"), "Author", "auth_003", "name")
    assert real_value == "Grace Hopper"


# --- a write that outlived the configuration it was written against ---
#
# HOT_RELOAD_PLAN.md step 6. The pending-write store SURVIVES a reload,
# deliberately -- discarding proposals on every configuration change
# would make an approvals inbox useless -- so the ontology a write was
# written against may no longer describe the fields it targets.

def test_a_write_whose_field_is_gone_is_refused_at_confirm_time(wm):
    """REFUSED BEFORE APPLYING, not during.

    The failure would otherwise arrive AFTER a human approved it: the
    approver is told their decision was accepted, and then that it
    could not be carried out. That is the worst order to learn those
    two things in.
    """
    pending = wm.propose_action(
        _record("alice"), "RenameAuthor", {"author_id": "auth_001", "new_name": "Ada L."},
        origin="human",
    )

    # The reload: `name` is no longer declared on Author.
    #
    # RESTORED IN A finally, because this schema dict is shared across
    # the module and an unrestored mutation makes later tests fail for
    # a reason that has nothing to do with them -- which is exactly
    # what happened while writing these.
    schema = wm._adapter_mediator.schema
    original = schema["Author"]
    schema["Author"] = {**original, "fields": {}}
    try:
        with pytest.raises(ValueError, match="no longer declares"):
            wm.confirm_and_execute(pending, approved=True)
    finally:
        schema["Author"] = original


def test_the_refusal_names_the_field_and_both_generations(wm):
    # The pair of generations IS the explanation: proposed under 7 and
    # refused under 12 says exactly where to look for what changed. A
    # message naming only the field leaves the operator guessing when.
    pending = wm.propose_action(
        _record("alice"), "RenameAuthor", {"author_id": "auth_001", "new_name": "Ada L."},
        origin="human",
    )
    schema = wm._adapter_mediator.schema
    original = schema["Author"]
    schema["Author"] = {**original, "fields": {}}
    wm.generation = 12
    try:
        with pytest.raises(ValueError) as caught:
            wm.confirm_and_execute(pending, approved=True)
    finally:
        schema["Author"] = original

    assert "Author.name" in str(caught.value)
    assert "generation 1" in str(caught.value)
    assert "now on 12" in str(caught.value)


def test_nothing_is_written_when_a_write_is_refused(wm):
    # "Nothing has been written" is a claim the message makes, so it is
    # a claim worth checking.
    before = wm.mediator.get_field(_record("alice"), "Author", "auth_001", "name")
    pending = wm.propose_action(
        _record("alice"), "RenameAuthor", {"author_id": "auth_001", "new_name": "Ada L."},
        origin="human",
    )
    schema = wm._adapter_mediator.schema
    original = schema["Author"]
    schema["Author"] = {**original, "fields": {}}

    with pytest.raises(ValueError):
        wm.confirm_and_execute(pending, approved=True)

    schema["Author"] = original
    assert wm.mediator.get_field(_record("alice"), "Author", "auth_001", "name") == before


def test_a_REJECTED_write_is_not_checked_at_all(wm):
    # Rejecting a write whose field vanished must still work. The
    # approver is declining it; whether it COULD have been applied is
    # irrelevant, and refusing the rejection would leave a proposal
    # nobody can clear.
    pending = wm.propose_action(
        _record("alice"), "RenameAuthor", {"author_id": "auth_001", "new_name": "Ada L."},
        origin="human",
    )
    schema = wm._adapter_mediator.schema
    original = schema["Author"]
    schema["Author"] = {**original, "fields": {}}
    try:
        assert wm.confirm_and_execute(pending, approved=False) is None
    finally:
        schema["Author"] = original


def test_an_ordinary_write_is_unaffected(wm):
    # THE CONTROL. A check that refused everything would pass every
    # test above while breaking the product.
    pending = wm.propose_action(
        _record("alice"), "RenameAuthor", {"author_id": "auth_001", "new_name": "Ada L."},
        origin="human",
    )

    assert wm.confirm_and_execute(pending, approved=True)["status"] == "written"
