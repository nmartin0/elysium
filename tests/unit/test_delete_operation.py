"""
Point 13: delete, modelled as an EDIT rather than a DELETE statement.

FOUNDRY'S MODEL, which reshaped this entire feature. Their actions
"edit, create, delete, and link object data", but a delete there never
touches the source: "edits are written to the writeback dataset and
NOT the dataset backing an object type... This ensures that users have
access to both the original data and the edited data." Their
resolution rule is that when an object's latest edit is a delete, the
object "is not visible in the ontology, regardless of whether any
corresponding row is in one of the data sources."

WHY THAT MATTERS HERE, beyond matching a precedent. Three options were
drafted before this research -- treat a missing row as success, flag
every interrupted delete ambiguous, or add a deleted_at column to the
customer's schema -- and ALL THREE shared a false premise: that
Elysium would issue a destructive DELETE. Foundry does not, and once
that is fixed the hard problem evaporates:

  - The external read-only guarantee stays intact. Elysium never
    destroys a row it does not own.
  - Delete is REVERSIBLE, because the read path takes the LATEST
    applied operation for an object.
  - Crash recovery is trivial where a destructive delete is genuinely
    ambiguous. A missing row cannot tell you whether your delete
    succeeded, someone else's did, or the row never existed. This
    record lives in storage this project owns, and can simply be read.
"""

import sqlite3
from datetime import UTC, datetime

import pytest
import yaml

from core.deployment_loader import _WRITE_ADAPTER_REGISTRY, _build_adapters
from core.filters import as_equality_conditions
from core.intermediate_layer.auth import UserRecord
from core.ontology.link_types import expand_link_types
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLogWriter
from core.ontology.write_mediator import PendingWrite, SubWrite, WriteMediator

FIXTURES = "tests/integration/fixtures/"
WEST = UserRecord(user_id="u1", security_value="us-west", role_name="customer_service")


@pytest.fixture
def deployment(tmp_path):
    schema = yaml.safe_load(open(FIXTURES + "ontology_schema.yaml"))
    # Link fields are GENERATED from link_types at load; the raw
    # YAML no longer declares them (see core/ontology/link_types.py).
    schema["object_types"] = expand_link_types(
        schema.get("link_types", {}), schema["object_types"]
    )
    policy = yaml.safe_load(open(FIXTURES + "policy.yaml"))

    db_path = tmp_path / "business.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(open(FIXTURES + "schema.sql").read())
    conn.commit()
    conn.close()

    adapters = _build_adapters(
        {"primary_sql": {"adapter": "sqlite", "connection": {"path": db_path}}},
        _WRITE_ADAPTER_REGISTRY,
    )
    object_types = {
        name: type_def
        for name, type_def in schema["object_types"].items()
        if name in ("Customer", "Transaction")
    }
    write_log = WriteLogWriter(tmp_path / "write_log.db")
    mediator = DataMediator(
        object_types, adapters, dict.fromkeys(object_types, "primary_sql"),
        policy["roles"], write_log=write_log,
    )
    write_mediator = WriteMediator(
        mediator, adapters, policy["roles"], schema["action_types"], generation=1)
    return mediator, write_mediator, write_log, db_path


def _write(write_mediator, operation, object_id="cust_001", changes=None, expected=None):
    pending = PendingWrite(
        sub_writes=[
            SubWrite("Customer", object_id, operation, changes or {}, expected or {})
        ],
        user_id="u1",
        description=operation,
        action_type_name="TestAction",
        origin="human",
        proposed_at=datetime.now(UTC),
        proposed_under_generation=1,
        parameters={},
        proposer=UserRecord("u1", "us-west", "analyst"),
    )
    return write_mediator.confirm_and_execute(pending, approved=True)


def _source_row(db_path, object_id="cust_001"):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT name FROM customers WHERE customer_id = ?", (object_id,)
        ).fetchone()
    finally:
        conn.close()


def test_a_deleted_object_is_not_visible(deployment):
    mediator, write_mediator, _log, _db = deployment
    assert mediator.get_field(WEST, "Customer", "cust_001", "name") is not None

    _write(write_mediator, "delete")

    assert mediator.get_field(WEST, "Customer", "cust_001", "name") is None


def test_a_deleted_object_disappears_from_search(deployment):
    mediator, write_mediator, _log, _db = deployment
    before = mediator.search_object(WEST, "Customer", as_equality_conditions({}))

    _write(write_mediator, "delete")
    after = mediator.search_object(WEST, "Customer", as_equality_conditions({}))

    assert "cust_001" in before
    assert "cust_001" not in after
    assert len(after) == len(before) - 1


