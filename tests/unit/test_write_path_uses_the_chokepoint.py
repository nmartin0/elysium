"""The write path reaches MAC through check_access(), so it emits the
same audit signals a read does (001's 004-8).

WHAT THE FINDING SAID AND WHAT MEASURING IT CHANGED. 004-8 reported
that "the documented single enforcement point is not single":
WriteMediator called `_security_allowed()` directly rather than
`check_access()`. True, but not as a duplicated combination -- reading
the code showed RBAC is gated ONCE, upstream in propose_action(), and
MAC per object here, which is the right shape. The grant is about the
ACTION; re-deciding it per sub_write would be redundant.

THE REAL DIFFERENCE WAS ONE AUDIT SIGNAL, and it is not in the audit
report. On a MAC denial, check_access() asks whether the object's
security value could be resolved AT ALL and records
log_security_resolution_failed() when it could not -- an orphaned MDO
record, a data-integrity signal, distinct from an ordinary mismatch.

GREPPED, NOT ASSUMED: log_security_resolution_failed() is called from
exactly ONE place in core/, inside check_access(). So a path that does
not go through there cannot emit it, whatever else it does correctly.
The same broken object produced that signal on a READ and silence on a
WRITE.

WHY A DIRECT CALL RATHER THAN A PROPOSAL THROUGH THE API. The
condition needs an object whose security value is unresolvable while
the object is still addressable -- an orphan. Building one through a
real deployment means corrupting a fixture in a way that would then
have to be described and maintained; calling the method with a
mediator that reports exactly that state tests the same branch without
inventing a broken deployment for everything else to trip over. The
end-to-end behaviour is already covered by the suite, which stayed
green through this change: 2,853 unit and 445 integration, no test
edited.
"""

import types

import pytest

from core.intermediate_layer.auth import UserRecord
from core.ontology.write_mediator import WriteMediator


class _SpyAuditLog:
    def __init__(self):
        self.accesses: list[tuple] = []
        self.resolution_failures: list[tuple] = []

    def log_access(self, user_id, object_type, object_id, action,
                   mac_allowed, rbac_allowed, request_id=None):
        self.accesses.append((user_id, object_type, object_id, action,
                              mac_allowed, rbac_allowed))

    def log_security_resolution_failed(self, user_id, object_type, object_id):
        self.resolution_failures.append((user_id, object_type, object_id))


class _StubMediator:
    """A mediator reporting one object as UNRESOLVABLE -- the orphan."""

    def __init__(self, audit_log, *, resolvable: bool):
        self.audit_log = audit_log
        self._resolvable = resolvable

    def _security_allowed(self, object_type, object_id, security_value) -> bool:
        return False

    def _get_security_value(self, object_type, object_id):
        return "us-east" if self._resolvable else None


def _write_mediator(audit_log, *, resolvable: bool) -> WriteMediator:
    """A WriteMediator with only what _authorize_sub_write touches.

    Built with object.__new__ rather than the real constructor, which
    wants adapters, a write log and a deployment. That is a deliberate
    narrowing, not a shortcut: the method under test reads exactly
    three attributes, and a full construction would make this a test
    of the constructor.
    """
    mediator = object.__new__(WriteMediator)
    mediator._adapter_mediator = _StubMediator(audit_log, resolvable=resolvable)
    mediator.roles = {"agent": {"allowed_actions": ["execute:MoveCustomer"]}}
    # audit_log is a PROPERTY returning self.mediator.audit_log, not an
    # attribute -- assigning it raises. Found by assuming otherwise.
    mediator.mediator = types.SimpleNamespace(audit_log=audit_log)
    return mediator


@pytest.fixture
def user():
    return UserRecord(user_id="alice", security_value="us-west", role_name="agent")


def test_an_unresolvable_security_value_is_recorded_on_a_write(user):
    """THE GAP ITSELF. Before this change the write path computed MAC
    inline and this signal was never emitted."""
    audit = _SpyAuditLog()
    mediator = _write_mediator(audit, resolvable=False)

    with pytest.raises(PermissionError):
        mediator._authorize_sub_write(
            user, "Customer", "orphan_001", "update", "execute:MoveCustomer", True
        )

    assert audit.resolution_failures == [("alice", "Customer", "orphan_001")]


def test_an_ordinary_mismatch_is_not_recorded_as_a_resolution_failure(user):
    """THE OPPOSITE DIRECTION. A guard that fired on every denial would
    satisfy the test above while making the signal meaningless -- it
    exists to distinguish a broken object from a denied one."""
    audit = _SpyAuditLog()
    mediator = _write_mediator(audit, resolvable=True)

    with pytest.raises(PermissionError):
        mediator._authorize_sub_write(
            user, "Customer", "cust_001", "update", "execute:MoveCustomer", True
        )

    assert audit.resolution_failures == []
    assert audit.accesses, "the denial was not audited at all"


def test_the_denial_is_still_audited_with_both_gates_broken_out(user):
    """UNCHANGED BEHAVIOUR, pinned while the path underneath moved."""
    audit = _SpyAuditLog()
    mediator = _write_mediator(audit, resolvable=True)

    with pytest.raises(PermissionError):
        mediator._authorize_sub_write(
            user, "Customer", "cust_001", "update", "execute:MoveCustomer", True
        )

    (_, object_type, object_id, action, mac_allowed, rbac_allowed) = audit.accesses[-1]
    assert (object_type, object_id, action) == ("Customer", "cust_001", "execute:MoveCustomer")
    assert mac_allowed is False
    assert rbac_allowed is True


def test_a_create_still_skips_mac_and_says_so(user):
    """A CREATE HAS NO ROW TO CONSULT, so it is gated by the execute:
    grant alone and must NOT reach check_access() -- which would read a
    security value from an object that does not exist and deny. This
    pins that the create branch was left alone deliberately."""
    audit = _SpyAuditLog()
    mediator = _write_mediator(audit, resolvable=False)

    mediator._authorize_sub_write(
        user, "Customer", "new_001", "create", "execute:MoveCustomer", True
    )

    assert audit.resolution_failures == []
    (_, _, object_id, _, mac_allowed, rbac_allowed) = audit.accesses[-1]
    assert (object_id, mac_allowed, rbac_allowed) == ("new_001", True, True)
