"""
Gold answers what the SOURCE DATABASE says, not merely what the
mirror says (PA001-G2).

THE GAP THIS CLOSES. tests/unit/test_gold_parity.py compares gold
against the MIRROR, and until now its mediator variable was even
called `from_source`. Both are Elysium's own copies: they can agree
with each other and both be wrong about the customer's database. The
audit put it exactly -- the parity test runs "on a schema with no m2m
and no cross-silo field, so it cannot see A2 or G1" -- and that is not
a hypothetical, because A2 and G1 were both real and both survived it.

SO THIS FILE COMPARES GOLD AGAINST SQLITE ITSELF, on a schema built
from the two shapes the old one lacked:

    a CROSS-SILO field   Customer.score, living in another database
    the fused result      one gold row carrying both silos' columns

A many-to-many link is covered separately, in
test_gold_serves_many_to_many_links.py.

WHAT GOOD IT DOES. Gold agreeing with silver proves the COPY was
faithful. Only comparing against the source proves the ANSWER is, and
that is the only question a person reading an object cares about.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.intermediate_layer.auth import UserRecord
from core.mirror.gold import build_gold, published_snapshot_ids
from core.mirror.gold_connector import GoldConnector
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.ontology.gold_view import build_gold_view
from core.ontology.mediator import DataMediator

CUSTOMERS = [("c1", "Ada", "us-west"), ("c2", "Bram", "us-west"),
              ("c3", "Chidi", "us-east")]
SCORES = [("c1", "0.35"), ("c2", "0.90"), ("c3", "0.10")]

SCHEMA = {
    "Customer": {
        "id_field": "id", "security": {"field": "region"},
        "storage": {"silo": "p", "table": "customers", "id_column": "id"},
        "additional_storage": {"risk": {"silo": "q", "table": "risk",
                                         "id_column": "id"}},
        "fields": {"id": {"type": "data"}, "name": {"type": "data"},
                    "region": {"type": "data"},
                    "score": {"type": "data", "storage": "risk"}},
    }
}
WEST = UserRecord(user_id="w", security_value="us-west", role_name="r")


@pytest.fixture
def both(tmp_path):
    """One question, asked of SQLite and of gold."""
    primary, risk = tmp_path / "a.db", tmp_path / "b.db"
    conn = sqlite3.connect(primary)
    conn.execute("CREATE TABLE customers (id TEXT PRIMARY KEY, name TEXT, region TEXT)")
    conn.executemany("INSERT INTO customers VALUES (?,?,?)", CUSTOMERS)
    conn.commit()
    conn.close()
    conn = sqlite3.connect(risk)
    conn.execute("CREATE TABLE risk (id TEXT PRIMARY KEY, score TEXT)")
    conn.executemany("INSERT INTO risk VALUES (?,?)", SCORES)
    conn.commit()
    conn.close()

    adapters = {"p": SQLiteReadAdapter({"path": primary}),
                "q": SQLiteReadAdapter({"path": risk})}
    sync = IcebergMirrorSync(tmp_path / "m", adapters)
    sync.sync_table("p", "customers", "id", ["id", "name", "region"], {})
    sync.sync_table("q", "risk", "id", ["id", "score"], {})

    silver = sync.catalog.load_table("p.customers").scan().to_arrow().to_pylist()
    extra = {"risk": sync.catalog.load_table("q.risk").scan().to_arrow().to_pylist()}
    assert build_gold(sync.catalog, "Customer", SCHEMA["Customer"], silver,
                       additional_rows=extra).published

    grants = ["read:Customer"] + [f"read:Customer.{f}"
                                   for f in SCHEMA["Customer"]["fields"]]
    roles = {"r": {"allowed_actions": grants}}
    view, excluded = build_gold_view(SCHEMA)
    assert excluded == {}, "a cross-silo type was dropped from the gold view"

    return {
        "source": DataMediator(SCHEMA, adapters, {"Customer": "p"}, roles),
        "gold": DataMediator(view, {"gold": GoldConnector(
            sync.catalog, published_snapshot_ids(sync.catalog, view))},
            {"Customer": "gold"}, roles),
    }


class TestGoldEqualsTheSource:
    @pytest.mark.parametrize("object_id", ["c1", "c2"])
    @pytest.mark.parametrize("field", ["name", "region", "score"])
    def test_every_field_of_every_visible_object(self, both, object_id, field):
        source = both["source"].get_field(WEST, "Customer", object_id, field)
        gold = both["gold"].get_field(WEST, "Customer", object_id, field)

        assert gold == source
        assert source is not None, "the fixture is empty; the test proves nothing"

    def test_the_CROSS_SILO_field_in_particular(self, both):
        """The shape the old parity test did not have. `score` lives
        in a different database from the rest of the object."""
        source = both["source"].get_field(WEST, "Customer", "c1", "score")
        gold = both["gold"].get_field(WEST, "Customer", "c1", "score")

        assert gold == source == "0.35"

    def test_get_object_returns_both_silos_columns_together(self, both):
        source = both["source"].get_object(WEST, "Customer", "c1",
                                            ["name", "score"])
        gold = both["gold"].get_object(WEST, "Customer", "c1", ["name", "score"])

        assert gold == source == {"name": "Ada", "score": "0.35"}

    def test_search_agrees(self, both):
        source = sorted(both["source"].search_object(WEST, "Customer"))
        gold = sorted(both["gold"].search_object(WEST, "Customer"))

        assert gold == source == ["c1", "c2"]

    def test_a_filter_on_the_cross_silo_field_agrees(self, both):
        """Filtering on a column that came from the OTHER database is
        where a fused table most easily disagrees with its sources."""
        from core.filters import FieldFilter

        condition = [FieldFilter("score", "equals", "0.90")]
        source = sorted(both["source"].search_object(WEST, "Customer", condition))
        gold = sorted(both["gold"].search_object(WEST, "Customer", condition))

        assert gold == source == ["c2"]

    def test_MAC_agrees(self, both):
        """c3 is us-east. Security is resolved from values in the rows,
        so it has to survive the fusion and the rebinding too."""
        assert both["source"].get_object(WEST, "Customer", "c3", ["name"]) == {
            "name": None}
        assert both["gold"].get_object(WEST, "Customer", "c3", ["name"]) == {
            "name": None}


class TestTheOldParityTestSaysWhatItDoes:
    def test_it_no_longer_calls_the_mirror_the_source(self):
        """PA001-G2's real harm was not the missing coverage but the
        NAME: a mediator built on MirrorReadAdapter was called
        `from_source`, so the file read as though it compared against
        the database."""
        from pathlib import Path

        lines = Path("tests/unit/test_gold_parity.py").read_text().splitlines()
        # CODE, NOT PROSE: that file's own docstring explains the
        # rename, so it mentions the old name on purpose.
        code = [ln for ln in lines if "from_source" in ln
                and not ln.lstrip().startswith("#")
                and "`from_source`" not in ln]

        assert code == [], f"the mirror is still called the source: {code}"
        assert any("from_mirror" in ln for ln in lines)