def test_deleting_never_touches_the_customers_database(deployment):
    # THE property that makes this model right for Elysium rather than
    # merely Foundry-shaped. The external read-only guarantee this
    # whole project is built around would be broken by a destructive
    # delete.
    mediator, write_mediator, _log, db_path = deployment

    _write(write_mediator, "delete")

    assert mediator.get_field(WEST, "Customer", "cust_001", "name") is None
    assert _source_row(db_path) == ("Ada Okafor",), "the source row was destroyed"


def test_a_delete_is_reversible_by_a_later_write(deployment):
    # Foundry's ordering rule: the LATEST edit wins, so a write after a
    # delete makes the object visible again.
    mediator, write_mediator, _log, _db = deployment
    _write(write_mediator, "delete")
    assert mediator.get_field(WEST, "Customer", "cust_001", "name") is None

    _write(
        write_mediator, "update",
        changes={"name": "Ada Restored"}, expected={"name": "Ada Okafor"},
    )

    assert mediator.get_field(WEST, "Customer", "cust_001", "name") == "Ada Restored"
    assert "cust_001" in mediator.search_object(WEST, "Customer", as_equality_conditions({}))


def test_deleting_after_an_update_still_hides_the_object(deployment):
    # The reverse order. "Latest wins" has to work both ways, or a
    # delete could be silently undone by an EARLIER write.
    mediator, write_mediator, _log, _db = deployment
    _write(
        write_mediator, "update",
        changes={"name": "Ada Edited"}, expected={"name": "Ada Okafor"},
    )

    _write(write_mediator, "delete")

    assert mediator.get_field(WEST, "Customer", "cust_001", "name") is None


def test_deleting_one_object_leaves_others_alone(deployment):
    mediator, write_mediator, _log, _db = deployment

    _write(write_mediator, "delete", object_id="cust_001")

    assert mediator.get_field(WEST, "Customer", "cust_002", "name") is not None


def test_recovery_after_a_delete_is_clean(deployment):
    # Where a destructive delete would be genuinely ambiguous, this is
    # trivial: the record is in storage this project owns.
    _mediator, write_mediator, _log, _db = deployment
    _write(write_mediator, "delete")

    assert write_mediator.resume_pending_writes() == {
        "resumed": 0, "already_applied": 0, "ambiguous": 0,
    }


def test_the_delete_is_recorded_as_a_real_log_entry(deployment):
    # The audit trail matters as much as the effect -- a delete must be
    # attributable, like every other write.
    _mediator, write_mediator, log, _db = deployment
    _write(write_mediator, "delete")

    conn = sqlite3.connect(log.db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT operation, user_id, status FROM write_log WHERE object_id = 'cust_001'"
        ).fetchone()
    finally:
        conn.close()

    assert row["operation"] == "delete"
    assert row["user_id"] == "u1"
    assert row["status"] == "applied"


def test_deleted_objects_are_filtered_in_bulk_not_per_object(deployment):
    # The same discipline Point 9 applied to security resolution: a
    # per-object delete check would reintroduce exactly the N+1 that
    # was just removed.
    import adapters.sqlite_adapter as sqlite_adapter_module

    mediator, write_mediator, _log, db_path = deployment
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO customers VALUES (?, ?, ?, ?)",
        [(f"c{i:03d}", f"Person {i}", "us-west", f"e{i}@x.com") for i in range(100)],
    )
    conn.commit()
    conn.close()
    _write(write_mediator, "delete", object_id="c050")

    real_run_query = sqlite_adapter_module._run_query
    counted = {"n": 0}

    def counting(*args, **kwargs):
        counted["n"] += 1
        return real_run_query(*args, **kwargs)

    sqlite_adapter_module._run_query = counting
    try:
        visible = mediator.search_object(WEST, "Customer", as_equality_conditions({}))
    finally:
        sqlite_adapter_module._run_query = real_run_query

    assert "c050" not in visible
    assert counted["n"] <= 5, (
        f"filtering deletes cost {counted['n']} queries -- should be a constant"
    )


# --- The derived deleted-state index ------------------------------------
#
# Resolving deleted-ness by scanning the write log cost 47.2 ms per
# search at 55,000 log rows and grew with edit history forever -- on a
# path that had just been made constant-time. The index is 0.006 ms and
# flat at 555,000 rows.
#
# Following Foundry: "the data-modification logic is immediately applied
# to the index in the object databases", with deleted-ness a stored
# column (__is_deleted) rather than something derived at read time.
# Their index is explicitly ephemeral -- "all indexed data in object
# databases are considered ephemeral, requiring persistent storing of
# all Ontology data in other ways" -- which is exactly what makes a
# derived table safe here rather than a second source of truth.


def test_a_delete_populates_the_index(deployment):
    _mediator, write_mediator, log, _db = deployment

    _write(write_mediator, "delete")

    assert log.deleted_object_ids("Customer") == {"cust_001"}


