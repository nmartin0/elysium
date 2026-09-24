"""
Building gold a batch at a time (GOLD-7's second half).

WHAT IS PROVEN HERE, AND WHAT IS NOT.

PROVEN: the streamed build produces the SAME TABLE as the materialised
one -- same schema, same rows -- and the streaming audit reports the
same findings, word for word, as the other two implementations. That
is the whole risk of the change: three implementations of one check
that must never disagree.

MEASURED, ON THE READ ALONE: reading 300,000 rows of six wide columns
costs +81.8 MB RSS materialised against +11.0 MB streamed, and the
11 MB is almost entirely the set of ids the audit keeps to find
duplicates -- so the residual is proportional to the number of
OBJECTS, not the width of their rows.

NOT PROVEN, AND SAID PLAINLY: an end-to-end saving. Measured cold, a
whole build peaked at 333 MB materialised against 321 streamed, and
the gap did not widen when the rows were made three times wider. The
write side and the allocator dominate, and a second build in the same
process peaked at 8 MB either way -- which says the instrument is
noisy, not that the build is free. The read-side saving is real; the
end-to-end one is not demonstrated, and this file does not assert it.
"""

import sqlite3

import pyarrow as pa
import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.gold import audit, build_gold, conform
from core.mirror.gold_arrow import audit_arrow, conform_arrow
from core.mirror.gold_stream import StreamingAudit
from core.mirror.iceberg_sync import IcebergMirrorSync

TYPE = {
    "id_field": "customer_id",
    "security": {"field": "region"},
    "storage": {"silo": "p", "table": "customers", "id_column": "cust_pk"},
    "fields": {
        "customer_id": {"type": "data", "column": "cust_pk"},
        "region": {"type": "data", "required": True},
        "name": {"type": "data"},
        "owner": {"type": "link", "target": "Staff", "cardinality": "one"},
    },
}
KNOWN = {"Staff": {"s1"}}


def _streamed_problems(rows, previous_count, known=KNOWN):
    accumulator = StreamingAudit(TYPE, known)
    for batch in conform_arrow(TYPE, pa.Table.from_pylist(rows)).to_batches():
        accumulator.add(batch)
    return sorted(accumulator.problems(previous_count))


class TestTheThreeAuditsAgree:
    """A check with three implementations is three chances to disagree,
    so every case is compared across all of them."""

    @pytest.mark.parametrize("rows, previous", [
        ([{"cust_pk": "c1", "region": "us-west", "name": "Ada", "owner": "s1"}], None),
        ([{"cust_pk": "c1", "region": "us-west", "owner": "s1"}], 1),
        # no id at all -- the case that found a bug in the table audit
        ([{"cust_pk": None, "region": "eu", "owner": None}], 10),
        # duplicates
        ([{"cust_pk": "c1", "region": "eu"}, {"cust_pk": "c1", "region": "eu"},
          {"cust_pk": "c2", "region": "eu"}], None),
        # a required property missing
        ([{"cust_pk": "c1", "region": None}], None),
        # a link pointing at nothing
        ([{"cust_pk": "c1", "region": "eu", "owner": "s9"}], None),
        # most of the rows gone
        ([{"cust_pk": "c1", "region": "eu"}], 100),
        # everything wrong at once
        ([{"cust_pk": None, "region": None, "owner": "s9"},
          {"cust_pk": "c1", "region": "eu"}, {"cust_pk": "c1", "region": "eu"}], 10),
    ])
    def test_word_for_word(self, rows, previous):
        from_dicts = sorted(audit(TYPE, conform(TYPE, rows), previous, KNOWN))
        from_table = sorted(audit_arrow(
            TYPE, conform_arrow(TYPE, pa.Table.from_pylist(rows)), previous, KNOWN))

        assert from_dicts == from_table == _streamed_problems(rows, previous)

    def test_a_duplicate_split_across_batches_is_still_found(self):
        """THE ONE THING A BATCH CANNOT ANSWER ALONE. Each batch here
        is clean; only the accumulation sees the repeat."""
        accumulator = StreamingAudit(TYPE, KNOWN)
        for value in ("c1", "c2", "c1"):
            table = pa.Table.from_pylist([{"cust_pk": value, "region": "eu"}])
            for batch in conform_arrow(TYPE, table).to_batches():
                accumulator.add(batch)

        problems = accumulator.problems(None)

        assert problems == ["1 duplicate customer_id(s): 'c1'"]

    def test_rows_are_counted_across_batches(self):
        accumulator = StreamingAudit(TYPE, KNOWN)
        for value in ("c1", "c2", "c3"):
            table = pa.Table.from_pylist([{"cust_pk": value, "region": "eu"}])
            for batch in conform_arrow(TYPE, table).to_batches():
                accumulator.add(batch)

        assert accumulator.rows == 3


