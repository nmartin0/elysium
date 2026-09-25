"""
Both gold paths type an id the same way (PA001-G6, PA001-G7).

TWO PATHS BUILD GOLD. `_arrow` takes dicts and is the only one that
can fuse several storages; `conform_arrow` works on Arrow buffers and
is the streaming path. They disagreed about one column.

    declared:  id, data_type integer
    streaming: id -> string
    dict path: id -> int64

WORSE ON A FUSED TYPE, where the dict path is the only one available.
Fusion writes ids as TEXT -- "keys are compared as text everywhere
else in this system", as that file has always said -- and the schema
then claimed int64, so the build CRASHED:

    ArrowInvalid: Could not convert '7' with type str: tried to
    convert to int64

A type with an integer id and a second storage could not be published
at all. That is more than the audit reported, and it is the reason
this is a defect rather than a tidiness question.

TEXT IS THE RIGHT ANSWER, not merely the consistent one. The gold
connector looks rows up with `literal=str(object_id)`, so an int64 id
column would match NOTHING even if the build succeeded -- every read
of that type would return None while the data sat there.

PA001-G7 RIDES ON THIS. The link audit compares ids without
normalising type, which is latent only while both sides are text.
Fixing G6 in the other direction -- making ids integers -- would have
made it live immediately. A test below pins that both sides stay text.
"""

import sqlite3

import pyarrow as pa
import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.gold import _arrow, build_gold, published_snapshot_ids
from core.mirror.gold_arrow import conform_arrow
from core.mirror.gold_connector import GoldConnector
from core.mirror.iceberg_sync import IcebergMirrorSync

TYPE = {
    "id_field": "id", "security": {"field": "v"},
    "storage": {"silo": "q", "table": "n", "id_column": "id"},
    "fields": {"id": {"type": "data", "data_type": "integer"},
                "qty": {"type": "data", "data_type": "integer"},
                "v": {"type": "data"}},
}
LINEAGE = {"_silo": "q", "_source_table": "n", "_row_hash": "h"}


def _types(table):
    return {f.name: str(f.type) for f in table.schema if not f.name.startswith("_")}


class TestTheTwoPathsAgree:
    def test_on_the_id_column(self):
        """THE REGRESSION TEST: string from one, int64 from the
        other."""
        rows = [{"id": 7, "qty": 42, "v": "x", **LINEAGE}]
        silver = pa.table({"id": [7], "qty": [42], "v": ["x"],
                            "_silo": ["q"], "_source_table": ["n"],
                            "_row_hash": ["h"]})

        assert _types(_arrow(rows, TYPE))["id"] == \
            _types(conform_arrow(TYPE, silver))["id"] == "string"

    def test_and_on_every_other_column(self, ):
        """An ordinary declared integer must NOT become text -- that
        was patch 370's fix and this must not undo it."""
        rows = [{"id": 7, "qty": 42, "v": "x", **LINEAGE}]
        silver = pa.table({"id": [7], "qty": [42], "v": ["x"],
                            "_silo": ["q"], "_source_table": ["n"],
                            "_row_hash": ["h"]})

        assert _types(_arrow(rows, TYPE)) == _types(conform_arrow(TYPE, silver))
        assert _types(_arrow(rows, TYPE))["qty"] == "int64"


class TestAFusedTypeWithAnIntegerId:
    """The case that crashed. The dict path is the ONLY path for a
    fused type, so there was no way to publish one at all."""

    @pytest.fixture
    def fused(self, tmp_path):
        primary, extra = tmp_path / "a.db", tmp_path / "b.db"
        conn = sqlite3.connect(primary)
        conn.execute("CREATE TABLE n (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO n VALUES (7,'x')")
        conn.commit()
        conn.close()
        conn = sqlite3.connect(extra)
        conn.execute("CREATE TABLE extra (id INTEGER PRIMARY KEY, note TEXT)")
        conn.execute("INSERT INTO extra VALUES (7,'hello')")
        conn.commit()
        conn.close()
        type_def = {
            "id_field": "id", "security": {"field": "v"},
            "storage": {"silo": "p", "table": "n", "id_column": "id"},
            "additional_storage": {"more": {"silo": "q", "table": "extra",
                                             "id_column": "id"}},
            "fields": {"id": {"type": "data", "data_type": "integer"},
                        "v": {"type": "data"},
                        "note": {"type": "data", "storage": "more"}},
        }
        sync = IcebergMirrorSync(tmp_path / "m", {
            "p": SQLiteReadAdapter({"path": primary}),
            "q": SQLiteReadAdapter({"path": extra})})
        sync.sync_table("p", "n", "id", ["id", "v"], {"id": "integer"})
        sync.sync_table("q", "extra", "id", ["id", "note"], {"id": "integer"})
        return sync, type_def

    def _publish(self, sync, type_def):
        return build_gold(
            sync.catalog, "N", type_def,
            sync.catalog.load_table("p.n").scan().to_arrow().to_pylist(),
            additional_rows={"more": sync.catalog.load_table("q.extra")
                              .scan().to_arrow().to_pylist()})

    def test_it_publishes_at_all(self, fused):
        sync, type_def = fused

        assert self._publish(sync, type_def).published

    def test_and_a_lookup_by_that_id_answers(self, fused):
        """The second half. An int64 id column would match nothing,
        because the connector looks up with str(object_id) -- so the
        type would have built and then returned None for everything."""
        sync, type_def = fused
        self._publish(sync, type_def)
        connector = GoldConnector(
            sync.catalog, published_snapshot_ids(sync.catalog, {"N": type_def}))
        config = {"storage": {"table": "N", "id_column": "id"}, "fields": {}}

        assert connector.get_raw_field("N", 7, "v", config) == "x"
        assert connector.get_raw_field("N", 7, "note", config) == "hello"

    def test_the_id_is_stored_as_text(self, fused):
        sync, type_def = fused
        self._publish(sync, type_def)

        table = sync.catalog.load_table("gold.N")
        assert [str(f.field_type) for f in table.schema().fields
                if f.name == "id"] == ["string"]


class TestG7StaysLatent:
    def test_ids_and_links_are_both_text(self):
        """PA001-G7: the link audit compares ids without normalising
        type. That is harmless only while BOTH sides are text.

        Fixing G6 the other way -- making ids integers -- would have
        made G7 live the same day, with a link check silently
        disagreeing with itself. This asserts the condition G7 depends
        on, so a future change has to notice."""
        type_def = {
            "id_field": "id", "security": {"field": "v"},
            "storage": {"silo": "q", "table": "n", "id_column": "id"},
            "fields": {"id": {"type": "data", "data_type": "integer"},
                        "v": {"type": "data"},
                        "owner": {"type": "link", "target": "Other"}},
        }
        rows = [{"id": 7, "v": "x", "owner": 3, **LINEAGE}]

        types = _types(_arrow(rows, type_def))

        assert types["id"] == "string"
        assert types["owner"] == "string"
