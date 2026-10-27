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


# ---- the arrangement everyone starts from (26 October) ----------------------

from tests.conftest import with_roles  # noqa: E402


def _roles(client):
    with_roles(
        client.app,
        sees_customer={"allowed_actions": frozenset(["read:Customer"])},
        sees_both={"allowed_actions": frozenset(["read:Customer", "read:Account"])},
        placer={"allowed_actions": frozenset(["manage:deployment", "read:Customer", "read:Account"])},
        placer_of_account={"allowed_actions": frozenset(["manage:deployment", "read:Account"])},
    )


def _shared(client, positions):
    return client.put("/api/admin/ontology-canvas-default", json={"positions": positions},
                      headers=_csrf_headers(client))


def _switch(client, username, role):
    client.cookies.clear()
    _as(client, username, role)


CUSTOMER_AT = {"x": 10.0, "y": 20.0}
ACCOUNT_AT = {"x": 300.0, "y": 40.0}


def test_what_a_manager_saves_is_what_everyone_starts_from(client):
    _roles(client)
    _as(client, "pat", "placer")
    assert _shared(client, {"Customer": CUSTOMER_AT, "Account": ACCOUNT_AT}).status_code == 200

    _switch(client, "sam", "sees_both")

    body = client.get("/api/me/ontology-canvas").json()
    assert body["shared_positions"] == {"Customer": CUSTOMER_AT, "Account": ACCOUNT_AT}
    assert body["positions"] == {}


def test_someone_who_cannot_see_a_type_is_not_sent_where_it_sits(client):
    """The gap in their picture must say nothing a name would not."""
    _roles(client)
    _as(client, "pat", "placer")
    _shared(client, {"Customer": CUSTOMER_AT, "Account": ACCOUNT_AT})

    _switch(client, "cat", "sees_customer")

    assert client.get("/api/me/ontology-canvas").json()["shared_positions"] == {"Customer": CUSTOMER_AT}


def test_a_manager_who_sees_fewer_types_does_not_erase_the_others(client):
    _roles(client)
    _as(client, "pat", "placer")
    _shared(client, {"Customer": CUSTOMER_AT, "Account": ACCOUNT_AT})

    _switch(client, "quin", "placer_of_account")
    _shared(client, {"Account": {"x": 999.0, "y": 1.0}, "Customer": {"x": 5.0, "y": 5.0}})

    _switch(client, "sam", "sees_both")
    assert client.get("/api/me/ontology-canvas").json()["shared_positions"] == {
        "Customer": CUSTOMER_AT, "Account": {"x": 999.0, "y": 1.0}}


def test_their_own_moves_do_not_touch_the_shared_arrangement(client):
    _roles(client)
    _as(client, "pat", "placer")
    _shared(client, {"Customer": CUSTOMER_AT})

    _switch(client, "sam", "sees_both")
    _put(client, {"positions": {"Customer": {"x": 77, "y": 88}}, "areas": []})

    body = client.get("/api/me/ontology-canvas").json()
    assert body["positions"] == {"Customer": {"x": 77.0, "y": 88.0}}
    assert body["shared_positions"] == {"Customer": CUSTOMER_AT}


def test_only_someone_who_manages_the_deployment_is_offered_it_or_may_do_it(client):
    _roles(client)
    _as(client, "sam", "sees_both")

    assert "can_set_shared" not in client.get("/api/me/ontology-canvas").json()
    assert _shared(client, {"Customer": CUSTOMER_AT}).status_code == 403

    _switch(client, "pat", "placer")
    assert client.get("/api/me/ontology-canvas").json()["can_set_shared"] is True


def test_nothing_they_can_place_is_a_refusal_not_a_silent_save(client):
    _roles(client)
    _as(client, "quin", "placer_of_account")

    response = _shared(client, {"Customer": CUSTOMER_AT})

    assert response.status_code == 400


def test_a_coordinate_that_is_not_a_number_is_refused(client):
    _roles(client)
    _as(client, "pat", "placer")

    assert _shared(client, {"Customer": {"x": 1e12, "y": 0}}).status_code == 400


def test_clearing_it_sends_everyone_back_to_the_automatic_layout(client):
    _roles(client)
    _as(client, "pat", "placer")
    _shared(client, {"Customer": CUSTOMER_AT})

    cleared = client.delete("/api/admin/ontology-canvas-default", headers=_csrf_headers(client))

    assert cleared.status_code == 200 and cleared.json()["shared_positions"] == {}
    _switch(client, "sam", "sees_both")
    assert client.get("/api/me/ontology-canvas").json()["shared_positions"] == {}


def test_only_a_manager_may_clear_it(client):
    _roles(client)
    _as(client, "sam", "sees_both")

    assert client.delete("/api/admin/ontology-canvas-default", headers=_csrf_headers(client)).status_code == 403