@pytest.fixture
def mirrored(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE customers (cust_pk TEXT PRIMARY KEY, region TEXT, "
                 "name TEXT, amount TEXT)")
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?)",
                     [(f"c{i}", "us-west", f"Person {i}", f"{i}.75") for i in range(2_000)])
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": source})})
    columns = ["cust_pk", "region", "name", "amount"]
    sync.sync_table("p", "customers", "cust_pk", columns,
                    {**dict.fromkeys(columns, "string"), "amount": "decimal"})
    return sync


TYPED = {**TYPE, "fields": {**{k: v for k, v in TYPE["fields"].items() if k != "owner"},
                             "amount": {"type": "data", "data_type": "decimal"}}}


class TestTheStreamedBuildMatches:
    def test_the_same_rows_are_published(self, mirrored):
        silver = mirrored._catalog.load_table("p.customers")

        materialised = build_gold(mirrored._catalog, "Whole", TYPED, silver.scan().to_arrow())
        streamed = build_gold(mirrored._catalog, "Streamed", TYPED,
                               silver.scan().to_arrow_batch_reader())

        assert materialised.published and streamed.published
        assert materialised.rows == streamed.rows == 2_000
        whole = mirrored._catalog.load_table("gold.Whole").scan().to_arrow().to_pylist()
        part = mirrored._catalog.load_table("gold.Streamed").scan().to_arrow().to_pylist()
        assert sorted(whole, key=lambda row: row["customer_id"]) == \
            sorted(part, key=lambda row: row["customer_id"])

    def test_AND_THE_SAME_SCHEMA(self, mirrored):
        """THE BUG THIS CAUGHT: lineage columns came back as
        large_string from a batch reader and string from a materialised
        scan, so gold's schema depended on HOW silver was read -- and
        the next build, reading it the other way, would have seen a
        changed column set and rebuilt the table."""
        silver = mirrored._catalog.load_table("p.customers")
        build_gold(mirrored._catalog, "Whole", TYPED, silver.scan().to_arrow())
        build_gold(mirrored._catalog, "Streamed", TYPED,
                    silver.scan().to_arrow_batch_reader())

        whole = mirrored._catalog.load_table("gold.Whole").scan().to_arrow().schema
        part = mirrored._catalog.load_table("gold.Streamed").scan().to_arrow().schema

        assert whole.equals(part)

    def test_a_failing_audit_still_refuses(self, mirrored):
        """The audit runs while the batches go past, so a build that
        should be refused must still be refused."""
        silver = mirrored._catalog.load_table("p.customers")
        strict = {**TYPED, "fields": {**TYPED["fields"],
                                       "missing": {"type": "data", "required": True}}}

        result = build_gold(mirrored._catalog, "Refused", strict,
                             silver.scan().to_arrow_batch_reader())

        assert not result.published
        assert "missing required missing" in result.problems[0]

    def test_the_row_count_comes_from_the_stream(self, mirrored):
        silver = mirrored._catalog.load_table("p.customers")

        result = build_gold(mirrored._catalog, "Counted", TYPED,
                             silver.scan().to_arrow_batch_reader())

        assert result.rows == 2_000
