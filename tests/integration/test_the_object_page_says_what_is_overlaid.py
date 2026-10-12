"""The object detail route names fields served from the write log (R67b)."""

from core.ontology.write_log import WriteLogWriter
from tests.conftest import mediator_of


def _login(client, username):
    client.app.state.user_directory.create_user(username, "pw", "us-west", "customer_service")
    assert client.post("/api/login", json={"username": username, "password": "pw"}).status_code == 204


def _pending_name(client, object_id, value):
    writer = WriteLogWriter(mediator_of(client.app).write_log.db_path)
    writer.log_pending_update("Customer", object_id, {"name": value}, {"name": "Ada Okafor"},
                              "someone", "rename")


def test_a_pending_approved_change_is_named(client):
    _login(client, "alice")
    _pending_name(client, "cust_001", "Ada O.")

    body = client.get("/api/objects/Customer/cust_001").json()

    assert body["fields"]["name"] == "Ada O."
    assert body["overlaid"] == {"name": "pending"}


def test_an_object_outside_the_compartment_says_nothing(client):
    """cust_003 is us-east. The read shows alice nothing, so nothing is
    said about a write to it either."""
    _login(client, "alice2")
    _pending_name(client, "cust_003", "Somebody")

    body = client.get("/api/objects/Customer/cust_003").json()

    assert body["overlaid"] == {}


def test_an_untouched_object_says_nothing(client):
    """THE CONTROL."""
    _login(client, "alice3")

    assert client.get("/api/objects/Customer/cust_002").json()["overlaid"] == {}
