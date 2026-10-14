"""The ontology canvas's layout over HTTP (DEV_UI 14): one person's, kept
to what they may see, with the security layer only for those who may see
the permission model."""

from tests.integration.test_api import _csrf_headers, _login  # noqa: F401


def _as(client, username, role):
    client.app.state.user_directory.create_user(username, "correct-pw", "us-west", role)
    _login(client, username, "correct-pw")


def _put(client, body):
    return client.put("/api/me/ontology-canvas", json=body, headers=_csrf_headers(client))


def test_a_fresh_person_has_no_layout_and_the_canvas_lays_itself_out(client):
    _as(client, "alice", "customer_service")
    body = client.get("/api/me/ontology-canvas").json()
    assert body["positions"] == {} and body["areas"] == []


def test_what_they_put_is_what_they_get_back(client):
    _as(client, "alice", "customer_service")
    saved = _put(client, {"positions": {"Customer": {"x": 40, "y": 80}},
                          "areas": [{"name": "Service", "types": ["Customer"]}]})
    assert saved.status_code == 200

    body = client.get("/api/me/ontology-canvas").json()
    assert body["positions"] == {"Customer": {"x": 40.0, "y": 80.0}}
    assert body["areas"] == [{"name": "Service", "types": ["Customer"]}]


def test_it_is_their_own(client):
    _as(client, "alice", "customer_service")
    _put(client, {"positions": {"Customer": {"x": 40, "y": 80}}, "areas": []})
    client.post("/api/logout", headers=_csrf_headers(client))

    _as(client, "bob", "customer_service")
    assert client.get("/api/me/ontology-canvas").json()["positions"] == {}


def test_a_type_they_cannot_see_is_dropped_and_the_answer_says_what_was_kept(client):
    """The same answer for a type that does not exist and one they may
    not see: neither is stored, neither is an error."""
    _as(client, "alice", "customer_service")
    visible = client.get("/api/me/visible-schema").json()
    assert "NoSuchType" not in visible

    saved = _put(client, {"positions": {"NoSuchType": {"x": 1, "y": 1}, "Customer": {"x": 2, "y": 2}},
                          "areas": []})
    assert saved.status_code == 200
    assert set(saved.json()["positions"]) == {"Customer"}


def test_a_type_whose_grant_was_withdrawn_is_not_named_back(client):
    """Cleaned on READ as well as on write: what was stored while they
    could see a type must not tell them about it once they cannot."""
    from core.canvas_layout import CanvasLayoutStore

    _as(client, "alice", "customer_service")
    user_id = client.app.state.user_directory.get_user_record("alice").user_id
    CanvasLayoutStore(client.app.state.runtime_paths.data_dir / "canvas_layouts.db").put(
        user_id, {"positions": {"Payroll": {"x": 1, "y": 1}, "Customer": {"x": 2, "y": 2}},
                  "areas": [{"name": "Old", "types": ["Payroll"]}]})

    body = client.get("/api/me/ontology-canvas").json()
    assert set(body["positions"]) == {"Customer"}
    assert body["areas"] == [{"name": "Old", "types": []}]


def test_a_malformed_layout_is_refused_with_the_reason(client):
    _as(client, "alice", "customer_service")
    response = _put(client, {"positions": {"Customer": {"x": "left", "y": 0}}})
    assert response.status_code == 400
    assert "numeric" in response.json()["detail"]


def test_saving_needs_the_csrf_token_like_every_other_write(client):
    _as(client, "alice", "customer_service")
    assert client.put("/api/me/ontology-canvas", json={"positions": {}, "areas": []}).status_code == 403


class TestTheSecurityLayer:
    def test_someone_who_may_change_roles_sees_the_chains(self, client):
        _as(client, "root", "debug")
        chains = client.get("/api/me/ontology-canvas").json()["security_chains"]
        by_type = {chain["type"]: chain for chain in chains}
        assert by_type["Customer"] == {"type": "Customer", "kind": "field", "field": "region"}
        assert by_type["Transaction"]["kind"] == "via"
        assert by_type["Transaction"]["target"] == "Customer"

    def test_anyone_else_gets_no_key_at_all_rather_than_an_empty_list(self, client):
        """An empty list would read as "nothing here is secured"."""
        _as(client, "alice", "customer_service")
        assert "security_chains" not in client.get("/api/me/ontology-canvas").json()
