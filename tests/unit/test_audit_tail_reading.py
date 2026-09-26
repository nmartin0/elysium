"""entries_for_request() reads the END of the audit log, not all of it
(001's F-21).

WHAT WENT WRONG. The method sliced `lines[-max_scan:]` off
`f.readlines()`, so the cap bounded the PARSE and not the READ -- the
whole file was in memory before the slice could discard any of it. Its
own docstring said the cap "bounds the cost to a constant regardless of
how long the deployment has been running", which was the opposite of
what it did. MEASURED, answering a three-entry request at the end of
the file:

      100,000 entries   21.3 MB     634 ms    26.6 MB peak
      400,000 entries   85.2 MB     981 ms   105.3 MB peak
      800,000 entries  170.4 MB   1,440 ms   210.3 MB peak

After: 0.3 MB peak at every size, and ~630 ms flat once past the cap.

WHY THE TEST COUNTS BYTES RATHER THAN TIMING OR MEMORY. A timing
assertion is flaky on a shared runner and a tracemalloc threshold is a
judgement call. "How many bytes did you read from this file" is exactly
the property, and it is an integer. The counting handle below wraps
read/readline/readlines, which is every route either implementation
takes to the file's contents.
"""

import json
from pathlib import Path

import pytest

from core.intermediate_layer import audit as audit_module
from core.intermediate_layer.audit import AuditLog


class _CountingHandle:
    """Proxies a file object and totals the bytes it hands out."""

    def __init__(self, handle, counter):
        self._handle = handle
        self._counter = counter

    def __getattr__(self, name):
        return getattr(self._handle, name)

    def __enter__(self):
        self._handle.__enter__()
        return self

    def __exit__(self, *exc):
        return self._handle.__exit__(*exc)

    def __iter__(self):
        for line in self._handle:
            self._counter[0] += len(line)
            yield line

    def read(self, *args):
        data = self._handle.read(*args)
        self._counter[0] += len(data)
        return data

    def readline(self, *args):
        data = self._handle.readline(*args)
        self._counter[0] += len(data)
        return data

    def readlines(self, *args):
        lines = self._handle.readlines(*args)
        self._counter[0] += sum(len(line) for line in lines)
        return lines


@pytest.fixture
def counted_reads(monkeypatch):
    """Totals the bytes read through the audit module's own `open`.

    Injected as a module global, which Python resolves before builtins,
    so both the old readlines() path and the new block-wise one are
    counted without either knowing.
    """
    counter = [0]
    real_open = open

    def counting_open(*args, **kwargs):
        return _CountingHandle(real_open(*args, **kwargs), counter)

    monkeypatch.setattr(audit_module, "open", counting_open, raising=False)
    return counter


def _write_log(path: Path, filler: int, request_id: str = "req-abc",
               user_id: str = "alice", matching: int = 3) -> None:
    with open(path, "w") as f:
        for i in range(filler):
            f.write(json.dumps({
                "timestamp": "2026-09-25T18:00:00+00:00", "user_id": user_id,
                "object_type": "Customer", "object_id": f"cust_{i:06d}",
                "action": "read:Customer.name", "mac_allowed": True,
                "rbac_allowed": True, "request_id": None,
            }) + "\n")
        for i in range(matching):
            f.write(json.dumps({
                "timestamp": "2026-09-25T18:00:01+00:00", "user_id": user_id,
                "object_type": "Customer", "object_id": f"target_{i}",
                "action": "read:Customer.name", "mac_allowed": True,
                "rbac_allowed": True, "request_id": request_id,
            }) + "\n")


class TestItReadsOnlyTheTail:
    def test_a_large_log_is_not_read_whole(self, tmp_path, counted_reads):
        """THE PROPERTY IS "bounded by max_scan", NOT "stops at the
        first match". The scan cannot stop early -- it does not know
        whether an earlier line also matches -- so it reads back
        max_scan lines and no further. Asserted with an explicit small
        cap, because at the DEFAULT of 50,000 a bounded read is still
        ~10 MB and would look indistinguishable from an unbounded one.
        Getting that wrong is what this test first asserted."""
        log = tmp_path / "audit.log"
        _write_log(log, filler=60_000)
        size = log.stat().st_size

        found = AuditLog(log).entries_for_request("req-abc", "alice", max_scan=100)

        assert len(found) == 3
        assert counted_reads[0] < size / 10, (
            f"read {counted_reads[0]:,} of {size:,} bytes for a 100-line cap"
        )

    def test_and_the_bytes_read_do_not_grow_with_the_file(self, tmp_path, counted_reads):
        """THE CLAIM IN THE DOCSTRING, made testable: cost is bounded by
        max_scan, not by how long the deployment has been running."""
        small = tmp_path / "small.log"
        _write_log(small, filler=5_000)
        AuditLog(small).entries_for_request("req-abc", "alice", max_scan=100)
        small_bytes = counted_reads[0]

        counted_reads[0] = 0
        large = tmp_path / "large.log"
        _write_log(large, filler=60_000)
        AuditLog(large).entries_for_request("req-abc", "alice", max_scan=100)
        large_bytes = counted_reads[0]

        assert large.stat().st_size > small.stat().st_size * 5
        assert large_bytes <= small_bytes * 2, (
            f"a 12x larger file read {large_bytes:,} against {small_bytes:,}"
        )


