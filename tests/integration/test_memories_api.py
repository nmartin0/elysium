"""
The memory routes (E-14): what people ask Elysium to remember about an
object, through the HTTP surface the object page uses.

    GET    /api/objects/{type}/{id}/memories
    POST   /api/objects/{type}/{id}/memories
    DELETE /api/memories/{memory_id}

The rules themselves -- who sees, what is stale, who forgets -- are
MemoryGuard's and tested in tests/unit/test_memory_guard.py. These
prove the routes reach it with the caller's own record and keep the
uniform-denial shape notes have.
"""


def _as(client, username, role, region="us-west"):
    client.cookies.clear()
    if not client.app.state.user_directory.user_exists(username):
        client.app.state.user_directory.create_user(username, "pw-for-tests", region, role)
    response = client.post("/api/login", json={"username": username, "password": "pw-for-tests"})
    assert response.status_code == 204, response.text


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("elysium_csrf")}


def _remember(client, object_id, text):
    return client.post(f"/api/objects/Customer/{object_id}/memories", json={"text": text},
                       headers=_csrf(client))


def test_a_memory_is_written_and_read_back(client):
    _as(client, "mem_writer", "customer_service")

    created = _remember(client, "cust_001", "Disputed two charges in March.")
    assert created.status_code == 201, created.text
    assert created.json()["stale"] is False
    assert created.json()["may_forget"] is True

    listed = client.get("/api/objects/Customer/cust_001/memories").json()
    assert [(m["text"], m["author"], m["stale"]) for m in listed] == [
        ("Disputed two charges in March.", "mem_writer", False)]


def test_a_reader_who_cannot_see_its_sources_gets_an_empty_list(client):
    _as(client, "mem_writer2", "customer_service")
    _remember(client, "cust_001", "Prefers email.")

    _as(client, "mem_narrow", "customer_service_no_email")
    assert client.get("/api/objects/Customer/cust_001/memories").json() == []


def test_another_region_gets_an_empty_list_and_a_404_on_write(client):
    _as(client, "mem_writer3", "customer_service")
    _remember(client, "cust_001", "x")

    _as(client, "mem_eu", "customer_service", region="eu")
    assert client.get("/api/objects/Customer/cust_001/memories").json() == []
    assert _remember(client, "cust_001", "y").status_code == 404


def test_an_object_that_does_not_exist_is_a_404(client):
    _as(client, "mem_probe", "customer_service")

    assert _remember(client, "no_such_customer", "x").status_code == 404


def test_empty_text_is_a_400(client):
    _as(client, "mem_empty", "customer_service")

    assert _remember(client, "cust_001", "   ").status_code == 400


def test_only_the_author_forgets_it_here(client):
    _as(client, "mem_author", "customer_service")
    memory_id = _remember(client, "cust_001", "x").json()["id"]

    _as(client, "mem_colleague", "customer_service")
    [seen] = client.get("/api/objects/Customer/cust_001/memories").json()
    assert seen["may_forget"] is False
    assert client.delete(f"/api/memories/{memory_id}", headers=_csrf(client)).status_code == 404

    _as(client, "mem_author", "customer_service")
    assert client.delete(f"/api/memories/{memory_id}", headers=_csrf(client)).status_code == 204
    assert client.get("/api/objects/Customer/cust_001/memories").json() == []


def test_writing_needs_the_csrf_token(client):
    _as(client, "mem_csrf", "customer_service")

    response = client.post("/api/objects/Customer/cust_001/memories", json={"text": "x"})
    assert response.status_code == 403
