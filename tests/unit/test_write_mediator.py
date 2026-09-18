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
from core.intermediate_layer.audit import AuditLog
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from core.ontology.submission_criteria import SubmissionCriteriaViolation
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


# --- four-eyes: criteria evaluated against the APPROVER ---
#
# propose_action() evaluates criteria against the PROPOSER. A four-eyes
# rule is about the approver and says nothing at propose time, because
# there is no approver yet -- which is why evaluating only once meant
# the rule could be written and never enforced.

FOUR_EYES = [{
    "check": "user",
    "field": "user_id",
    "operator": "not_equals",
    "value": "proposer.user_id",
    "description": "A write must be approved by someone other than its proposer.",
}]


def _with_four_eyes(wm):
    """Adds a four-eyes rule to RenameAuthor's sub_write.

    Restored by the caller: action_types is shared across this module
    and an unrestored mutation makes later tests fail for reasons that
    have nothing to do with them.
    """
    action = wm.action_types["RenameAuthor"]
    original = action["sub_writes"]
    action["sub_writes"] = [{**original[0], "submission_criteria": FOUR_EYES}]
    return original


def test_someone_else_may_approve_a_write(wm):
    original = _with_four_eyes(wm)
    try:
        pending = wm.propose_action(
            _record("alice"), "RenameAuthor",
            {"author_id": "auth_001", "new_name": "Ada L."}, origin="human",
        )

        result = wm.confirm_and_execute(pending, approved=True, approver=_record("bob"))

        assert result["status"] == "written"
    finally:
        wm.action_types["RenameAuthor"]["sub_writes"] = original


def test_the_proposer_may_not_approve_their_own_write(wm):
    # THE RULE THIS EXISTS FOR, and it could not be enforced at all
    # before criteria were evaluated at confirm time.
    original = _with_four_eyes(wm)
    try:
        pending = wm.propose_action(
            _record("alice"), "RenameAuthor",
            {"author_id": "auth_001", "new_name": "Ada L."}, origin="human",
        )

        with pytest.raises(SubmissionCriteriaViolation, match="other than its proposer"):
            wm.confirm_and_execute(pending, approved=True, approver=_record("alice"))
    finally:
        wm.action_types["RenameAuthor"]["sub_writes"] = original


def test_a_refused_approval_writes_nothing(wm):
    # The criteria check runs BEFORE anything is applied, so a refusal
    # must leave the object exactly as it was.
    original = _with_four_eyes(wm)
    try:
        before = wm.mediator.get_field(_record("alice"), "Author", "auth_001", "name")
        pending = wm.propose_action(
            _record("alice"), "RenameAuthor",
            {"author_id": "auth_001", "new_name": "Ada L."}, origin="human",
        )

        with pytest.raises(SubmissionCriteriaViolation):
            wm.confirm_and_execute(pending, approved=True, approver=_record("alice"))

        assert wm.mediator.get_field(_record("alice"), "Author", "auth_001", "name") == before
    finally:
        wm.action_types["RenameAuthor"]["sub_writes"] = original


def test_a_rejection_is_not_blocked_by_criteria(wm):
    # The proposer may always REJECT their own write. Whether they
    # could have approved it is irrelevant, and blocking the rejection
    # would leave a proposal nobody can clear.
    original = _with_four_eyes(wm)
    try:
        pending = wm.propose_action(
            _record("alice"), "RenameAuthor",
            {"author_id": "auth_001", "new_name": "Ada L."}, origin="human",
        )

        assert wm.confirm_and_execute(pending, approved=False, approver=_record("alice")) is None
    finally:
        wm.action_types["RenameAuthor"]["sub_writes"] = original


def test_an_action_with_no_criteria_is_unaffected_by_the_approver(wm):
    # THE CONTROL. Most actions declare no criteria at all, and a
    # confirm-time check that refused them would break every write.
    pending = wm.propose_action(
        _record("alice"), "RenameAuthor",
        {"author_id": "auth_001", "new_name": "Ada L."}, origin="human",
    )

    assert wm.confirm_and_execute(
        pending, approved=True, approver=_record("alice"),
    )["status"] == "written"


