"""
Tests proving a single deployment can use TWO genuinely separate
databases of the SAME adapter type -- two distinct SQLite files, not
just two different adapter classes (which was already implicitly
proven by every test mixing SQLite + Ollama). This matters because a
real organization's data is often already split across multiple real
databases, even when they're the same underlying technology.

core/deployment_loader.py's _build_adapters() constructs one adapter
INSTANCE per named silo entry, from that silo's own connection dict --
nothing about this assumes silo names correspond 1:1 with adapter
CLASSES. This file proves that mechanism holds under real, concurrent
use: independent data, independent RBAC, independent MAC, all
enforced correctly despite both silos being instances of the exact
same SQLiteWriteAdapter class.

Deliberately NOT a cross-silo LINK test -- see tests/unit/test_cross_silo_links.py
for that (a security-chain and reverse link both genuinely crossing
database boundaries). These two object types are independent of each
other on purpose, to isolate "two silos, no links between them" from
"two silos, linked" as separate, cleanly-scoped concerns.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteWriteAdapter
from core.deployment_loader import _WRITE_ADAPTER_REGISTRY, _build_adapters
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLogWriter

TEST_SCHEMA = {
    "Widget": {
        "storage": {"silo": "widget_db", "table": "widgets", "id_column": "widget_id"},
        "id_field": "widget_id",
        "security": {"field": "owner_team"},
        "fields": {"owner_team": {"type": "data"}, "name": {"type": "data"}},
    },
    "Gadget": {
        "storage": {"silo": "gadget_db", "table": "gadgets", "id_column": "gadget_id"},
        "id_field": "gadget_id",
        "security": {"field": "owner_team"},
        "fields": {"owner_team": {"type": "data"}, "label": {"type": "data"}},
    },
}

TEST_ROLES = {
    "both": {"allowed_actions": [
        "read:Widget", "read:Widget.widget_id", "read:Widget.name",
        "read:Gadget", "read:Gadget.gadget_id", "read:Gadget.label",
    ]},
    "widget_only": {"allowed_actions": ["read:Widget", "read:Widget.widget_id", "read:Widget.name"]},
}

TEST_USERS = {
    "alice": {"owner_team": "team-a", "role": "both"},
    "bob": {"owner_team": "team-a", "role": "widget_only"},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "owner_team")


@pytest.fixture
def mediator(tmp_path):
    # TWO genuinely separate SQLite FILES -- not the same file reused,
    # not a mock -- both constructed via the exact SAME adapter class.
    widget_db_path = tmp_path / "widgets.db"
    conn = sqlite3.connect(widget_db_path)
    conn.executescript("""
        CREATE TABLE widgets (widget_id TEXT PRIMARY KEY, owner_team TEXT, name TEXT);
        INSERT INTO widgets VALUES ('w1', 'team-a', 'Left Widget');
    """)
    conn.commit()
    conn.close()

    gadget_db_path = tmp_path / "gadgets.db"
    conn = sqlite3.connect(gadget_db_path)
    conn.executescript("""
        CREATE TABLE gadgets (gadget_id TEXT PRIMARY KEY, owner_team TEXT, label TEXT);
        INSERT INTO gadgets VALUES ('g1', 'team-a', 'Right Gadget'), ('g2', 'team-b', 'Other Team Gadget');
    """)
    conn.commit()
    conn.close()

    adapters = _build_adapters({
        "widget_db": {"adapter": "sqlite", "connection": {"path": widget_db_path}},
        "gadget_db": {"adapter": "sqlite", "connection": {"path": gadget_db_path}},
    }, _WRITE_ADAPTER_REGISTRY)
    silo_for_type = {"Widget": "widget_db", "Gadget": "gadget_db"}
    return DataMediator(TEST_SCHEMA, adapters, silo_for_type, TEST_ROLES,
                         write_log=WriteLogWriter(tmp_path / "write_log.db"))


def test_two_silos_get_genuinely_separate_adapter_instances(mediator):
    widget_adapter = mediator.adapters["widget_db"]
    gadget_adapter = mediator.adapters["gadget_db"]
    assert isinstance(widget_adapter, SQLiteWriteAdapter)
    assert isinstance(gadget_adapter, SQLiteWriteAdapter)
    assert widget_adapter is not gadget_adapter
    assert widget_adapter.db_path != gadget_adapter.db_path


def test_authorized_user_reads_correctly_from_both_silos(mediator):
    alice = _record("alice")
    assert mediator.search_object(alice, "Widget", {"widget_id": "w1"}) == ["w1"]
    assert mediator.search_object(alice, "Gadget", {"gadget_id": "g1"}) == ["g1"]
    assert mediator.get_field(alice, "Widget", "w1", "name") == "Left Widget"
    assert mediator.get_field(alice, "Gadget", "g1", "label") == "Right Gadget"


def test_mac_boundary_enforced_independently_within_the_second_silo(mediator):
    # alice (team-a) must still be blocked from a team-b gadget --
    # MAC enforcement isn't skipped or weakened just because this is
    # the SECOND silo of the same adapter type.
    alice = _record("alice")
    assert mediator.search_object(alice, "Gadget", {"gadget_id": "g2"}) == []


def test_rbac_blocks_one_silo_entirely_while_the_other_still_works(mediator):
    # bob has zero Gadget grants at all, despite matching alice's MAC
    # team exactly -- proves RBAC is independently enforced per silo,
    # not accidentally shared or bypassed because both silos are the
    # same adapter class.
    bob = _record("bob")
    assert mediator.search_object(bob, "Gadget", {"gadget_id": "g1"}) == []
    assert mediator.search_object(bob, "Widget", {"widget_id": "w1"}) == ["w1"]


def test_an_action_to_one_silo_never_touches_the_other(mediator):
    from core.ontology.write_mediator import WriteMediator

    roles = {**TEST_ROLES, "widget_writer": {"allowed_actions": [
        "read:Widget", "read:Widget.widget_id", "execute:RenameWidget",
    ]}}
    users = {**TEST_USERS, "carol": {"owner_team": "team-a", "role": "widget_writer"}}
    mediator.roles = roles
    carol = resolve_user_record(users, "carol", "owner_team")

    action_types = {
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
    write_mediator = WriteMediator(mediator, mediator.adapters, roles, action_types)
    pending = write_mediator.propose_action(carol, "RenameWidget", {"widget_id": "w1", "new_name": "Renamed Widget"})
    write_mediator.confirm_and_execute(pending, approved=True)

    # The widget changed...
    alice = _record("alice")
    assert mediator.get_field(alice, "Widget", "w1", "name") == "Renamed Widget"
    # ...but the gadget silo -- a COMPLETELY SEPARATE database file --
    # is provably untouched.
    assert mediator.get_field(alice, "Gadget", "g1", "label") == "Right Gadget"
