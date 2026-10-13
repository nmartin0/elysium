"""
Silver records which reference data judged it (R40).

phonenumbers, email-validator, ftfy and holidays (DEP-4) carry data that
changes between releases. The same source row can pass one sync and be
quarantined the next with nothing in the data or the configuration
changed. Each silver table now records the versions it was checked and
tidied with, and a sync warns when one changed.
"""

import json
import logging
import sqlite3

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import REFERENCE_DATA_PROPERTY, IcebergMirrorSync
from core.mirror.sync_targets import resolve_sync_targets
from core.ontology.constraints import validate_constraints

SCHEMA = {"Person": {
    "id_field": "id", "storage": {"silo": "s", "table": "people", "id_column": "id"},
    "fields": {"id": {"type": "data"},
               "phone": {"type": "data", "standardise": {"phone": "US"}},
               "email": {"type": "data", "constraints": {"email": True}},
               "note": {"type": "data"}}}}


def _sync(tmp_path, schema=SCHEMA):
    source = tmp_path / "s.db"
    if not source.exists():
        connection = sqlite3.connect(source)
        connection.execute("CREATE TABLE people (id TEXT PRIMARY KEY, phone TEXT, email TEXT, note TEXT)")
        connection.execute("INSERT INTO people VALUES ('p1', '(201) 555-0123', 'a@b.co', 'x')")
        connection.commit()
        connection.close()
    validate_constraints(schema)
    (target,) = resolve_sync_targets({"object_types": schema})
    sync = IcebergMirrorSync(tmp_path / "m", {"s": SQLiteReadAdapter({"path": source})})
    sync.sync_table("s", "people", "id", target.columns, target.column_types,
                    target.fields_by_column, target.standardisation, target.expectations)
    return sync


def _recorded(sync):
    return json.loads(sync._catalog.load_table("s.people").properties[REFERENCE_DATA_PROPERTY])


def test_the_versions_used_are_recorded(tmp_path):
    from importlib.metadata import version

    assert _recorded(_sync(tmp_path)) == {"phonenumbers": version("phonenumbers"),
                                          "email-validator": version("email-validator")}


def test_a_table_that_uses_none_records_none(tmp_path):
    plain = {"Person": {**SCHEMA["Person"], "fields": {"id": {"type": "data"},
                                                       "note": {"type": "data"}}}}
    sync = _sync(tmp_path, plain)
    assert REFERENCE_DATA_PROPERTY not in sync._catalog.load_table("s.people").properties


def test_a_changed_version_is_warned_about_even_when_the_data_did_not_change(tmp_path, caplog):
    sync = _sync(tmp_path)
    table = sync._catalog.load_table("s.people")
    with table.transaction() as tx:  # as if the last sync ran an older release
        tx.set_properties({REFERENCE_DATA_PROPERTY: json.dumps({"phonenumbers": "8.0.0"})})

    with caplog.at_level(logging.WARNING):
        sync = _sync(tmp_path)

    assert "reference data changed since the last sync -- phonenumbers 8.0.0 ->" in caplog.text
    assert _recorded(sync)["phonenumbers"] != "8.0.0"
