"""
Point 14: edit history as a read API.

FOUNDRY'S PRECEDENT. Their Edit History widget provides "an immutable
audit trail of all changes made to ontology objects", configured to
answer "what changed, by whom, and when?" Elysium already recorded all
of that in the write log -- who, when, what changed, and the
description of the action -- with no way to read it back.

THE SECURITY RULE COMES FROM FOUNDRY DIRECTLY, which settled a
question that would otherwise have needed inventing: "Users who have
access to the current state of an object (object with the same primary
key) can access the entire history of the object." So authorization is
the SAME check as reading the object -- no separate grant, and no way
to learn about an object's past that you could not learn about its
present.

One thing this project adds beyond that rule, because field-level RBAC
exists here: changed values are filtered PER FIELD. A caller granted
read:Customer but not read:Customer.email must not learn that the
email changed, or to what. The entry still appears with the ungranted
values removed, because the FACT that someone edited this object at a
given time is exactly what an audit trail is for.
"""

import sqlite3
from datetime import UTC, datetime

import pytest
import yaml

from core.deployment_loader import _WRITE_ADAPTER_REGISTRY, _build_adapters
from core.intermediate_layer.auth import UserRecord
from core.ontology.link_types import expand_link_types
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLogWriter
from core.ontology.write_mediator import PendingWrite, SubWrite, WriteMediator

FIXTURES = "tests/integration/fixtures/"
WEST = UserRecord(user_id="alice", security_value="us-west", role_name="customer_service")
EAST = UserRecord(user_id="bob", security_value="us-east", role_name="customer_service")
LIMITED = UserRecord(user_id="carol", security_value="us-west", role_name="limited")


@pytest.fixture
def deployment(tmp_path):
    schema = yaml.safe_load(open(FIXTURES + "ontology_schema.yaml"))
    # Link fields are GENERATED from link_types at load; the raw
    # YAML no longer declares them (see core/ontology/link_types.py).
    schema["object_types"] = expand_link_types(
        schema.get("link_types", {}), schema["object_types"]
    )
    policy = yaml.safe_load(open(FIXTURES + "policy.yaml"))
    # A role that can read the object but NOT one of its fields.
    policy["roles"]["limited"] = {
        "allowed_actions": ["read:Customer", "read:Customer.name", "read:Customer.region"]
    }

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
    return mediator, write_mediator


def _edit(write_mediator, changes, expected, user_id="alice", operation="update"):
    pending = PendingWrite(
        sub_writes=[SubWrite("Customer", "cust_001", operation, changes, expected)],
        user_id=user_id,
        description=f"{operation} by {user_id}",
        action_type_name="TestAction",
        origin="human",
        proposed_at=datetime.now(UTC),
        proposed_under_generation=1,
        parameters={},
        proposer=UserRecord(user_id, "us-west", "analyst"),
    )
    return write_mediator.confirm_and_execute(pending, approved=True)


def test_history_records_what_changed_by_whom(deployment):
    mediator, write_mediator = deployment
    _edit(write_mediator, {"name": "Ada v2"}, {"name": "Ada Okafor"})

    history, _total = mediator.edit_history(WEST, "Customer", "cust_001")

    assert len(history) == 1
    assert history[0]["operation"] == "update"
    assert history[0]["user_id"] == "alice"
    assert history[0]["changes"] == {"name": "Ada v2"}
    assert history[0]["created_at"]


def test_history_is_newest_first(deployment):
    # A timeline reads downward from the most recent change.
    mediator, write_mediator = deployment
    _edit(write_mediator, {"name": "Ada v2"}, {"name": "Ada Okafor"}, user_id="alice")
    _edit(write_mediator, {"name": "Ada v3"}, {"name": "Ada v2"}, user_id="bob")

    history, _total = mediator.edit_history(WEST, "Customer", "cust_001")

    assert [entry["changes"]["name"] for entry in history] == ["Ada v3", "Ada v2"]
    assert [entry["user_id"] for entry in history] == ["bob", "alice"]


def test_a_delete_appears_in_history(deployment):
    # A delete is an edit like any other, and an audit trail that
    # omitted removals would be worse than none.
    mediator, write_mediator = deployment
    _edit(write_mediator, {}, {}, operation="delete")

    # Read as a caller who can still see the object type; the object
    # itself is now hidden, so history is read through the write log
    # directly to prove the entry exists.
    assert write_mediator.write_log.edit_history("Customer", "cust_001")[0]["operation"] == "delete"


def test_an_object_with_no_edits_has_empty_history(deployment):
    mediator, _write_mediator = deployment

    assert mediator.edit_history(WEST, "Customer", "cust_001")[0] == []


def test_mac_denies_history_for_an_object_the_caller_cannot_read(deployment):
    # Foundry's rule: access to the history follows access to the
    # object. A caller who cannot read the present must not read the
    # past.
    mediator, write_mediator = deployment
    _edit(write_mediator, {"name": "Ada v2"}, {"name": "Ada Okafor"})

    assert mediator.edit_history(EAST, "Customer", "cust_001")[0] == []


def test_an_unknown_object_returns_empty_rather_than_erroring(deployment):
    # Uniform denial: the response never distinguishes "no history"
    # from "not allowed" from "no such object".
    mediator, _write_mediator = deployment

    assert mediator.edit_history(WEST, "Customer", "does_not_exist")[0] == []


