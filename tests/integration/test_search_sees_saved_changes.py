"""A search sees a saved change before the next sync (16 October).

Reading an object showed a saved change at once, through the mirror
overlay; SEARCHING for it did not, because the search reconciled only
pending writes. A rename approved in Elysium could not be found by its
new name -- and was still found by its old one -- until a sync. Found
by a trigger whose count could not see the change it was checked for.
"""

from tests.integration.test_trigger_checks import _csrf, _login


def _count(client, name):
    response = client.post(
        "/api/objects/Customer/count",
        json={"conditions": [{"field": "name", "operator": "equals", "value": name}]},
        headers=_csrf(client))
    assert response.status_code == 200, response.text
    return response.json()["count"]


def _rename(client, new_name):
    proposed = client.post(
        "/api/actions/UpdateCustomerName",
        json={"parameters": {"customer_id": "cust_001", "new_name": new_name}},
        headers=_csrf(client))
    confirmed = client.post(f"/api/writes/{proposed.json()['pending_write']['id']}/confirm",
                            json={"approved": True}, headers=_csrf(client))
    assert confirmed.json().get("status") == "written", confirmed.text


def test_found_by_its_new_value_and_not_its_old(client):
    _login(client, "alice")
    old_name = client.get("/api/objects/Customer/cust_001").json()["fields"]["name"]
    assert _count(client, old_name) == 1

    _rename(client, "Grace Hopper")

    assert _count(client, "Grace Hopper") == 1
    assert _count(client, old_name) == 0
