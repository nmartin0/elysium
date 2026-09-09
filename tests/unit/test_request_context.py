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


def test_a_trace_returns_only_its_own_request(tmp_path):
    log_path = tmp_path / "audit.log"
    audit = AuditLog(log_path=log_path)
    audit.log_access("alice", "Customer", "c1", "read", True, True, request_id="req-1")
    audit.log_access("alice", "Customer", "c2", "read", True, True, request_id="req-2")
    audit.log_access("alice", "Customer", "c3", "read", True, True, request_id="req-1")

    trace = audit.entries_for_request("req-1", "alice")

    assert [e["object_id"] for e in trace] == ["c1", "c3"]


def test_a_trace_is_oldest_first(tmp_path):
    # A trace is read as a SEQUENCE of what the agent did, and that
    # reads forwards -- even though the scan runs backwards.
    log_path = tmp_path / "audit.log"
    audit = AuditLog(log_path=log_path)
    for index in range(3):
        audit.log_access("alice", "Customer", f"c{index}", "read", True, True,
                         request_id="req-1")

    trace = audit.entries_for_request("req-1", "alice")

    assert [e["object_id"] for e in trace] == ["c0", "c1", "c2"]


def test_one_user_cannot_read_anothers_trace(tmp_path):
    """A request id is a uuid and unguessable, but "unguessable" is not
    "authorized".

    One appearing in a log line, a bug report or a screenshot must not
    become a key to somebody else's activity -- the entries name what
    THAT user looked at, which this caller never had.
    """
    log_path = tmp_path / "audit.log"
    audit = AuditLog(log_path=log_path)
    audit.log_access("alice", "Customer", "c1", "read", True, True, request_id="req-1")

    assert audit.entries_for_request("req-1", "bob") == []


def test_untracked_entries_never_match_a_trace(tmp_path):
    # A read belonging to no request has request_id None, and None is
    # not a request anyone can ask for.
    log_path = tmp_path / "audit.log"
    audit = AuditLog(log_path=log_path)
    audit.log_access("alice", "Customer", "c1", "read", True, True)

    assert audit.entries_for_request("req-1", "alice") == []
    assert audit.entries_for_request(None, "alice") == []


def test_the_scan_is_bounded(tmp_path):
    """The design decision, not an optimisation.

    A forward scan reads the whole file, which is fine at a fixture's
    volume and wrong at a real one. Reading backwards with a cap bounds
    the cost regardless of how long the deployment has run -- and a
    request being asked about is almost always the one that just ran.

    The cap can truncate, and this asserts that it DOES rather than
    silently reading everything.
    """
    log_path = tmp_path / "audit.log"
    audit = AuditLog(log_path=log_path)
    audit.log_access("alice", "Customer", "old", "read", True, True, request_id="req-1")
    for index in range(10):
        audit.log_access("alice", "Customer", f"c{index}", "read", True, True,
                         request_id="req-2")

    # A window smaller than the file cannot reach the first entry.
    trace = audit.entries_for_request("req-1", "alice", max_scan=5)

    assert trace == []


def test_a_torn_line_does_not_fail_the_whole_read(tmp_path):
    # A process dying mid-write leaves a partial line. Skipping it
    # beats failing every trace in the file.
    log_path = tmp_path / "audit.log"
    audit = AuditLog(log_path=log_path)
    audit.log_access("alice", "Customer", "c1", "read", True, True, request_id="req-1")
    with open(log_path, "a") as f:
        f.write('{"stage": "access_check", "request_i\n')

    assert len(audit.entries_for_request("req-1", "alice")) == 1
