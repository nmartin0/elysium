"""
Bronze holds every source column, declared or not (PA001-A12).

THE FINDING SAYS THIS "REVERSES THE STATED POLICY". IT DOES NOT. The
policy states exactly this behaviour, in ELT_ROADMAP.md, with a
measurement beside it:

    Sync writes every column the source has, not only the declared
    ones; `columns_present()` already reports them, having been built
    for drift detection.

    Justified by lineage, not speed, and always was. Today a value
    that looks wrong has nothing to compare against except a source
    that may since have changed, and adding an ontology field means
    re-reading the source.

    A bronze layer costs about 1.8x storage. 20,000 rows, three
    declared columns versus all six: 177KB -> 327KB.

No other document says otherwise; I grepped for one. So the behaviour
is deliberate, measured and documented, and A12 is NOT REPRODUCED as
stated.

WHAT IS REAL, AND IS RECORDED NOWHERE. The decision was taken on
storage and lineage grounds. Its CONSEQUENCE was not written down:

    the ontology declares  id, name
    the source also holds  salary, ssn
    -> the SSN is in the lake, in a parquet file, in the clear

An undeclared column has no field grant, appears in no silver or gold
table, and is invisible to every read path -- and is nonetheless
copied to disk. OPEN_RISKS item 2 already says the lake directory is
part of the security perimeter: read access to it is read access to
everything in it, with no audit entry.

So "we only expose what the ontology declares" is true of the READ
PATHS and false of the LAKE. That gap is the finding, and it belongs
to the owner: the fix is either a declared opt-out per silo, encrypting
bronze at rest, or accepting it and saying so in the security
documentation. Recorded as NEW-5.

THE TESTS BELOW PIN TODAY'S BEHAVIOUR so the decision stays visible
and any change to it is deliberate.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync


@pytest.fixture
def synced(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE staff (id TEXT PRIMARY KEY, name TEXT, "
                 "salary TEXT, ssn TEXT)")
    conn.execute("INSERT INTO staff VALUES ('a','Ada','250000','123-45-6789')")
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "m",
                              {"p": SQLiteReadAdapter({"path": source})})
    # THE ONTOLOGY DECLARES ONLY id AND name.
    sync.sync_table("p", "staff", "id", ["id", "name"], {})
    return sync, tmp_path / "m"


def _columns(sync, table):
    return sorted(f.name for f in sync.catalog.load_table(table).schema().fields
                  if not f.name.startswith("_"))


class TestWhatEachLayerHolds:
    def test_bronze_holds_every_column(self, synced):
        """Deliberate: lineage needs the raw record, and adding a
        field later must not mean re-reading a source that has since
        changed."""
        sync, _ = synced

        assert _columns(sync, "bronze_p.staff") == ["id", "name", "salary", "ssn"]

    def test_silver_holds_only_the_declared_ones(self, synced):
        sync, _ = synced

        assert _columns(sync, "p.staff") == ["id", "name"]


class TestTheConsequenceNobodyWroteDown:
    def test_an_undeclared_value_is_on_disk_in_the_clear(self, synced):
        """NEW-5. Not a failure -- a fact, pinned so it cannot be
        forgotten. The SSN was never declared, is in no silver or gold
        table, and is invisible to every read path. It is also in a
        parquet file."""
        _, lake = synced

        found = [p for p in lake.rglob("*.parquet")
                 if b"123-45-6789" in p.read_bytes()]

        assert found, "the fixture no longer exercises the case"
        assert all("bronze" in str(p) for p in found), (
            "an undeclared value reached a layer other than bronze, which "
            "would be a different and worse finding")

    def test_it_reaches_no_read_path(self, synced):
        """The other half, and the reason this is a lake question
        rather than an access-control one: nothing serves it."""
        sync, _ = synced

        assert "ssn" not in _columns(sync, "p.staff")
