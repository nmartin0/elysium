"""
A source column NAME is a name, never SQL (PA001-A7).

THE AUDIT REPORTED FOUR DISTINCT FAILURES from interpolating column
names into the bronze read: a reserved word ("group") broke the sync; a
name with a space ("unit price") parsed as an ALIAS; a hyphenated name
("a-b") parsed as the EXPRESSION a minus b, reported as "column 'a' is
missing"; and a name shaped like a subquery was EXECUTED, reading a
table the ontology never referenced.

ALL FOUR ARE ALREADY FIXED, by LIB-3 (patch 390), which routed every
SQL site in the SQLite adapter through
sqlite_dialect().identifier_preparer.quote(). This file is the
regression test that work never had for the BRONZE path specifically --
LIB-3 was driven by find_ids, and read_all_rows is a different
function with the same hazard.

VERIFIED HERE, NOT ASSUMED: each of the four shapes, plus a
deliberately malicious one, run through the adapter's real bulk read.

AND ONE HAZARD WORTH KNOWING ABOUT. SQLite treats an unknown
double-quoted identifier as a STRING LITERAL rather than an error:

    SELECT "nosuchcolumn" FROM t   ->  ('nosuchcolumn',)

So quoting, which is what makes the four cases above safe, also means
a MISSPELLED column would silently yield its own name as a constant
value for every row. Nothing in the adapter prevents that. What
prevents it is the drift check one layer up, which compares declared
columns against columns_present and refuses the table before any read
happens. The last class here pins that dependency, because it is not
obvious from either layer alone.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync

AWKWARD = {
    "group": "g",            # a reserved word
    "unit price": "9.99",    # a space: parsed as an alias
    "a-b": "ab",             # a hyphen: parsed as subtraction
    "order by": "x",         # two reserved words
    'say "hi"': "quoted",    # an embedded quote
}


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "s.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE secrets (k TEXT)")
    conn.execute("INSERT INTO secrets VALUES ('TOPSECRET')")
    columns = ", ".join(f'"{name.replace(chr(34), chr(34) * 2)}" TEXT'
                        for name in AWKWARD)
    conn.execute(f"CREATE TABLE t (id TEXT PRIMARY KEY, {columns})")
    conn.execute(f"INSERT INTO t VALUES ('r1', {', '.join('?' * len(AWKWARD))})",
                 tuple(AWKWARD.values()))
    conn.commit()
    conn.close()
    return path


class TestAwkwardNamesAreReadCorrectly:
    @pytest.mark.parametrize("name,expected", sorted(AWKWARD.items()))
    def test_the_bulk_read_returns_the_column(self, source, name, expected):
        adapter = SQLiteReadAdapter({"path": source})

        rows = adapter.read_all_rows(
            "t", ["id", name], {"storage": {"table": "t", "id_column": "id"}})

        assert rows[0][name] == expected

    @pytest.mark.parametrize("name", sorted(AWKWARD))
    def test_a_whole_sync_handles_it(self, tmp_path, source, name):
        """Through the real pipeline, not just the adapter."""
        sync = IcebergMirrorSync(tmp_path / f"m{abs(hash(name))}",
                                  {"p": SQLiteReadAdapter({"path": source})})

        sync.sync_table("p", "t", "id", ["id", name], {})

        rows = sync.catalog.load_table("p.t").scan().to_arrow().to_pylist()
        assert rows[0][name] == AWKWARD[name]


class TestTheTableNameToo:
    """WRITTEN BECAUSE A CONTROL PROVED NOTHING. Unquoting the TABLE
    name left every test passing, because the fixture's table is
    called `t`. A customer's table is called "order details"."""

    @pytest.mark.parametrize("table", ["order details", "group", "select"])
    def test_an_awkward_table_name_is_read(self, tmp_path, table):
        path = tmp_path / f"{abs(hash(table))}.db"
        conn = sqlite3.connect(path)
        escaped = table.replace('"', '""')
        conn.execute(f'CREATE TABLE "{escaped}" (id TEXT PRIMARY KEY, v TEXT)')
        conn.execute(f'INSERT INTO "{escaped}" VALUES (?, ?)', ("r1", "value"))
        conn.commit()
        conn.close()
        adapter = SQLiteReadAdapter({"path": path})

        rows = adapter.read_all_rows(
            table, ["id", "v"], {"storage": {"table": table, "id_column": "id"}})

        assert rows[0]["v"] == "value"


class TestNothingIsExecuted:
    @pytest.mark.parametrize("hostile", [
        "(SELECT k FROM secrets)",
        'x" FROM secrets --',
        "x); DROP TABLE t; --",
        "x FROM secrets UNION SELECT k",
    ])
    def test_a_name_shaped_like_sql_reads_no_other_table(self, source, hostile):
        """The audit's worst case: a column name that EXECUTED,
        reading a table the ontology never referenced."""
        adapter = SQLiteReadAdapter({"path": source})

        try:
            rows = adapter.read_all_rows(
                "t", ["id", hostile], {"storage": {"table": "t", "id_column": "id"}})
        except Exception:
            return  # refusing is a perfectly good answer

        assert "TOPSECRET" not in str(rows), f"{hostile!r} reached another table"

    def test_the_other_table_still_exists_afterwards(self, source):
        """A DROP smuggled through a column name would not show up in
        the returned rows at all."""
        adapter = SQLiteReadAdapter({"path": source})
        try:
            adapter.read_all_rows("t", ["id", "x); DROP TABLE secrets; --"],
                                   {"storage": {"table": "t", "id_column": "id"}})
        except Exception:
            pass

        conn = sqlite3.connect(source)
        try:
            assert conn.execute("SELECT k FROM secrets").fetchone() == ("TOPSECRET",)
        finally:
            conn.close()


class TestTheMisspellingHazard:
    """QUOTING IS WHAT MAKES THE CASES ABOVE SAFE, and it has a cost
    worth writing down: SQLite reads an unknown double-quoted
    identifier as a STRING LITERAL rather than raising.

        SELECT "nosuchcolumn" FROM t  ->  ('nosuchcolumn',)

    So a misspelled column would quietly fill every row with its own
    name. The adapter cannot tell the difference. The DRIFT CHECK one
    layer up can, and does -- which means these two layers depend on
    each other in a way neither states."""

    def test_sqlite_really_does_this(self, source):
        conn = sqlite3.connect(source)
        try:
            assert conn.execute('SELECT "nosuchcolumn" FROM t').fetchone() == (
                "nosuchcolumn",)
        finally:
            conn.close()

    def test_but_the_sync_refuses_before_it_can_matter(self, tmp_path, source):
        sync = IcebergMirrorSync(tmp_path / "typo",
                                  {"p": SQLiteReadAdapter({"path": source})})

        with pytest.raises(ValueError, match="typo_column"):
            sync.sync_table("p", "t", "id", ["id", "typo_column"], {})

    def test_and_writes_nothing(self, tmp_path, source):
        sync = IcebergMirrorSync(tmp_path / "typo2",
                                  {"p": SQLiteReadAdapter({"path": source})})

        with pytest.raises(ValueError):
            sync.sync_table("p", "t", "id", ["id", "typo_column"], {})

        assert not sync.catalog.table_exists("p.t")
