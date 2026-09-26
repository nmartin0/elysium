"""
Changing a declared type has a path forward (PA001-A10).

WHAT HAPPENED. An operator changes one line of YAML -- `data_type:
string` to `integer` -- and the sync stops, permanently, with
pyiceberg's own message:

    ValidationError: Cannot change column type: amount: string -> long

Not the table. Not the declaration that caused it. Not a remedy.
Iceberg is right to refuse -- reinterpreting stored bytes is not a
schema edit -- but the deployment is then stuck, and nothing tells
anyone how to get unstuck.

THERE WAS A PATH ALL ALONG: drop the silver table and re-sync. BRONZE
IS UNTOUCHED, holding every raw value as text, so this is not a
re-read of a source that may have moved on. What it costs is silver's
snapshot history for that one table -- real, and not the same as
losing data.

So the sync now refuses with that remedy spelled out, and
`--rebuild silo.table` performs it. The flag exists for the same
reason `--accept-deletions` does: a destructive option should be
typed by a person who has read what it costs, not implied by a retry.

AND THE FIRST VERSION OF THIS FIX LEFT THE DEPLOYMENT HALF-WORKING,
which is the part worth keeping. Measured on a real deployment: silver
rebuilt correctly and gold then failed with "Mismatch in fields",
because `_columns_changed` compared NAMES ONLY -- deliberately, in its
own words: "a type change is a different problem, and the audit is
where that belongs". The audit does not handle it. An operator
following the printed instruction ended up with a working silver and a
broken gold, which is worse than being told nothing. Gold rebuilds on
a type change now; it is derived from silver, so it can.

SPELLINGS ARE NORMALISED in both places. Iceberg's Arrow round trip
returns `large_string` where we wrote `string`; without that, every
text column looked changed and the check fired on every second sync.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import DeclaredTypeChanged, IcebergMirrorSync


@pytest.fixture
def mirror(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, amount TEXT, note TEXT)")
    conn.execute("INSERT INTO t VALUES ('a','42','hello')")
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "m",
                              {"p": SQLiteReadAdapter({"path": source})})

    def run(amount_type, rebuild=None):
        return sync.sync_table("p", "t", "id", ["id", "amount", "note"],
                                {"amount": amount_type}, rebuild=rebuild)

    sync.run = run
    return sync


class TestAnUnchangedDeclaration:
    def test_a_second_sync_is_fine(self, mirror):
        """THE CHECK MUST NOT FIRE ON ITSELF. Iceberg returns
        `large_string` for what we wrote as `string`, and an
        unnormalised comparison refused every second sync."""
        mirror.run("string")

        mirror.run("string")

    def test_and_a_third(self, mirror):
        mirror.run("string")
        mirror.run("string")

        mirror.run("string")


class TestAChangedDeclaration:
    def test_it_is_refused(self, mirror):
        mirror.run("string")

        with pytest.raises(DeclaredTypeChanged):
            mirror.run("integer")

    def test_the_message_names_the_table_the_column_and_both_types(self, mirror):
        mirror.run("string")

        with pytest.raises(DeclaredTypeChanged) as raised:
            mirror.run("integer")

        message = str(raised.value)
        assert "p.t" in message
        assert "amount" in message
        assert "int64" in message

    def test_the_message_gives_the_remedy(self, mirror):
        """The whole finding is 'no path forward'. A refusal that does
        not say what to do leaves the operator exactly where they
        were."""
        mirror.run("string")

        with pytest.raises(DeclaredTypeChanged) as raised:
            mirror.run("integer")

        assert "--rebuild p.t" in str(raised.value)

    def test_the_mirror_is_left_as_it_was(self, mirror):
        """A refusal must not be a partial write."""
        mirror.run("string")

        with pytest.raises(DeclaredTypeChanged):
            mirror.run("integer")

        rows = mirror.catalog.load_table("p.t").scan().to_arrow().to_pylist()
        assert rows[0]["amount"] == "42"


class TestGoldFollowsSilver:
    """WRITTEN BECAUSE A CONTROL PROVED NOTHING. The tests above sync
    silver only, so making gold compare NAMES ONLY again -- the
    original half-fix -- changed none of them.

    This is the failure that was measured on a real deployment: silver
    rebuilt, gold said "Mismatch in fields", and the operator who
    followed our own printed instruction was left half-fixed."""

    def test_gold_rebuilds_when_a_declared_type_changes(self, mirror):
        from core.mirror.gold import build_gold

        type_def = {
            "id_field": "id", "security": {"field": "note"},
            "storage": {"silo": "p", "table": "t", "id_column": "id"},
            "fields": {"id": {"type": "data"},
                        "amount": {"type": "data", "data_type": "string"},
                        "note": {"type": "data"}},
        }
        mirror.run("string")
        silver = mirror.catalog.load_table("p.t").scan().to_arrow()
        assert build_gold(mirror.catalog, "Thing", type_def, silver).published

        mirror.run("integer", rebuild={"p.t"})
        type_def["fields"]["amount"]["data_type"] = "integer"
        silver = mirror.catalog.load_table("p.t").scan().to_arrow()

        assert build_gold(mirror.catalog, "Thing", type_def, silver).published
        types = {f.name: str(f.field_type)
                 for f in mirror.catalog.load_table("gold.Thing").schema().fields}
        assert types["amount"] == "long"

    def test_gold_does_not_rebuild_when_nothing_changed(self, mirror):
        """The other half: rebuilding gold every sync would discard a
        type's publication tags and its history for no reason."""
        from core.mirror.gold import build_gold

        type_def = {
            "id_field": "id", "security": {"field": "note"},
            "storage": {"silo": "p", "table": "t", "id_column": "id"},
            "fields": {"id": {"type": "data"},
                        "amount": {"type": "data", "data_type": "string"},
                        "note": {"type": "data"}},
        }
        mirror.run("string")
        silver = mirror.catalog.load_table("p.t").scan().to_arrow()
        build_gold(mirror.catalog, "Thing", type_def, silver)
        build_gold(mirror.catalog, "Thing", type_def, silver)

        tags = [n for n in mirror.catalog.load_table("gold.Thing").refs()
                if n.startswith("published-")]
        assert len(tags) == 2, (
            "gold was rebuilt when nothing changed, losing its earlier "
            "publication")


