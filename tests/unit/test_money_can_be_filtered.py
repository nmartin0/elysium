"""
Filtering money by amount.

TWO BUGS, ONE QUESTION. The roadmap asked whether refusing `range` on
a decimal field was deliberate or a gap. It is a gap: `decimal` is an
EXACT NUMERIC TYPE -- the one you choose for money precisely so it can
be compared -- and SQL has never excluded it from BETWEEN. Leaving it
out meant a money field could not be filtered by amount at all, which
is most of what anyone wants to do with money.

AND FIXING THAT EXPOSED A WORSE ONE. On the source path, a customer
database that stores money as TEXT -- which many do -- answered
`amount BETWEEN 10 AND 50` with 100.00: SQLite's TEXT affinity
converts the bounds to text, and "100.00" sorts between "10" and
"50". A wrong answer about money, silently, with no error anywhere.

THE CAST IS APPLIED ONLY WHERE THE ONTOLOGY DECLARES A NUMERIC TYPE.
Guessing from the value would make a string field whose contents
happen to look numeric compare differently from one whose do not,
which is a worse surprise than the one being fixed.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.filters import FieldFilter, validate_filter
from core.mirror.gold import build_gold
from core.mirror.gold_connector import GoldConnector
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.ontology.gold_view import build_gold_view

TYPE = {
    "id_field": "id",
    "security": {"field": "region"},
    "storage": {"silo": "p", "table": "t", "id_column": "id"},
    "fields": {
        "id": {"type": "data"},
        "region": {"type": "data"},
        "amount": {"type": "data", "data_type": "decimal", "decimal_places": 2},
        "label": {"type": "data", "data_type": "string"},
    },
}
ROWS = [("a", "10.50", "10.50", "us-west"),
        ("b", "0.99", "0.99", "us-west"),
        ("c", "100.00", "100.00", "us-west"),
        ("d", "50.00", "50.00", "us-west")]


class TestTheVocabulary:
    def test_range_applies_to_a_decimal(self):
        validate_filter(FieldFilter("amount", "range", {"min": 10, "max": 50}), "decimal")

    def test_and_still_to_integers_and_numbers(self):
        for declared in ("integer", "number"):
            validate_filter(FieldFilter("amount", "range", {"min": 1}), declared)

    def test_but_not_to_a_string(self):
        """The control: range must still refuse what it cannot mean."""
        with pytest.raises(Exception, match="cannot be used"):
            validate_filter(FieldFilter("label", "range", {"min": 1}), "string")


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "s.db"
    conn = sqlite3.connect(path)
    # TEXT, as a customer database often stores money.
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, amount TEXT, label TEXT, "
                 "region TEXT)")
    conn.executemany("INSERT INTO t VALUES (?,?,?,?)", ROWS)
    conn.commit()
    conn.close()
    return path


class TestTheSourcePath:
    def test_a_range_is_numeric_not_lexicographic(self, source):
        """THE BUG: "100.00" sorts between "10" and "50", so 100.00 was
        returned as an amount between ten and fifty."""
        adapter = SQLiteReadAdapter({"path": source})

        found = adapter.find_ids(
            "T", [FieldFilter("amount", "range", {"min": 10, "max": 50})], TYPE)

        assert sorted(found) == ["a", "d"]

    def test_a_lower_bound_alone(self, source):
        adapter = SQLiteReadAdapter({"path": source})

        found = adapter.find_ids("T", [FieldFilter("amount", "range", {"min": 60})], TYPE)

        assert found == ["c"]

    def test_an_upper_bound_alone(self, source):
        adapter = SQLiteReadAdapter({"path": source})

        found = adapter.find_ids("T", [FieldFilter("amount", "range", {"max": 1})], TYPE)

        assert found == ["b"]

    def test_equality_on_a_decimal_ignores_trailing_form(self, source):
        """A consequence of the cast, and a welcome one: "10.5" and
        "10.50" are the same amount, and a person filtering money
        means the amount rather than the spelling."""
        adapter = SQLiteReadAdapter({"path": source})

        assert adapter.find_ids("T", [FieldFilter("amount", "equals", "10.5")], TYPE) == ["a"]

    def test_a_STRING_field_is_left_alone(self, source):
        """The cast follows the DECLARATION, not the contents. A string
        column whose values look numeric still compares as text."""
        adapter = SQLiteReadAdapter({"path": source})

        found = adapter.find_ids("T", [FieldFilter("label", "equals", "100.00")], TYPE)

        assert found == ["c"]
        assert adapter.find_ids("T", [FieldFilter("label", "equals", "100.0")], TYPE) == []


class TestTheGoldPath:
    def test_a_range_filters_published_gold(self, tmp_path, source):
        """Where reads actually come from since GOLD-8, and where the
        column is a real decimal rather than text."""
        sync = IcebergMirrorSync(tmp_path / "mirror",
                                  {"p": SQLiteReadAdapter({"path": source})})
        sync.sync_table("p", "t", "id", ["id", "amount", "label", "region"],
                        {"id": "string", "amount": "decimal", "label": "string",
                         "region": "string"})
        silver = sync._catalog.load_table("p.t")
        build_gold(sync._catalog, "Thing", TYPE, silver.scan().to_arrow())
        view, _ = build_gold_view({"Thing": TYPE})
        from core.mirror.gold import published_snapshot_ids
        connector = GoldConnector(sync._catalog,
                                   published_snapshot_ids(sync._catalog, view))

        found = connector.find_ids(
            "Thing", [FieldFilter("amount", "range", {"min": 10, "max": 50})],
            view["Thing"])

        assert sorted(found) == ["a", "d"]

    def test_and_both_paths_agree(self, tmp_path, source):
        """The property that matters while both exist: a question about
        money has one answer."""
        sync = IcebergMirrorSync(tmp_path / "mirror",
                                  {"p": SQLiteReadAdapter({"path": source})})
        sync.sync_table("p", "t", "id", ["id", "amount", "label", "region"],
                        {"id": "string", "amount": "decimal", "label": "string",
                         "region": "string"})
        silver = sync._catalog.load_table("p.t")
        build_gold(sync._catalog, "Thing", TYPE, silver.scan().to_arrow())
        view, _ = build_gold_view({"Thing": TYPE})
        from core.mirror.gold import published_snapshot_ids
        connector = GoldConnector(sync._catalog,
                                   published_snapshot_ids(sync._catalog, view))
        condition = [FieldFilter("amount", "range", {"min": 0, "max": 51})]

        from_source = SQLiteReadAdapter({"path": source}).find_ids("Thing", condition, TYPE)
        from_gold = connector.find_ids("Thing", condition, view["Thing"])

        assert sorted(from_source) == sorted(from_gold)


class TestTheNamingIsDocumented:
    """004-F3: "tools" at the boundary, "functions" in the code.

    NOT RENAMED, DOCUMENTED. The boundary word is the industry's --
    OpenAI deprecated its `functions` parameter for `tools` in 2023
    and now rejects both together, Azure followed, MCP says tools --
    so a deployment config says what a reader expects. Renaming the
    INSIDE buys nothing anyone outside can see, and renaming a
    boundary is never just a rename.

    THESE TESTS EXIST because the documentation had already drifted:
    five places pointed at a `core/tools/` package that does not
    exist, which is what a mapping nobody states looks like after a
    while.
    """

    def _configs(self):
        from pathlib import Path
        return [Path("templates/config.yaml"), Path("deployment/etc/config.yaml")]

    def test_the_shipped_configs_explain_the_mapping(self):
        for path in self._configs():
            text = path.read_text()
            assert "NAMING" in text
            assert "core/functions/registry.py" in text

    def test_nothing_points_at_a_package_that_is_not_in_the_repository(self):
        """ASKS GIT, NOT THE FILESYSTEM.

        The first version of this test asserted `not
        Path("core/tools").exists()` and FAILED ON A REAL DEPLOYMENT --
        not because the repository was wrong, but because that machine
        had an untracked leftover directory from before the package was
        renamed. A stale __pycache__ or an empty directory git does not
        track is nobody's bug, and a test that fails on one is testing
        the developer's disk rather than the project.

        What is worth asserting is that the repository does not SHIP a
        core/tools and does not POINT at one.
        """
        import subprocess
        from pathlib import Path

        tracked = subprocess.run(
            ["git", "ls-files", "core/tools"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()

        assert tracked == "", f"core/tools is tracked in the repository: {tracked}"
        for path in [*self._configs(), Path("README.md"),
                     Path("functions/linear_regression.py")]:
            assert "core/tools/" not in path.read_text(), f"{path} points at core/tools/"

    def test_the_boundary_key_is_still_tools(self):
        """The control: documenting the mapping must not have quietly
        renamed the thing a deployment writes."""
        from pathlib import Path

        import yaml

        config = yaml.safe_load(Path("deployment/etc/config.yaml").read_text())

        assert "tools" in config and "enabled" in config["tools"]
