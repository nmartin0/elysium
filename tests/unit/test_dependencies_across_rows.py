"""
Functional dependencies: rules across rows (R29's second half).

"Rows that agree on the zip agree on the city." Checked in silver over
the whole table, after the per-row rules, with the same three policies.
A quarantine holds the rows disagreeing with a strict majority, or the
whole group when there is none -- the first is what a person would do,
the second refuses to guess.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.expectations import ExpectationFailed
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.sync_targets import resolve_sync_targets
from core.ontology.field_rules import (
    FieldDependency,
    dependency_violations,
    validate_dependencies,
)

COLUMNS = {"zip": "zip", "city": "city", "country": "country"}
CITY = FieldDependency("city_follows_zip", ("zip",), "city", "quarantine")


def _rows(*pairs):
    return [{"zip": zip_code, "city": city, "country": "US"} for zip_code, city in pairs]


class TestTheCheck:
    def test_agreement_is_no_violation(self):
        assert dependency_violations(CITY, _rows(("1", "A"), ("1", "A"), ("2", "B")), COLUMNS) == {}

    def test_the_minority_against_a_strict_majority_is_named(self):
        found = dependency_violations(CITY, _rows(("1", "A"), ("1", "A"), ("1", "B")), COLUMNS)

        assert list(found) == [2]
        assert "'1' has city 'A' in 2 of 3 rows, not 'B'" in found[2]

    def test_with_no_majority_every_row_of_the_group_is_named(self):
        found = dependency_violations(CITY, _rows(("1", "A"), ("1", "B")), COLUMNS)

        assert sorted(found) == [0, 1]
        assert "no single city ('A', 'B')" in found[0]

    def test_an_empty_determinant_or_dependent_is_not_a_disagreement(self):
        assert dependency_violations(CITY, _rows((None, "A"), (None, "B"), ("1", "A"),
                                                 ("1", None)), COLUMNS) == {}

    def test_a_compound_determinant(self):
        both = FieldDependency("d", ("zip", "country"), "city")
        rows = [{"zip": "1", "country": "US", "city": "A"},
                {"zip": "1", "country": "FR", "city": "B"}]
        assert dependency_violations(both, rows, COLUMNS) == {}


TYPE = {
    "id_field": "id", "storage": {"silo": "s", "table": "people", "id_column": "id"},
    "fields": {"id": {"type": "data"}, "zip": {"type": "data"}, "city": {"type": "data"},
               "friend": {"type": "link", "target": "Other"}},
}


class TestRefusedAtLoad:
    @pytest.mark.parametrize("rule, says", [
        ({"determinant": "zip"}, "does not have"),
        ({"determinant": "nope", "dependent": "city"}, "does not have"),
        ({"determinant": [], "dependent": "city"}, "must name one field"),
        ({"determinant": "city", "dependent": "city"}, "cannot determine itself"),
        ({"determinant": "friend", "dependent": "city"}, "not a stored value"),
        ({"determinant": "zip", "dependent": "city", "on_violation": "drop"}, "on_violation"),
        ({"determinant": "zip", "dependent": "city", "when": "x"}, "unknown key"),
    ])
    def test_a_dependency_that_could_never_be_checked(self, rule, says):
        with pytest.raises(ValueError, match=says):
            validate_dependencies({"Person": {**TYPE, "dependencies": {"d": rule}}})


def _sync(tmp_path, policy, rows):
    source = tmp_path / "s.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE people (id TEXT PRIMARY KEY, zip TEXT, city TEXT)")
    connection.executemany("INSERT INTO people VALUES (?, ?, ?)", rows)
    connection.commit()
    connection.close()
    schema = {"Person": {**TYPE, "fields": {k: v for k, v in TYPE["fields"].items()
                                             if k != "friend"},
                         "dependencies": {"city_follows_zip": {
                             "determinant": "zip", "dependent": "city", "on_violation": policy}}}}
    validate_dependencies(schema)
    (target,) = resolve_sync_targets({"object_types": schema})
    sync = IcebergMirrorSync(tmp_path / "m", {"s": SQLiteReadAdapter({"path": source})})
    result = sync.sync_table("s", "people", "id", target.columns, target.column_types,
                             target.fields_by_column, target.standardisation, target.expectations)
    return sync, result


ROWS = [("p1", "90210", "Beverly Hills"), ("p2", "90210", "Beverly Hills"),
        ("p3", "90210", "Paris"), ("p4", "10001", "New York")]


class TestThroughARealSync:
    def test_quarantine_holds_the_disagreeing_row_and_names_the_majority(self, tmp_path):
        sync, _ = _sync(tmp_path, "quarantine", ROWS)

        kept = {row["id"] for row in sync._catalog.load_table("s.people").scan().to_arrow().to_pylist()}
        (held,) = sync._catalog.load_table("quarantine_s.people").scan().to_arrow().to_pylist()
        assert kept == {"p1", "p2", "p4"}
        assert held["object_id"] == "p3" and held["field"] == "city_follows_zip"
        assert "'Beverly Hills' in 2 of 3 rows, not 'Paris'" in held["reason"]

    def test_warn_keeps_every_row_and_reports(self, tmp_path):
        sync, result = _sync(tmp_path, "warn", ROWS)

        kept = sync._catalog.load_table("s.people").scan().to_arrow().num_rows
        assert kept == 4
        assert any("city_follows_zip" in rule for rule in result.violations)

    def test_fail_stops_the_build(self, tmp_path):
        with pytest.raises(ExpectationFailed):
            _sync(tmp_path, "fail", ROWS)