class TestTheRemedy:
    def test_rebuild_applies_the_new_type(self, mirror):
        mirror.run("string")

        mirror.run("integer", rebuild={"p.t"})

        types = {f.name: str(f.field_type)
                 for f in mirror.catalog.load_table("p.t").schema().fields}
        assert types["amount"] == "long"

    def test_the_rows_survive(self, mirror):
        mirror.run("string")

        mirror.run("integer", rebuild={"p.t"})

        rows = mirror.catalog.load_table("p.t").scan().to_arrow().to_pylist()
        assert rows[0]["amount"] == 42
        assert rows[0]["note"] == "hello"

    def test_bronze_is_untouched(self, mirror):
        """The reason this is safe: the raw record never moved."""
        mirror.run("string")
        before = len(mirror.catalog.load_table("bronze_p.t").snapshots())

        mirror.run("integer", rebuild={"p.t"})

        assert mirror.catalog.table_exists("bronze_p.t")
        assert len(mirror.catalog.load_table("bronze_p.t").snapshots()) >= before

    def test_it_only_rebuilds_the_table_named(self, mirror, tmp_path):
        """A rebuild flag that rebuilt everything would be a foot-gun
        rather than a remedy."""
        mirror.run("string")
        mirror.sync_table("p", "t", "id", ["id", "amount", "note"],
                           {"amount": "string"}, rebuild={"p.other"})

        rows = mirror.catalog.load_table("p.t").scan().to_arrow().to_pylist()
        assert rows[0]["amount"] == "42"
