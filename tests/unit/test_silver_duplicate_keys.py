"""
Two rows claiming one identity (GOLD-1's third stage,
MEDALLION_PIPELINE.md's S4).

WHY IT IS NOT AN ORDINARY EXPECTATION: every other rule is about one
row's values; this is about two rows disagreeing about who they are. An
object type is BACKED BY a table keyed on its id, and Foundry fails an
indexing run outright on a duplicate primary key, because the ontology
cannot say which row the object is.

THE DEFAULT HOLDS EVERY COPY and names the key. Keeping one silently
would pick a winner nobody chose, and the row that lost might be the
true one.
"""

import sqlite3

import pytest
from pyiceberg.exceptions import NoSuchTableError

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.duplicates import (
    DuplicateKeys,
    DuplicatePolicy,
    policy_for_storage,
    split_duplicates,
)
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.sync_targets import resolve_sync_targets

TWICE = [{"id": "a", "v": 1}, {"id": "a", "v": 2}, {"id": "b", "v": 3}]


class TestTheDefault:
    def test_every_copy_is_held_and_the_unique_row_kept(self):
        kept, held = split_duplicates(TWICE, "id", DuplicatePolicy())

        assert [row["id"] for row in kept] == ["b"]
        assert [row["id"] for row, _, _ in held] == ["a", "a"]

    def test_the_reason_names_the_key_and_how_many(self):
        _, held = split_duplicates(TWICE, "id", DuplicatePolicy())

        assert "duplicate id 'a'" in held[0][2] and "2 rows" in held[0][2]


class TestFail:
    def test_the_build_stops_and_names_the_keys(self):
        with pytest.raises(DuplicateKeys, match="duplicate key\\(s\\) 'a'"):
            split_duplicates(TWICE, "id", DuplicatePolicy("fail"))

    def test_it_says_the_mirror_is_unchanged(self):
        with pytest.raises(DuplicateKeys, match="mirror is unchanged"):
            split_duplicates(TWICE, "id", DuplicatePolicy("fail"))

    def test_no_duplicates_is_not_a_failure(self):
        kept, held = split_duplicates([{"id": "a"}], "id", DuplicatePolicy("fail"))

        assert len(kept) == 1 and not held


class TestKeepLastBy:
    def test_the_later_copy_survives_and_the_other_is_recorded(self):
        kept, held = split_duplicates(TWICE, "id", DuplicatePolicy("keep_last_by", "v"))

        assert sorted((row["id"], row["v"]) for row in kept) == [("a", 2), ("b", 3)]
        assert [(row["id"], row["v"]) for row, _, _ in held] == [("a", 1)]

    def test_it_compares_by_value_not_by_text(self):
        """repr() would order 10 before 9."""
        rows = [{"id": "a", "v": 9}, {"id": "a", "v": 10}]

        kept, _ = split_duplicates(rows, "id", DuplicatePolicy("keep_last_by", "v"))

        assert kept[0]["v"] == 10

    @pytest.mark.parametrize("rows, why", [
        ([{"id": "a", "v": 5}, {"id": "a", "v": 5}], "a tie"),
        ([{"id": "a", "v": None}, {"id": "a", "v": 2}], "a missing ordering value"),
        ([{"id": "a", "v": 1}, {"id": "a", "v": "2"}], "mixed types"),
    ])
    def test_what_it_cannot_decide_falls_back_to_holding_every_copy(self, rows, why):
        kept, held = split_duplicates(rows, "id", DuplicatePolicy("keep_last_by", "v"))

        assert not kept and len(held) == 2, why


class TestDeclaringIt:
    @pytest.mark.parametrize("declared, action", [
        ({}, "quarantine"),
        ({"duplicate_keys": "quarantine"}, "quarantine"),
        ({"duplicate_keys": "fail"}, "fail"),
        ({"duplicate_keys": {"keep_last_by": "updated_at"}}, "keep_last_by"),
    ])
    def test_what_a_storage_block_can_say(self, declared, action):
        assert policy_for_storage(declared).action == action

    @pytest.mark.parametrize("declared", [
        {"duplicate_keys": "quarentine"},
        {"duplicate_keys": {"keep_last_by": ""}},
        {"duplicate_keys": {"keep_first_by": "x"}},
        {"duplicate_keys": ["fail"]},
    ])
    def test_anything_else_is_refused(self, declared):
        with pytest.raises(ValueError, match="duplicate_keys"):
            policy_for_storage(declared)

    def test_it_reaches_the_sync_target_and_names_the_table(self):
        schema = {"object_types": {"Customer": {
            "id_field": "customer_id",
            "storage": {"silo": "s", "table": "customers", "id_column": "customer_id",
                        "duplicate_keys": "fail"},
            "security": {"field": "region"},
            "fields": {"region": {"type": "data"}},
        }}}

        assert resolve_sync_targets(schema)[0].duplicate_policy.action == "fail"

    def test_a_bad_declaration_names_the_table(self):
        schema = {"object_types": {"Customer": {
            "id_field": "customer_id",
            "storage": {"silo": "s", "table": "customers", "id_column": "customer_id",
                        "duplicate_keys": "nope"},
            "security": {"field": "region"},
            "fields": {"region": {"type": "data"}},
        }}}

        with pytest.raises(ValueError, match="'customers'"):
            resolve_sync_targets(schema)


class TestThroughTheSync:
    @pytest.fixture
    def synced(self, tmp_path):
        source = tmp_path / "s.db"
        conn = sqlite3.connect(source)
        # No PRIMARY KEY, so the source can hold the duplicate a real
        # one arrives with: a view, an export, a join gone wrong.
        conn.execute("CREATE TABLE t (id TEXT, region TEXT)")
        conn.executemany("INSERT INTO t VALUES (?,?)",
                         [("a", "us-west"), ("a", "us-east"), ("b", "us-west")])
        conn.commit()
        conn.close()
        return IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": source})})

    def _sync(self, sync, policy):
        return sync.sync_table("p", "t", "id", ["id", "region"],
                               {"id": "string", "region": "string"},
                               duplicate_policy=policy)

    def test_the_duplicated_object_is_not_in_silver(self, synced):
        result = self._sync(synced, DuplicatePolicy())

        assert result.row_count == 1 and result.quarantined == 2
        rows = synced._catalog.load_table("p.t").scan().to_arrow().to_pylist()
        assert [row["id"] for row in rows] == ["b"]

    def test_both_copies_are_recorded_by_key(self, synced):
        self._sync(synced, DuplicatePolicy())

        held = synced._catalog.load_table("quarantine_p.t").scan().to_arrow().to_pylist()
        assert [h["object_id"] for h in held] == ["a", "a"]
        assert all("duplicate id" in h["reason"] for h in held)

    def test_and_both_stay_in_bronze(self, synced):
        self._sync(synced, DuplicatePolicy())

        bronze = synced._catalog.load_table("bronze_p.t").scan().to_arrow().to_pylist()
        assert sorted(row["id"] for row in bronze) == ["a", "a", "b"]

    def test_fail_leaves_the_mirror_unchanged(self, synced):
        with pytest.raises(DuplicateKeys):
            self._sync(synced, DuplicatePolicy("fail"))

        # NAMED, not a blind Exception: "anything went wrong" would
        # pass for a typo in the table name too.
        with pytest.raises(NoSuchTableError):
            synced._catalog.load_table("p.t")
