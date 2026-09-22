"""
The security cache belongs to one request, never to the mediator.

004-F6, A MAC BYPASS, REPRODUCED BEFORE THIS FIX. The cache lived on the
one DataMediator every user and thread shares, and was cleared only by
the next prefetch ANYBODY made. A us-west user read a customer; the
source moved it to us-east; the same user read everything again -- the
response itself saying 'us-east' -- while the rightful us-east user was
denied.

NOW a ContextVar scope: one per HTTP request (middleware), one per agent
query (AgentLoop.run), one per public mediator call, and nested scopes
share the outermost. No scope, no cache.
"""

import sqlite3

from fastapi.testclient import TestClient

import core.ontology.mediator as mediator_module
from tests.integration.test_api import _login

PW = "a-long-and-unremarkable-passphrase"


def _user(client, name, region, role="customer_service"):
    client.app.state.user_directory.create_user(name, PW, region, role)
    other = TestClient(client.app)
    _login(other, name, PW)
    return other


def _move_cust_001_to(client, region):
    db = client.app.state.runtime_paths.data_dir / "dev_fixtures" / "mediator.db"
    conn = sqlite3.connect(db)
    conn.execute("UPDATE customers SET region = ? WHERE customer_id = 'cust_001'", (region,))
    conn.commit()
    conn.close()


def _name_seen(client):
    response = client.get("/api/objects/Customer/cust_001")
    fields = response.json().get("fields", response.json()) if response.status_code == 200 else {}
    return fields.get("name")


class TestTheBypassIsClosed:
    def test_a_customer_moved_out_of_region_is_denied_at_once(self, client):
        """THE REPRODUCTION, over HTTP. Warm by reading, move the row,
        read again -- with NOTHING in between."""
        west = _user(client, "west", "us-west")
        assert _name_seen(west) == "Ada Okafor"

        _move_cust_001_to(client, "us-east")

        assert _name_seen(west) is None

    def test_and_the_rightful_region_is_allowed_at_once(self, client):
        """IT FAILED BOTH WAYS: the new region was denied too."""
        west = _user(client, "west", "us-west")
        east = _user(client, "east", "us-east")
        _name_seen(west)

        _move_cust_001_to(client, "us-east")

        assert _name_seen(east) == "Ada Okafor"


class TestOneScopePerRequest:
    def _spy(self, client, monkeypatch):
        mediator = client.app.state.generation.mediator
        seen = []
        for name in ("search_object", "get_object", "get_field"):
            real = getattr(mediator, name)

            def spy(*args, _real=real, **kwargs):
                # THE OBJECT ITSELF, not id(): Python reuses the id of a
                # freed object, so two requests' caches could share an id
                # while being different -- or a test could pass on a
                # coincidence. Holding the object keeps it alive.
                seen.append(mediator_module._SECURITY_CACHE.get())
                return _real(*args, **kwargs)
            monkeypatch.setattr(mediator, name, spy)
        return seen

    def test_every_call_in_one_request_shares_one_scope(self, client, monkeypatch):
        """WHAT LETS A PAGE SHARE ONE RESOLUTION -- and what justifies the
        unit test that reads its page inside one scope."""
        dana = _user(client, "dana", "us-west", "debug")
        seen = self._spy(client, monkeypatch)

        dana.get("/api/objects/Customer/search")

        assert seen and None not in seen
        assert all(scope is seen[0] for scope in seen)

    def test_two_requests_never_share_one(self, client, monkeypatch):
        """THE PROPERTY 004-F6 NEEDED, stated directly."""
        dana = _user(client, "dana", "us-west", "debug")
        seen = self._spy(client, monkeypatch)

        dana.get("/api/objects/Customer/cust_001")
        first = list(seen)
        seen.clear()
        dana.get("/api/objects/Customer/cust_001")

        assert first and seen
        assert not any(a is b for a in first for b in seen)

    def test_nothing_leaks_past_a_request(self, client):
        dana = _user(client, "dana", "us-west", "debug")
        dana.get("/api/objects/Customer/cust_001")

        assert mediator_module._SECURITY_CACHE.get() is None
