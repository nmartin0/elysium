"""
What silver's cleaning rules changed, per cell, and by which rule (R33).

Bronze holds what the source wrote; silver holds what the rules made of
it. Until now the difference had no record: "why does silver say
+12015550123 when the source says (201) 555-0123" was answerable only by
re-deriving it. cleaning_<silo>.<table> now says, per cell: the text
before, after, and the rules that changed it. Rewritten each sync, so it
describes silver as it is; Iceberg's snapshots are its history; and it
is REPLAYABLE, because bronze holds every `before`.
"""

import json
import sqlite3

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.standardise import rules_for, standardise_explained
from core.mirror.sync_targets import resolve_sync_targets

SCHEMA = {"Person": {
    "id_field": "id", "storage": {"silo": "s", "table": "people", "id_column": "id"},
    "fields": {"id": {"type": "data"},
               "name": {"type": "data", "classification": "pii"},
               "phone": {"type": "data", "standardise": {"phone": "US", "null_if": ["N/A"]}}},
}}


def _sync(tmp_path, rows):
    source = tmp_path / "s.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE IF NOT EXISTS people (id TEXT PRIMARY KEY, name TEXT, phone TEXT)")
    connection.execute("DELETE FROM people")
    connection.executemany("INSERT INTO people VALUES (?, ?, ?)", rows)
    connection.commit()
    connection.close()
    (target,) = resolve_sync_targets({"object_types": SCHEMA})
    sync = IcebergMirrorSync(tmp_path / "m", {"s": SQLiteReadAdapter({"path": source})})
    sync.sync_table("s", "people", "id", target.columns, target.column_types,
                    target.fields_by_column, target.standardisation, target.expectations)
    return sync


def _cleaning(sync):
    return sync._catalog.load_table("cleaning_s.people").scan().to_arrow().to_pylist()


ROWS = [("p1", "  Ada  Okafor ", "(201) 555-0123"), ("p2", "Bram", "N/A"), ("p3", "Cy", None)]


def test_each_changed_cell_is_recorded_with_its_rules(tmp_path):
    records = {(r["object_id"], r["column"]): r for r in _cleaning(_sync(tmp_path, ROWS))}

    assert set(records) == {("p1", "name"), ("p1", "phone"), ("p2", "phone")}
    assert records[("p1", "name")]["before"] == "  Ada  Okafor "
    assert records[("p1", "name")]["after"] == "Ada Okafor"
    assert records[("p1", "name")]["rules"] == "collapse_whitespace"
    assert records[("p1", "phone")]["after"] == "+12015550123"
    assert records[("p1", "phone")]["rules"] == "phone"
    assert records[("p2", "phone")]["after"] is None and records[("p2", "phone")]["rules"] == "null_if"


def test_it_is_replayable_from_bronze_and_the_rules(tmp_path):
    """Every `before` is in bronze, and running the declared rules on it
    again gives the recorded `after` -- the definition of replayable."""
    sync = _sync(tmp_path, ROWS)
    bronze = {row["id"]: row for row in
              sync._catalog.load_table("bronze_s.people").scan().to_arrow().to_pylist()}
    fields = SCHEMA["Person"]["fields"]

    for record in _cleaning(sync):
        before = bronze[record["object_id"]][record["column"]]
        assert before == record["before"]
        after, rules = standardise_explained(before, rules_for(fields[record["column"]]))
        assert after == record["after"] and ", ".join(rules) == record["rules"]


def test_it_describes_silver_now_rather_than_accumulating(tmp_path):
    _sync(tmp_path, ROWS)
    # The same rows, now already clean at the source.
    sync = _sync(tmp_path, [("p1", "Ada Okafor", "+12015550123"), ("p2", "Bram", None),
                            ("p3", "Cy", None)])

    assert _cleaning(sync) == []


def test_nothing_cleaned_creates_nothing(tmp_path):
    sync = _sync(tmp_path, [("p1", "Ada", None)])
    assert "cleaning_s" not in {ns[0] for ns in sync._catalog.list_namespaces()}


def test_it_carries_the_labels_of_what_it_holds():
    from core.mirror.classifications import classifications_by_table

    labels = classifications_by_table(SCHEMA)["cleaning_s.people"]
    assert "pii" in labels["before"] and "pii" in labels["after"]


def test_an_erased_person_s_cells_go_with_them():
    from core.mirror.erasure import table_key_columns

    assert table_key_columns(SCHEMA, "cleaning_s.people") == {"object_id": {"Person"}}


def test_a_silo_may_not_be_called_cleaning_something():
    from core.deployment_loader import RESERVED_SILO_PREFIXES

    assert "cleaning_" in RESERVED_SILO_PREFIXES
    assert json.dumps(RESERVED_SILO_PREFIXES)  # a tuple of strings, as the loader reads
