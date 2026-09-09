"""The request id must reach the audit log, or the whole point is lost.

These test the CHAIN, not the dataclass. A frozen dataclass with one
field needs no test; what needs testing is that the id survives every
hop from the route to the access entry -- which is exactly what a
context variable would have got wrong silently on a pooled thread.
"""

import json
from dataclasses import FrozenInstanceError

import pytest

from core.intermediate_layer.audit import AuditLog
from core.request_context import RequestContext


def _user():
    from core.intermediate_layer.auth import UserRecord
    return UserRecord(user_id="alice", role_name="r", security_value=None)


def _entries(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_a_context_is_unique_per_request(tmp_path):
    # A counter would need shared state, which is the thing this design
    # exists to avoid.
    assert RequestContext.new().request_id != RequestContext.new().request_id


def test_a_context_cannot_be_mutated(tmp_path):
    """Frozen, which is what makes it safe to hand to a worker thread.

    An object several threads share and none can change needs no lock
    and cannot be observed half-updated.
    """
    context = RequestContext.new()

    # The TYPE, not the message. A first version matched on the words
    # "frozen" or "attribute"; the real message is "cannot assign to
    # field", so the test failed against correct code.
    with pytest.raises(FrozenInstanceError):
        context.request_id = "something else"


def test_an_access_entry_carries_the_request_id(tmp_path):
    log_path = tmp_path / "audit.log"
    audit = AuditLog(log_path=log_path)

    audit.log_access("alice", "Customer", "c1", "read", True, True, request_id="req-1")

    assert _entries(log_path)[0]["request_id"] == "req-1"


def test_an_untracked_read_records_NO_id_rather_than_a_wrong_one(tmp_path):
    """None is honest.

    A login check or a startup validation belongs to no request.
    Inventing an id would tie the entry to a request that never
    existed, which is worse than admitting there was none -- an audit
    trail that attributes reads to the wrong unit of work is not a
    weaker trail, it is a misleading one.
    """
    log_path = tmp_path / "audit.log"
    audit = AuditLog(log_path=log_path)

    audit.log_access("alice", "Customer", "c1", "read", True, True)

    entry = _entries(log_path)[0]
    assert "request_id" in entry, "the key must be written either way"
    assert entry["request_id"] is None


def test_two_concurrent_requests_do_not_share_an_id(tmp_path):
    """THE property that ruled out a context variable.

    Elysium runs synchronous work on a pooled ThreadPoolExecutor, and a
    pooled worker keeps whatever context it was last left with -- so a
    task landing on a worker without setting one would inherit the
    previous request's id and log one user's reads under another's.

    Threading the context explicitly makes that impossible: each call
    carries its own.
    """
    from concurrent.futures import ThreadPoolExecutor

    log_path = tmp_path / "audit.log"
    audit = AuditLog(log_path=log_path)
    contexts = [RequestContext.new() for _ in range(2)]

    def do_read(index):
        audit.log_access(f"user{index}", "Customer", f"c{index}", "read", True, True,
                         request_id=contexts[index].request_id)

    # A pool of ONE, so both tasks genuinely run on the same worker --
    # the exact condition under which a context variable leaks.
    with ThreadPoolExecutor(max_workers=1) as pool:
        list(pool.map(do_read, [0, 1]))

    by_user = {e["user_id"]: e["request_id"] for e in _entries(log_path)}
    assert by_user["user0"] == contexts[0].request_id
    assert by_user["user1"] == contexts[1].request_id
    assert by_user["user0"] != by_user["user1"]


def test_check_access_carries_the_context_into_the_log(tmp_path, monkeypatch):
    """The CHAIN, not the endpoints.

    A first version of this file tested log_access directly, so a
    control that dropped the id inside check_access passed -- the
    threading between them was never exercised. This calls the
    authorization path itself.
    """
    from core.intermediate_layer import access_control

    written = []

    class FakeAudit:
        def log_access(self, *args, request_id=None, **kwargs):
            written.append(request_id)

    class FakeMediator:
        audit_log = FakeAudit()
        schema = {}

    monkeypatch.setattr(access_control, "authorize", lambda *a, **k: True)
    context = RequestContext.new()

    access_control.check_access(
        FakeMediator(), _user(), {}, "Customer", "c1", "read", context,
    )

    assert written == [context.request_id]


def test_check_access_without_a_context_records_none(tmp_path, monkeypatch):
    from core.intermediate_layer import access_control

    written = []

    class FakeAudit:
        def log_access(self, *args, request_id=None, **kwargs):
            written.append(request_id)

    class FakeMediator:
        audit_log = FakeAudit()
        schema = {}

    monkeypatch.setattr(access_control, "authorize", lambda *a, **k: True)

    access_control.check_access(FakeMediator(), _user(), {}, "Customer", "c1", "read")

    assert written == [None]
