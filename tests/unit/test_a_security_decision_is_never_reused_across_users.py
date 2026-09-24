"""
One user's security answer is never handed to another (004-6).

THE FINDING, from the first audit set: `_security_value_cache` was an
instance attribute of DataMediator, of which there is ONE per
configuration generation, shared across every user and every executor
thread -- so a MAC decision could be made against a value cached for
somebody else. It was reproduced over HTTP: after an object moved
compartment, the old user kept access AND the rightful user was
denied.

IT DOES NOT REPRODUCE. The cache moved into a ContextVar scoped per
request, per agent query and per public mediator call (commit e9c0a33,
"Scope the security cache to one request, closing a MAC bypass"), so
this was already fixed before the audit reached us -- the audit is
pinned to 120d1b2, well behind.

SO WHY ADD TESTS AT ALL. tests/unit/test_security_cache_scope.py
already covers the MECHANISM thoroughly: no scope means no cache,
scopes nest, scopes reset, no instance attribute holds one. What was
missing is the SHAPE THE AUDIT REPORTED -- two real users, one real
object moving between compartments, read through a real mediator, and
the same thing again with both users reading at once.

A mechanism test says the lock is fitted. This says the door is shut.

AND AN HONEST LIMIT, because it would be easy to present these as
guarding 004-6 and they do not. Reinstating a SHARED cache -- the
exact shape the finding describes -- leaves every test here passing.
Three things independently prevent the leak, and only one of them is
the ContextVar:

  1. THE CACHE HOLDS THE OBJECT'S SECURITY VALUE, keyed by (type, id):
     {('T', 'o1'): 'us-west'}. It is not a per-user DECISION. Two users
     sharing that entry still compare it against their OWN security
     value, so sharing it cannot by itself grant anyone anything.
  2. _prefetch_security_values CLEARS both caches before warming them,
     so a stale entry cannot outlive the call that made it.
  3. The ContextVar scope, which is what commit e9c0a33 added.

So these tests pin the BEHAVIOUR (an object that moves compartment is
visible to exactly the right people, including under concurrent
reads). They do not pin the mechanism, and pretending otherwise would
put a false reassurance in the suite.
"""

import sqlite3
import threading

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.intermediate_layer.auth import UserRecord
from core.ontology.mediator import DataMediator

SCHEMA = {
    "T": {
        "id_field": "id", "security": {"field": "region"},
        "storage": {"silo": "p", "table": "t", "id_column": "id"},
        "fields": {"id": {"type": "data"}, "name": {"type": "data"},
                    "region": {"type": "data"}},
    }
}


@pytest.fixture
def deployment(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, name TEXT, region TEXT)")
    conn.execute("INSERT INTO t VALUES ('o1','Thing','us-west')")
    conn.commit()
    conn.close()
    grants = ["read:T"] + [f"read:T.{f}" for f in SCHEMA["T"]["fields"]]
    mediator = DataMediator(SCHEMA, {"p": SQLiteReadAdapter({"path": source})},
                             {"T": "p"}, {"r": {"allowed_actions": grants}})

    def move_to(region):
        conn = sqlite3.connect(source)
        conn.execute("UPDATE t SET region=? WHERE id='o1'", (region,))
        conn.commit()
        conn.close()

    mediator.move_to = move_to
    return mediator


WEST = UserRecord(user_id="w", security_value="us-west", role_name="r")
EAST = UserRecord(user_id="e", security_value="us-east", role_name="r")


class TestWhenAnObjectMovesCompartment:
    def test_the_old_compartment_loses_access(self, deployment):
        """Half of what the audit reproduced: the user who could see
        it kept seeing it."""
        assert deployment.get_object(WEST, "T", "o1", ["name"]) == {"name": "Thing"}

        deployment.move_to("us-east")

        assert deployment.get_object(WEST, "T", "o1", ["name"]) == {"name": None}

    def test_the_new_compartment_gains_access(self, deployment):
        """The other half, and the one that makes it obviously a bug
        rather than merely cautious: the RIGHTFUL user was denied."""
        assert deployment.get_object(EAST, "T", "o1", ["name"]) == {"name": None}

        deployment.move_to("us-east")

        assert deployment.get_object(EAST, "T", "o1", ["name"]) == {"name": "Thing"}

    def test_reading_as_one_user_first_does_not_decide_it_for_the_other(self, deployment):
        """The cache is populated by the FIRST read. If it were
        shared, whoever asked first would set the answer for
        everybody."""
        deployment.get_object(WEST, "T", "o1", ["name"])
        deployment.move_to("us-east")

        assert deployment.get_object(WEST, "T", "o1", ["name"]) == {"name": None}
        assert deployment.get_object(EAST, "T", "o1", ["name"]) == {"name": "Thing"}


class TestTwoUsersAtOnce:
    def test_concurrent_reads_do_not_share_an_answer(self, deployment):
        """ONE mediator, two threads, two compartments -- which is
        exactly the production shape: one generation serving every
        request."""
        deployment.move_to("us-east")
        seen = {}

        def read(user, key):
            seen[key] = deployment.get_object(user, "T", "o1", ["name"])

        threads = [threading.Thread(target=read, args=(WEST, "west")),
                   threading.Thread(target=read, args=(EAST, "east"))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert seen["west"] == {"name": None}
        assert seen["east"] == {"name": "Thing"}

    def test_many_interleaved_reads_stay_correct(self, deployment):
        """One pair proves little about a race. Twenty each,
        interleaved, is still not proof -- but a shared cache would
        almost certainly show through."""
        wrong = []

        def read_many(user, expected):
            for _ in range(20):
                if deployment.get_object(user, "T", "o1", ["name"]) != expected:
                    wrong.append(user.security_value)

        threads = [threading.Thread(target=read_many, args=(WEST, {"name": "Thing"})),
                   threading.Thread(target=read_many, args=(EAST, {"name": None}))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert wrong == []
