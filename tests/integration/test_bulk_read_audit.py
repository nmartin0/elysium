"""
One audit record for one read, and every denial named.

MEASURED. A read over 50,000 objects wrote 50,007 audit records --
49,997 of them identical grants -- and spent 1.08 of 1.45 seconds doing
it. It now writes 4: one for the read, three for the denials. 0.52s,
same answers.

WHY THIS IS THE RIGHT GRANULARITY RATHER THAN A SHORTCUT. NIST SP
800-92 asks for "events that are significant for security and
accountability... events that involve a state change or a SECURITY
DECISION". A bulk read makes ONE decision -- may this user read this
type -- and applies it many times. The decision is the event.

Successful access stays in scope: the same guidance lists "attempts to
access sensitive resources (successful and failed)". This records that
the read happened, at the granularity of the thing that happened.

DENIALS ARE NEVER SUMMARISED, because "sample strategically for
non-security telemetry ONLY". Every denial keeps its own record AND is
named in the bulk one.

AND IT IS FINER, NOT COARSER, IN EVERY OTHER DIMENSION. The six
questions a defensible trail answers -- who, what, when, where, why,
what outcome -- are all answered here. The per-object records answered
three, and never captured which FIELDS were read or which SECURITY
PARTITIONS a query touched.
"""

import collections
import json

from core.intermediate_layer.auth import UserRecord

ALICE = UserRecord("alice", "us-west", "customer_service")


def _log_file(log_dir):
    """The audit LOG FILE inside the fixture's log DIRECTORY.

    isolated_audit_log is a directory -- named for what it isolates
    rather than for what it is -- and opening it directly raises
    IsADirectoryError.
    """
    return log_dir / "audit.log"


def _entries_after(log_dir, offset):
    log_path = _log_file(log_dir)
    if not log_path.exists():
        return []
    with open(log_path) as f:
        f.seek(offset)
        return [json.loads(line) for line in f if line.strip()]


def test_a_read_writes_one_record_not_one_per_object(mediator, isolated_audit_log):
    before = _log_file(isolated_audit_log).stat().st_size if _log_file(isolated_audit_log).exists() else 0

    mediator.search_object(ALICE, "Customer", [])

    entries = _entries_after(isolated_audit_log, before)
    stages = collections.Counter(entry["stage"] for entry in entries)
    assert stages["bulk_read"] == 1


def test_grants_no_longer_write_their_own_record(mediator, isolated_audit_log):
    # THE WHOLE POINT. Every object alice can see used to produce an
    # identical access_check line.
    before = _log_file(isolated_audit_log).stat().st_size if _log_file(isolated_audit_log).exists() else 0

    allowed = mediator.search_object(ALICE, "Customer", [])

    entries = _entries_after(isolated_audit_log, before)
    grants = [e for e in entries if e["stage"] == "access_check" and e.get("allowed")]
    assert allowed, "the fixture must grant something for this to mean anything"
    assert grants == []


def test_every_denial_still_writes_its_own_record(mediator, isolated_audit_log):
    """DENIALS ARE NEVER SUMMARISED.

    "Sample strategically for non-security telemetry only" -- a denial
    is a security event, and one that cannot be named is unauditable.
    """
    before = _log_file(isolated_audit_log).stat().st_size if _log_file(isolated_audit_log).exists() else 0

    mediator.search_object(ALICE, "Customer", [])

    entries = _entries_after(isolated_audit_log, before)
    denials = [e for e in entries if e["stage"] == "access_check" and not e.get("allowed")]
    bulk = next(e for e in entries if e["stage"] == "bulk_read")

    # The two must agree: a count nobody can reconcile is worse than no
    # count, because it looks authoritative.
    assert len(denials) == bulk["denied"]
    assert len(bulk["denied_object_ids"]) == bulk["denied"]


def test_the_bulk_record_answers_the_six_questions(mediator, isolated_audit_log):
    # who acted, what, when, where it originated, why permitted, what
    # outcome. The per-object records answered three.
    before = _log_file(isolated_audit_log).stat().st_size if _log_file(isolated_audit_log).exists() else 0

    mediator.search_object(ALICE, "Customer", [])

    bulk = next(e for e in _entries_after(isolated_audit_log, before)
                if e["stage"] == "bulk_read")

    assert bulk["user_id"] == "alice"          # who
    assert bulk["object_type"] == "Customer"   # what
    assert "timestamp" in bulk                 # when
    assert "request_id" in bulk                # where it originated
    assert "security_values_seen" in bulk      # why it was permitted
    assert "considered" in bulk and "denied" in bulk   # what outcome


def test_it_names_the_security_partitions_touched(mediator, isolated_audit_log):
    """A QUESTION THE OLD RECORDS COULD NOT ANSWER.

    Read through the resolver rather than the cache: the cache is keyed
    by the type a security value LIVES ON, which for a via_field chain
    is the far side. Reading it directly returned an empty set and
    would have shipped a silently blank audit field -- caught by
    looking at the output rather than by a test.
    """
    before = _log_file(isolated_audit_log).stat().st_size if _log_file(isolated_audit_log).exists() else 0

    mediator.search_object(ALICE, "Transaction", [])

    bulk = next(e for e in _entries_after(isolated_audit_log, before)
                if e["stage"] == "bulk_read" and e["object_type"] == "Transaction")

    assert bulk["security_values_seen"] == ["us-west"]


def test_the_considered_count_is_every_candidate(mediator, isolated_audit_log):
    # Not just the allowed ones. "Considered" is what the read looked
    # at; "denied" is what it withheld. Conflating them would hide the
    # withholding.
    before = _log_file(isolated_audit_log).stat().st_size if _log_file(isolated_audit_log).exists() else 0

    allowed = mediator.search_object(ALICE, "Customer", [])

    bulk = next(e for e in _entries_after(isolated_audit_log, before)
                if e["stage"] == "bulk_read")
    assert bulk["considered"] == len(allowed) + bulk["denied"]
