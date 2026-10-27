"""A type listed to everyone is a NAME, and tells nothing else (R: discoverable types).

`discoverable: true` on a type lists it, by name, to every role -- the
same as granting `discover:{type}` to all of them, and no more. These pin
what "no more" means over HTTP, because the risk is not the schema (one
function builds that) but every route that ever treated "the type is in
my visible schema" as "I may use it". Until now that was a rare state, a
discover-only grant; listing makes it every person's.

THE METHOD IS A COMPARISON, NOT A LIST OF EXPECTED ANSWERS. Each route is
asked about a LISTED type (Account) and about a HIDDEN one (Transaction)
by a role holding neither. A listed type must be answered exactly as a
hidden one is -- same status, same body once the name is swapped -- so
the only thing a stranger can learn about a listed type is what the
schema already told them: that it exists.
"""

import re

import pytest

from tests.integration.test_api import _login

LISTED = "Account"
HIDDEN = "Transaction"
ROLE = "customer_service_link_only"   # reads Customer, Tag, SupportTicket; neither of the two above


@pytest.fixture
def linker(client):
    client.app.state.generation.mediator.schema[LISTED]["discoverable"] = True
    client.app.state.user_directory.create_user("linker", "correct-pw", "us-west", ROLE)
    _login(client, "linker", "correct-pw")
    return client


def _schema(client):
    return client.get("/api/me/visible-schema").json()


def test_it_is_listed_by_name_and_nothing_else(linker):
    listed = _schema(linker)[LISTED]

    assert listed["readable"] is False
    assert listed["fields"] == {}
    assert listed["id_field"] is None
    assert listed["title_field"] is None
    assert listed["searchable_by_meaning"] is False
    assert listed["display_name"]


def test_an_unlisted_type_is_still_absent(linker):
    # THE CONTROL: listing one type must not widen the others.
    assert HIDDEN not in _schema(linker)


def test_a_link_to_a_listed_type_is_shown_and_to_a_hidden_one_is_not(client):
    client.app.state.user_directory.create_user("linker", "correct-pw", "us-west", ROLE)
    _login(client, "linker", "correct-pw")

    before = _schema(client)["Customer"]["fields"]
    assert "accounts" not in before, "a link to a type they are not told about must not be named"

    client.app.state.generation.mediator.schema[LISTED]["discoverable"] = True
    after = _schema(client)["Customer"]["fields"]
    assert after["accounts"]["target"] == LISTED


ROUTES = [
    ("GET", "/api/objects/{t}/search?q=", None),
    ("GET", "/api/objects/{t}/matching-ids", None),
    ("POST", "/api/objects/{t}/export", {}),
    ("POST", "/api/objects/{t}/count", {}),
    ("POST", "/api/objects/{t}/aggregate", {"measures": [{"name": "n", "type": "count"}]}),
    ("POST", "/api/objects/{t}/search-around", {"link_field": "customer_id"}),
    ("GET", "/api/objects/{t}/related-in-meaning", None),
    ("GET", "/api/objects/{t}/1", None),
    ("GET", "/api/objects/{t}/1/link-counts", None),
    ("GET", "/api/objects/{t}/1/history", None),
    ("GET", "/api/objects/{t}/1/published-history", None),
    ("GET", "/api/objects/{t}/1/notes", None),
    ("GET", "/api/objects/{t}/1/provenance", None),
    ("GET", "/api/objects/{t}/1/conflicts", None),
    ("GET", "/api/objects/{t}/1/similar", None),
    ("GET", "/api/unusual/{t}", None),
]


def _ask(client, method, path, body, object_type):
    url = path.format(t=object_type)
    response = client.get(url) if method == "GET" else client.post(url, json=body)
    text = response.text.replace(object_type, "<TYPE>")
    # A request id is minted per request, so two honest answers differ in it.
    # (A hidden type is refused before a trace exists, so its answer says
    # null where a listed one's carries an id: no use to a stranger, since
    # a hidden type and a missing one look the same.)
    text = re.sub(r'"request_id":("[0-9a-f-]+"|null)', '"request_id":"<ID>"', text)
    return response.status_code, text


@pytest.mark.parametrize("method,path,body", ROUTES, ids=[f"{m} {p}" for m, p, _ in ROUTES])
def test_a_route_answers_a_listed_type_as_it_answers_a_hidden_one(linker, method, path, body):
    listed = _ask(linker, method, path, body, LISTED)
    hidden = _ask(linker, method, path, body, HIDDEN)

    assert listed == hidden, (
        f"{method} {path}: a listed type was answered differently from a hidden one -- "
        f"listed {listed[0]} {listed[1][:200]!r}, hidden {hidden[0]} {hidden[1][:200]!r}")