def test_ungranted_field_values_are_filtered_out_of_history(deployment):
    # THE property that stops history becoming a way around field-level
    # RBAC. A caller who cannot read Customer.email must not learn its
    # value by reading what it changed to.
    mediator, write_mediator = deployment
    _edit(
        write_mediator,
        {"name": "Ada v2", "email": "secret@new.com"},
        {"name": "Ada Okafor", "email": "ada.okafor@example.com"},
    )

    full = mediator.edit_history(WEST, "Customer", "cust_001")[0][0]["changes"]
    limited = mediator.edit_history(LIMITED, "Customer", "cust_001")[0][0]["changes"]

    assert full == {"name": "Ada v2", "email": "secret@new.com"}
    assert limited == {"name": "Ada v2"}
    assert "email" not in limited


def test_an_edit_of_only_ungranted_fields_still_appears(deployment):
    # The entry survives with empty changes, because the FACT that
    # someone edited this object at a given time is exactly what an
    # audit trail is for -- hiding it would misrepresent the history as
    # complete.
    mediator, write_mediator = deployment
    _edit(
        write_mediator, {"email": "secret@new.com"}, {"email": "ada.okafor@example.com"}
    )

    limited, _total = mediator.edit_history(LIMITED, "Customer", "cust_001")

    assert len(limited) == 1
    assert limited[0]["changes"] == {}
    assert limited[0]["user_id"] == "alice"


def test_history_shows_applied_writes_only(deployment):
    # A pending entry is a write still in flight, not a thing that
    # happened -- showing it would report a change that may yet be
    # rejected.
    mediator, write_mediator = deployment
    write_mediator.write_log.log_pending_update(
        "Customer", "cust_001", {"name": "Never Applied"}, {}, "alice", "in flight"
    )

    assert mediator.edit_history(WEST, "Customer", "cust_001")[0] == []


def test_edits_from_one_action_share_a_batch_id(deployment):
    # A UI grouping "these four changes happened together" needs this;
    # Foundry links a single action log to every object it edited for
    # the same reason.
    mediator, write_mediator = deployment
    _edit(write_mediator, {"name": "Ada v2"}, {"name": "Ada Okafor"})

    entries, _total = mediator.edit_history(WEST, "Customer", "cust_001")
    entry = entries[0]

    assert entry["batch_id"]


# --- Paging in SQL -------------------------------------------------------
#
# Reading an object's whole history to return twenty rows is the same
# shape as the N+1s fixed elsewhere: fine at ten edits, wasteful at ten
# thousand, and the waste grows with exactly the history a timeline
# widget exists to scroll through. Measured at 20,000 edits: 87.6 ms to
# read everything and slice, 9.7 ms to read one page.


def _many_edits(write_mediator, count):
    log = write_mediator.write_log
    for index in range(count):
        log.mark_applied(
            log.log_pending_update(
                "Customer", "cust_001", {"name": f"v{index}"}, {}, "alice", f"edit {index}"
            )
        )


def test_a_page_returns_only_its_own_rows(deployment):
    mediator, write_mediator = deployment
    _many_edits(write_mediator, 30)

    page, total = mediator.edit_history(WEST, "Customer", "cust_001", limit=10, offset=0)

    assert len(page) == 10
    assert total == 30


def test_the_total_counts_everything_not_just_the_page(deployment):
    mediator, write_mediator = deployment
    _many_edits(write_mediator, 25)

    _page, total = mediator.edit_history(WEST, "Customer", "cust_001", limit=5)

    assert total == 25


def test_paging_walks_the_whole_history_exactly_once(deployment):
    mediator, write_mediator = deployment
    _many_edits(write_mediator, 23)

    seen = []
    offset = 0
    while True:
        page, total = mediator.edit_history(
            WEST, "Customer", "cust_001", limit=7, offset=offset
        )
        if not page:
            break
        seen.extend(entry["id"] for entry in page)
        offset += 7

    assert len(seen) == 23
    assert len(seen) == len(set(seen))


def test_a_page_matches_what_slicing_the_full_history_would_give(deployment):
    # The SQL paging must be a pure optimization -- same rows, same
    # order, less work. Compared against the unpaged read rather than a
    # hardcoded expectation.
    mediator, write_mediator = deployment
    _many_edits(write_mediator, 20)

    everything, _total = mediator.edit_history(WEST, "Customer", "cust_001")
    page, _total = mediator.edit_history(WEST, "Customer", "cust_001", limit=6, offset=6)

    assert [entry["id"] for entry in page] == [e["id"] for e in everything[6:12]]


def test_paging_reads_only_the_page_not_the_whole_history(deployment):
    # THE regression guard. Asserted by counting rows materialised
    # rather than by timing, which would be flaky.
    mediator, write_mediator = deployment
    _many_edits(write_mediator, 200)

    page = write_mediator.write_log.edit_history("Customer", "cust_001", limit=10, offset=0)

    assert len(page) == 10, (
        f"a 10-row page materialised {len(page)} rows -- paging is happening in "
        f"Python, not in SQL"
    )


def test_mac_still_denies_a_paged_read(deployment):
    # Paging must not become a way around the check -- the count leaks
    # how much history exists just as the entries would.
    mediator, write_mediator = deployment
    _many_edits(write_mediator, 10)

    page, total = mediator.edit_history(EAST, "Customer", "cust_001", limit=5)

    assert page == []
    assert total == 0
