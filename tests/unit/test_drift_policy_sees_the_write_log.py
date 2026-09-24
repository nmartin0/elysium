"""
The drift policy asks the write log a question it can answer
(PA001-A1).

THE WRITE LOG IS KEYED BY OBJECT TYPE. The sync works in TABLES. It
asked using the table name, so `customers` returned zero where
`Customer` had one pending write -- and zero edits means ABSORB. A
column with an unapplied write against it was dropped from the
ontology's view without a word.

THE COMMENT MADE TWO CLAIMS, BOTH FALSE:

    # They coincide in every deployment written so far, and where
    # they do not the count comes back zero -- which REFUSES nothing,
    # because zero edits means absorb. Wrong in the safe direction

The shipped ontology has Customer in `customers` and Transaction in
`transactions`, so they coincide in NONE of them. And absorbing is the
PERMISSIVE outcome: it strands exactly the pending writes that
verdict_for_removed_column exists to protect. Wrong in the unsafe
direction, in the one deployment we ship.

THE ANSWER WAS ALREADY IN HAND. resolve_sync_targets walks the
ontology to build fields_by_column; the object type is right there in
the same loop and was being thrown away. A frozenset rather than one
name, because two types genuinely can share a table -- which that same
function already handles for columns -- and a pending write on either
is a reason to refuse.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.sync_targets import resolve_sync_targets
from core.ontology.write_log import WriteLogWriter

COLUMNS = ["customer_id", "name", "tier"]
FIELDS = {"name": "name", "tier": "tier"}


@pytest.fixture
def deployment(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE customers (customer_id TEXT, name TEXT, tier TEXT)")
    conn.execute("INSERT INTO customers VALUES ('c1','Ada','gold')")
    conn.commit()
    conn.close()
    write_log = WriteLogWriter(tmp_path / "write_log.db")
    sync = IcebergMirrorSync(tmp_path / "m", {"primary": SQLiteReadAdapter({"path": source})},
                              write_log=write_log)

    def run(object_types=frozenset({"Customer"})):
        return sync.sync_table("primary", "customers", "customer_id", COLUMNS, {},
                                fields_by_column=FIELDS, object_types=object_types)

    def drop_tier():
        conn = sqlite3.connect(source)
        conn.execute("ALTER TABLE customers DROP COLUMN tier")
        conn.commit()
        conn.close()

    sync.run, sync.drop_tier, sync.write_log = run, drop_tier, write_log
    return sync


class TestAPendingWriteProtectsItsColumn:
    def test_a_removed_column_with_a_pending_write_is_refused(self, deployment):
        """THE REGRESSION TEST. The type is Customer; the table is
        customers; asking by table name returned zero."""
        deployment.write_log.log_pending_update(
            "Customer", "c1", {"tier": "platinum"}, {"tier": "gold"}, "u1", "upgrade")
        deployment.run()
        deployment.drop_tier()

        with pytest.raises(ValueError, match="pending"):
            deployment.run()

    def test_an_APPLIED_write_counts_too(self, deployment):
        """An applied write is a value a user was told was saved. The
        column backing it vanishing is no less serious."""
        log_id = deployment.write_log.log_pending_update(
            "Customer", "c1", {"tier": "platinum"}, {"tier": "gold"}, "u1", "upgrade")
        deployment.write_log.mark_applied(log_id)
        deployment.run()
        deployment.drop_tier()

        with pytest.raises(ValueError, match="applied"):
            deployment.run()

    def test_with_no_write_at_all_the_removal_is_still_absorbed(self, deployment):
        """The permissive path is CORRECT when nothing is at stake, and
        the fix must not turn every schema change into an outage."""
        deployment.run()
        deployment.drop_tier()

        result = deployment.run()

        assert result.row_count == 1

    def test_a_write_on_a_DIFFERENT_field_does_not_protect_this_one(self, deployment):
        """Otherwise any edit anywhere would freeze every column."""
        deployment.write_log.log_pending_update(
            "Customer", "c1", {"name": "Ada L."}, {"name": "Ada"}, "u1", "rename")
        deployment.run()
        deployment.drop_tier()

        assert deployment.run().row_count == 1


class TestTablesSharedByTwoTypes:
    def test_the_targets_carry_every_owning_type(self):
        schema = {"object_types": {
            "Customer": {"storage": {"silo": "p", "table": "customers",
                                      "id_column": "cid"},
                          "id_field": "cid", "fields": {"name": {"type": "data"}}},
            "Account": {"storage": {"silo": "p", "table": "customers",
                                     "id_column": "cid"},
                         "id_field": "cid", "fields": {"tier": {"type": "data"}}},
        }}

        (target,) = resolve_sync_targets(schema)

        assert target.object_types == frozenset({"Customer", "Account"})

    def test_a_pending_write_on_EITHER_type_refuses(self, deployment):
        """Summed across types, because a write against the second one
        is just as stranded as against the first."""
        deployment.write_log.log_pending_update(
            "Account", "c1", {"tier": "platinum"}, {"tier": "gold"}, "u1", "upgrade")
        types = frozenset({"Customer", "Account"})
        deployment.run(types)
        deployment.drop_tier()

        with pytest.raises(ValueError, match="pending"):
            deployment.run(types)


    def test_EVERY_type_is_asked_not_just_the_first(self, deployment):
        """WRITTEN BECAUSE A CONTROL PROVED NOTHING. Asking only the
        first type (sorted) still passed, because the one multi-type
        test above happened to put its write on "Account", which sorts
        first. The write goes on "Customer" here, so a fix that stops
        after one type absorbs the removal."""
        deployment.write_log.log_pending_update(
            "Customer", "c1", {"tier": "platinum"}, {"tier": "gold"}, "u1", "upgrade")
        types = frozenset({"Customer", "Account"})
        deployment.run(types)
        deployment.drop_tier()

        with pytest.raises(ValueError, match="pending"):
            deployment.run(types)

    def test_the_counts_are_SUMMED_across_types(self, deployment):
        """AND THE OTHER CONTROL THAT PROVED NOTHING. Overwriting
        instead of summing still refused, because one write is enough
        to refuse. The COUNT is what differs, and an operator reading
        "1 pending write" when two are stranded is being told something
        false about how much work is at stake."""
        for object_type in ("Customer", "Account"):
            deployment.write_log.log_pending_update(
                object_type, "c1", {"tier": "platinum"}, {"tier": "gold"}, "u1", "x")
        types = frozenset({"Customer", "Account"})
        deployment.run(types)
        deployment.drop_tier()

        with pytest.raises(ValueError, match="2 pending"):
            deployment.run(types)


class TestTheOldBehaviourWhenNobodySays:
    def test_a_caller_that_passes_no_types_falls_back_to_the_table_name(self, deployment):
        """Older callers and tests that build a sync directly. No worse
        than before, and the shipped path passes them."""
        deployment.write_log.log_pending_update(
            "Customer", "c1", {"tier": "platinum"}, {"tier": "gold"}, "u1", "upgrade")
        deployment.run(object_types=frozenset())
        deployment.drop_tier()

        assert deployment.run(object_types=frozenset()).row_count == 1
