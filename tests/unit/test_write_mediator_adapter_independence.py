"""
Tests proving WriteMediator's own real, structural independence from
DataMediator's adapters -- Phase 0 of the read-only mirror initiative
(see ROADMAP.md's own "Read-only data mirror architecture" section,
and write_mediator.py's own __init__ docstring for the full story).

The real point being proven here isn't "the existing test suite still
passes" -- that's necessary but not sufficient, since a test file that
happens to pass BOTH adapters to the same real database wouldn't ever
catch a regression back to the old, borrowed-from-DataMediator
behavior. These tests use two GENUINELY SEPARATE SQLite databases --
one for DataMediator, a different one for WriteMediator -- so that a
write landing in the wrong one is a real, structural, unmistakable
failure, not something a shared-database test could ever detect.
"""

import sqlite3

from adapters.sqlite_adapter import SQLiteReadAdapter, SQLiteWriteAdapter
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLogWriter
from core.ontology.write_mediator import WriteMediator

TEST_SCHEMA = {
    "Widget": {
        "storage": {"silo": "primary", "table": "widgets", "id_column": "widget_id"},
        "id_field": "widget_id",
        "title_field": "name",
        "security": {"field": "org_id"},
        "fields": {
            "widget_id": {"type": "data"},
            "name": {"type": "data"},
            "org_id": {"type": "data"},
        },
    },
}

TEST_ROLES = {
    "widget_writer": {"allowed_actions": ["read:Widget", "read:Widget.widget_id", "execute:RenameWidget"]},
}

TEST_USERS = {"alice": {"org_id": "org1", "role": "widget_writer"}}

TEST_ACTION_TYPES = {
    "RenameWidget": {
        "affected_object_types": ["Widget"],
        "parameters": {
            "widget_id": {"type": "object_reference", "object_type": "Widget", "required": True},
            "new_name": {"type": "string", "required": True},
        },
        "sub_writes": [{
            "object_type": "Widget",
            "object_id": "parameter.widget_id",
            "operation": "update",
            "mutations": [{"set": {"property": "name", "value": "parameter.new_name"}}],
        }],
    },
}


def _make_widgets_db(path, initial_name: str):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE widgets (widget_id TEXT PRIMARY KEY, name TEXT, org_id TEXT)")
    conn.execute("INSERT INTO widgets VALUES ('w1', ?, 'org1')", (initial_name,))
    conn.commit()
    conn.close()


def test_a_confirmed_write_lands_in_write_adapters_own_database_not_mediators(tmp_path):
    # THE real, structural proof -- two genuinely separate SQLite
    # files, each seeded with the SAME row under a DIFFERENT starting
    # name, so which one actually got the real UPDATE is unambiguous.
    read_db = tmp_path / "read_side.db"
    write_db = tmp_path / "write_side.db"
    _make_widgets_db(read_db, initial_name="original-on-read-side")
    _make_widgets_db(write_db, initial_name="original-on-write-side")

    read_adapter = SQLiteReadAdapter({"path": read_db})
    write_adapter = SQLiteWriteAdapter({"path": write_db})

    write_log = WriteLogWriter(tmp_path / "write_log.db")
    mediator = DataMediator(TEST_SCHEMA, {"primary": read_adapter}, {"Widget": "primary"}, TEST_ROLES,
                             write_log=write_log)
    write_mediator = WriteMediator(mediator, {"primary": write_adapter}, TEST_ROLES, TEST_ACTION_TYPES)

    alice = resolve_user_record(TEST_USERS, "alice", "org_id")
    pending = write_mediator.propose_action(alice, "RenameWidget", {"widget_id": "w1", "new_name": "renamed"})
    write_mediator.confirm_and_execute(pending, approved=True)

    # The real, unambiguous proof: write_side.db has the real update;
    # read_side.db was never touched at all.
    write_conn = sqlite3.connect(write_db)
    assert write_conn.execute("SELECT name FROM widgets WHERE widget_id = 'w1'").fetchone()[0] == "renamed"
    write_conn.close()

    read_conn = sqlite3.connect(read_db)
    assert read_conn.execute(
        "SELECT name FROM widgets WHERE widget_id = 'w1'"
    ).fetchone()[0] == "original-on-read-side"
    read_conn.close()


def test_write_mediator_never_reaches_into_mediators_own_adapters_dict(tmp_path):
    # A second, more direct proof of the same real property, at the
    # object level rather than through an end-to-end write: confirm
    # WriteMediator's own internal adapter-owning mediator is a
    # genuinely DIFFERENT object from the one passed in, holding a
    # genuinely different adapters dict -- not the same instance
    # reused, which the end-to-end test above couldn't distinguish
    # from "got lucky."
    read_adapter = SQLiteReadAdapter({"path": tmp_path / "read.db"})
    write_adapter = SQLiteWriteAdapter({"path": tmp_path / "write.db"})
    _make_widgets_db(tmp_path / "read.db", initial_name="x")
    _make_widgets_db(tmp_path / "write.db", initial_name="x")

    write_log = WriteLogWriter(tmp_path / "write_log.db")
    mediator = DataMediator(TEST_SCHEMA, {"primary": read_adapter}, {"Widget": "primary"}, TEST_ROLES,
                             write_log=write_log)
    write_mediator = WriteMediator(mediator, {"primary": write_adapter}, TEST_ROLES, TEST_ACTION_TYPES)

    assert write_mediator._adapter_mediator is not mediator
    assert write_mediator._adapter_mediator.adapters["primary"] is write_adapter
    assert write_mediator._adapter_mediator.adapters["primary"] is not read_adapter