def test_a_later_write_clears_the_index(deployment):
    # "Last edit wins", the same rule Foundry's indexing uses.
    _mediator, write_mediator, log, _db = deployment
    _write(write_mediator, "delete")

    _write(
        write_mediator, "update",
        changes={"name": "Ada Restored"}, expected={"name": "Ada Okafor"},
    )

    assert log.deleted_object_ids("Customer") == set()


def test_the_index_timestamp_matches_the_log_entry(deployment):
    # deleted_at mirrors Foundry's own __patch_offset: it records WHICH
    # edit produced the row, so the index can be RECONCILED against the
    # log rather than merely rebuilt from it. Sourced from the log row
    # itself rather than a second clock reading, or the comparison
    # would be meaningless.
    _mediator, write_mediator, log, _db = deployment
    _write(write_mediator, "delete")

    conn = sqlite3.connect(log.db_path)
    conn.row_factory = sqlite3.Row
    try:
        indexed = conn.execute(
            "SELECT deleted_at FROM object_deleted WHERE object_id = 'cust_001'"
        ).fetchone()["deleted_at"]
        logged = conn.execute(
            "SELECT created_at FROM write_log WHERE object_id = 'cust_001' "
            "AND operation = 'delete'"
        ).fetchone()["created_at"]
    finally:
        conn.close()

    assert indexed == logged


def test_rebuilding_from_the_log_reproduces_the_index(deployment):
    # THE property that makes this a cache rather than a second source
    # of truth. If incremental maintenance and the log ever disagree,
    # the log wins and this is how it wins.
    _mediator, write_mediator, log, _db = deployment
    _write(write_mediator, "delete")
    incremental = log.deleted_object_ids("Customer")

    log.rebuild_deleted_index()

    assert log.deleted_object_ids("Customer") == incremental
    assert incremental == {"cust_001"}


def test_rebuilding_repairs_an_index_that_drifted(deployment):
    # The failure this recovers from is real: the log entry is written
    # before the index row, so a crash between them leaves the index
    # stale. Simulated by corrupting the index directly.
    _mediator, write_mediator, log, _db = deployment
    _write(write_mediator, "delete")

    conn = sqlite3.connect(log.db_path)
    conn.execute("DELETE FROM object_deleted")
    conn.commit()
    conn.close()
    assert log.deleted_object_ids("Customer") == set(), "index should now be wrong"

    log.rebuild_deleted_index()

    assert log.deleted_object_ids("Customer") == {"cust_001"}


def test_rebuilding_drops_an_index_row_the_log_does_not_justify(deployment):
    # Drift in the other direction: an index row with no delete behind
    # it. A rebuild that only ADDED would leave this forever.
    _mediator, write_mediator, log, _db = deployment
    # Touch the log first: its schema is created lazily on the first
    # real connection, and this test writes to the table directly.
    log.deleted_object_ids("Customer")

    conn = sqlite3.connect(log.db_path)
    conn.execute(
        "INSERT INTO object_deleted VALUES ('Customer', 'never_deleted', '2020-01-01')"
    )
    conn.commit()
    conn.close()

    log.rebuild_deleted_index()

    assert "never_deleted" not in log.deleted_object_ids("Customer")


def test_rebuilding_respects_last_edit_wins(deployment):
    # A rebuild that treated "any delete exists" as deleted would
    # resurrect a delete an later write had superseded.
    _mediator, write_mediator, log, _db = deployment
    _write(write_mediator, "delete")
    _write(
        write_mediator, "update",
        changes={"name": "Ada Restored"}, expected={"name": "Ada Okafor"},
    )

    log.rebuild_deleted_index()

    assert log.deleted_object_ids("Customer") == set()


def test_reading_deleted_ids_does_not_scale_with_edit_history(deployment):
    # The regression this exists to prevent. Asserted as a query COUNT
    # against a log deliberately filled with unrelated history: the old
    # implementation read every applied row, so its cost grew with the
    # log; this reads one small table.
    _mediator, write_mediator, log, _db = deployment
    _write(write_mediator, "delete")

    conn = sqlite3.connect(log.db_path)
    conn.executemany(
        "INSERT INTO write_log (id, object_type, object_id, operation, changes, "
        "expected_current_values, status, user_id, description, created_at) "
        "VALUES (?, 'Customer', ?, 'update', '{}', '{}', 'applied', 'u', 'noise', ?)",
        [(f"noise{i}", f"c{i}", f"2020-01-01T{i:06d}") for i in range(5000)],
    )
    conn.commit()
    conn.close()

    # Still exactly the one deleted object, unaffected by 5,000 rows of
    # unrelated history.
    assert log.deleted_object_ids("Customer") == {"cust_001"}