class TestItStillReturnsTheSameAnswers:
    """The cost is the point, but a cheaper wrong answer is no use."""

    def test_the_matching_entries_come_back_oldest_first(self, tmp_path):
        """OLDEST FIRST, deliberately -- the method reverses at the end
        because "a trace is read as a sequence of what the agent did,
        and that reads forwards". The tail reader hands lines over
        NEWEST first, so this pins that the reversal survived the
        rewrite. I asserted the opposite first and the code was right."""
        log = tmp_path / "audit.log"
        _write_log(log, filler=10)

        found = AuditLog(log).entries_for_request("req-abc", "alice")

        assert [e["object_id"] for e in found] == ["target_0", "target_1", "target_2"]

    def test_another_users_trace_is_never_returned(self, tmp_path):
        """OWNERSHIP, unchanged by this patch and worth pinning while
        the read path is being rewritten underneath it."""
        log = tmp_path / "audit.log"
        _write_log(log, filler=10, user_id="alice")

        assert AuditLog(log).entries_for_request("req-abc", "bob") == []

    def test_a_last_line_with_no_newline_is_still_read(self, tmp_path):
        """A process that died mid-write leaves one. The old slice
        included it; the block reader must too."""
        log = tmp_path / "audit.log"
        _write_log(log, filler=3, matching=0)
        with open(log, "a") as f:
            f.write(json.dumps({
                "user_id": "alice", "request_id": "req-abc",
                "object_type": "Customer", "object_id": "tail",
            }))  # deliberately no trailing newline

        found = AuditLog(log).entries_for_request("req-abc", "alice")

        assert [e["object_id"] for e in found] == ["tail"]

    def test_a_torn_line_is_skipped_rather_than_failing_the_read(self, tmp_path):
        log = tmp_path / "audit.log"
        _write_log(log, filler=2)
        with open(log, "a") as f:
            f.write('{"user_id": "alice", "request_i')

        assert len(AuditLog(log).entries_for_request("req-abc", "alice")) == 3

    def test_an_entry_longer_than_one_block_is_not_torn(self, tmp_path):
        """Lines are read in 64 KiB blocks, so one larger than a block
        straddles a boundary and must be rejoined, not split."""
        log = tmp_path / "audit.log"
        _write_log(log, filler=2, matching=0)
        with open(log, "a") as f:
            f.write(json.dumps({
                "user_id": "alice", "request_id": "req-abc",
                "object_type": "Customer", "object_id": "x" * 200_000,
            }) + "\n")

        found = AuditLog(log).entries_for_request("req-abc", "alice")

        assert len(found) == 1
        assert len(found[0]["object_id"]) == 200_000

    def test_the_cap_still_truncates(self, tmp_path):
        """THE OPPOSITE DIRECTION. A reader that ignored max_scan would
        pass every test above while reinstating the unbounded scan."""
        log = tmp_path / "audit.log"
        _write_log(log, filler=50, matching=0)
        with open(log, "a") as f:
            for i in range(20):
                f.write(json.dumps({
                    "user_id": "alice", "request_id": "req-abc",
                    "object_type": "Customer", "object_id": f"t{i}",
                }) + "\n")

        found = AuditLog(log).entries_for_request("req-abc", "alice", max_scan=5)

        assert len(found) == 5

    def test_a_missing_log_is_empty_not_an_error(self, tmp_path):
        assert AuditLog(tmp_path / "nothing.log").entries_for_request("r", "alice") == []

    def test_an_empty_log_is_empty(self, tmp_path):
        log = tmp_path / "audit.log"
        log.write_text("")

        assert AuditLog(log).entries_for_request("req-abc", "alice") == []

    def test_blank_lines_do_not_consume_the_cap(self, tmp_path):
        """The old slice counted them and threw each away at
        json.loads(); not counting them makes the cap mean what it
        says."""
        log = tmp_path / "audit.log"
        with open(log, "w") as f:
            f.write("\n" * 100)
            for i in range(3):
                f.write(json.dumps({
                    "user_id": "alice", "request_id": "req-abc",
                    "object_type": "Customer", "object_id": f"t{i}",
                }) + "\n")

        assert len(AuditLog(log).entries_for_request("req-abc", "alice", max_scan=10)) == 3
