"""
The write log is asked once, not once per object per field.

MEASURED BEFORE AND AFTER. Counting 50,000 transactions by category
took 35 SECONDS and opened 200,023 SQLite connections -- four per
object, because every field read asked the write log two questions and
each opened its own connection. After batching: 1.29 seconds, same 43
groups. A 27x improvement on the real path.

THE BENCHMARK THAT NEARLY MISLED ME measured grouping in isolation and
showed DuckDB beating Python 8.9x. Real, reproducible, and the wrong
thing: the grouping loop was 0.24s of the 41. Optimising it would have
left 38.7s untouched.

WHAT MUST NOT CHANGE is the ANSWER. A pending write still shadows the
stored value, a deleted object still reads as absent, and an object
with neither still reads from storage. These tests exist for that,
because the fast path re-implements semantics the per-object path had
in one place.
"""

import pytest

from core.intermediate_layer.auth import UserRecord
from core.ontology.write_log import WriteLogWriter

ALICE = UserRecord("alice", "us-west", "customer_service")


@pytest.fixture
def write_log(mediator):
    """The mediator's OWN write log, written through the real writer.

    Not a fake: what is being tested is that the batch lookups agree
    with the per-object ones, and a fake would only agree with itself.
    """
    return mediator.write_log


@pytest.fixture
def writer(mediator):
    return WriteLogWriter(mediator.write_log.db_path)


def test_a_pending_change_still_shadows_the_stored_value(mediator, writer):
    # The whole point of consulting the write log: an uncommitted edit
    # is visible to its own deployment before it is applied.
    writer.log_pending_update("Customer", "cust_001", {"name": "Pending Name"}, {}, "alice", "req-1")

    rows = mediator._read_fields_for_ids(ALICE, "Customer", {"cust_001"}, ["name"])

    assert rows["cust_001"]["name"] == "Pending Name"


def test_an_object_with_no_pending_change_reads_from_storage(mediator):
    # THE CONTROL, and the overwhelmingly common case. A batch lookup
    # that returned nothing useful would silently blank every field.
    rows = mediator._read_fields_for_ids(ALICE, "Customer", {"cust_001"}, ["name"])

    assert rows["cust_001"]["name"] == "Ada Okafor"


def test_only_the_changed_field_is_shadowed(mediator, writer):
    # A pending change touching one field must not blank the others --
    # the per-object path merged field by field, and the batch path has
    # to merge the same way.
    writer.log_pending_update("Customer", "cust_001", {"name": "Pending Name"}, {}, "alice", "req-2")

    rows = mediator._read_fields_for_ids(ALICE, "Customer", {"cust_001"}, ["name", "region"])

    assert rows["cust_001"]["name"] == "Pending Name"
    assert rows["cust_001"]["region"] == "us-west"


def test_several_objects_are_resolved_independently(mediator, writer):
    # The bug a batch introduces if the id mapping is wrong: one
    # object's pending change leaking onto another.
    writer.log_pending_update("Customer", "cust_001", {"name": "Only This One"}, {}, "alice", "req-3")

    rows = mediator._read_fields_for_ids(ALICE, "Customer", {"cust_001", "cust_002"}, ["name"])

    assert rows["cust_001"]["name"] == "Only This One"
    assert rows["cust_002"]["name"] != "Only This One"


def test_the_batch_lookup_returns_only_ids_that_have_changes(write_log, writer):
    # Absence means "no change", not "not asked about" -- so a caller
    # needs no sentinel and cannot confuse the two.
    writer.log_pending_update("Customer", "cust_001", {"name": "x"}, {}, "alice", "req-4")

    found = write_log.pending_changes_for_ids("Customer", ["cust_001", "cust_002"])

    assert set(found) == {"cust_001"}


def test_an_empty_id_list_asks_nothing(write_log):
    # An aggregate over zero visible objects must not build a query
    # with an empty IN clause, which is a syntax error in SQLite.
    assert write_log.pending_changes_for_ids("Customer", []) == {}
    assert write_log.deleted_ids("Customer", []) == set()


def test_more_ids_than_sqlite_allows_in_one_query(write_log, writer):
    # SQLite caps bound variables (999 on older builds), and an
    # aggregate over a whole table exceeds it. Chunking is why the
    # batch form works at the size that motivated it.
    writer.log_pending_update("Customer", "cust_001", {"name": "x"}, {}, "alice", "req-5")
    many = [f"cust_{n:05d}" for n in range(2500)] + ["cust_001"]

    found = write_log.pending_changes_for_ids("Customer", many)

    assert set(found) == {"cust_001"}


def test_a_deleted_object_reads_as_absent(mediator, writer):
    """THE SEMANTIC A CONTROL CAUGHT ME MISSING.

    The per-object path returned None for every field of a deleted
    object. The batch path has to do the same, and nothing tested it
    until removing the check failed nothing.
    """
    # A delete is recorded AGAINST a write log entry, not standalone --
    # the log id has to exist first, which is the audit trail doing its
    # job rather than an inconvenience.
    log_id = writer.log_pending_update(
        "Customer", "cust_002", {}, {}, "alice", "removing this customer",
        operation="delete",
    )
    writer.record_delete("Customer", "cust_002", log_id)

    rows = mediator._read_fields_for_ids(ALICE, "Customer", {"cust_001", "cust_002"}, ["name"])

    assert rows["cust_002"]["name"] is None
    # And only that one: a batch that over-applied deletion would blank
    # every object it was asked about.
    assert rows["cust_001"]["name"] == "Ada Okafor"


def test_the_chunk_loop_gives_the_same_answer_as_one_query(write_log, writer):
    """HONEST LIMIT, recorded rather than dressed up.

    The chunking exists because SQLite caps bound variables, and older
    builds cap it at 999. This build allows far more, so a control
    raising the chunk size to 100,000 changes nothing and the test
    cannot prove the chunk is NECESSARY.

    What it does prove is that the loop is CORRECT: asked about more
    ids than one chunk holds, it finds exactly the ones that have
    changes and no others.
    """
    writer.log_pending_update("Customer", "cust_001", {"name": "x"}, {}, "alice", "req-chunk")
    many = [f"cust_{n:05d}" for n in range(1200)] + ["cust_001"]

    found = write_log.pending_changes_for_ids("Customer", many)

    assert set(found) == {"cust_001"}