def test_an_omitted_approver_skips_the_check_rather_than_failing(wm):
    # scripts/run_deployment.py and older tests call without one. A
    # missing approver must not mean "deny": that would break every
    # non-HTTP caller, and the HTTP route always supplies one.
    original = _with_four_eyes(wm)
    try:
        pending = wm.propose_action(
            _record("alice"), "RenameAuthor",
            {"author_id": "auth_001", "new_name": "Ada L."}, origin="human",
        )

        assert wm.confirm_and_execute(pending, approved=True)["status"] == "written"
    finally:
        wm.action_types["RenameAuthor"]["sub_writes"] = original


# --- the audit names both parties ---
#
# log_pre() records pending.user_id, which is the PROPOSER. A four-eyes
# deployment could enforce that two different people were involved and
# then be unable to PROVE it afterwards: the control existed, the
# evidence did not.

def _audit_entries(tmp_path):
    import json

    log = tmp_path / "audit.log"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_the_audit_names_the_approver_as_well_as_the_proposer(wm, tmp_path):
    # Set on the MEDIATOR, not the write mediator: audit_log is a
    # read-only property that always returns the mediator's own
    # instance, deliberately, so there is never a second copy.
    wm.mediator.audit_log = AuditLog(tmp_path / "audit.log")
    pending = wm.propose_action(
        _record("alice"), "RenameAuthor",
        {"author_id": "auth_001", "new_name": "Ada L."}, origin="human",
    )

    wm.confirm_and_execute(pending, approved=True, approver=_record("bob"))

    entry = [e for e in _audit_entries(tmp_path) if e.get("stage") == "pre"][-1]
    assert entry["user_id"] == "alice"
    assert entry["params"]["approved_by"] == "bob"


def test_a_self_approval_is_flagged_rather_than_left_to_be_derived(wm, tmp_path):
    # Someone auditing a four-eyes control asks ONE question -- were
    # these the same person -- and a log that makes them compare two
    # fields invites the comparison being done wrong, or not at all.
    # Set on the MEDIATOR, not the write mediator: audit_log is a
    # read-only property that always returns the mediator's own
    # instance, deliberately, so there is never a second copy.
    wm.mediator.audit_log = AuditLog(tmp_path / "audit.log")
    pending = wm.propose_action(
        _record("alice"), "RenameAuthor",
        {"author_id": "auth_001", "new_name": "Ada L."}, origin="human",
    )

    wm.confirm_and_execute(pending, approved=True, approver=_record("alice"))

    entry = [e for e in _audit_entries(tmp_path) if e.get("stage") == "pre"][-1]
    assert entry["params"]["self_approved"] is True


def test_two_parties_are_not_flagged_as_self_approval(wm, tmp_path):
    # THE CONTROL for the test above: a flag that is always true says
    # nothing.
    # Set on the MEDIATOR, not the write mediator: audit_log is a
    # read-only property that always returns the mediator's own
    # instance, deliberately, so there is never a second copy.
    wm.mediator.audit_log = AuditLog(tmp_path / "audit.log")
    pending = wm.propose_action(
        _record("alice"), "RenameAuthor",
        {"author_id": "auth_001", "new_name": "Ada L."}, origin="human",
    )

    wm.confirm_and_execute(pending, approved=True, approver=_record("bob"))

    entry = [e for e in _audit_entries(tmp_path) if e.get("stage") == "pre"][-1]
    assert entry["params"]["self_approved"] is False


def test_an_unreviewed_write_records_no_approver(wm, tmp_path):
    # HONEST RATHER THAN TIDY. scripts/run_deployment.py confirms
    # without an approver, and writing the proposer into that field
    # would make a single-party write look like a reviewed one.
    # Set on the MEDIATOR, not the write mediator: audit_log is a
    # read-only property that always returns the mediator's own
    # instance, deliberately, so there is never a second copy.
    wm.mediator.audit_log = AuditLog(tmp_path / "audit.log")
    pending = wm.propose_action(
        _record("alice"), "RenameAuthor",
        {"author_id": "auth_001", "new_name": "Ada L."}, origin="human",
    )

    wm.confirm_and_execute(pending, approved=True)

    entry = [e for e in _audit_entries(tmp_path) if e.get("stage") == "pre"][-1]
    assert entry["params"]["approved_by"] is None
    assert entry["params"]["self_approved"] is False
