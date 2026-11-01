"""Deprecating from the UI (the removal design, 28 October), over HTTP
against a COPY of the fixture configuration -- these tests write the file.

The rules under test: a status is written and reloaded as one generation;
the reason is required and a reply says what is wrong with the rest; a link
follows its types; it changes nobody's access; a stale view is refused; and
only a manager of the deployment may.
"""

import yaml

from tests.conftest import read_audit_log, with_roles
from tests.integration import test_editing_config_from_the_ui as editing
from tests.integration.test_api import _csrf_headers, _login

config_dir = editing.config_dir
deployer = editing.deployer
FILE = "ontology_schema.yaml"

EMAIL = {"kind": "field", "object_type": "Customer", "field": "email", "status": "deprecated",
         "reason": "Replaced by name.", "replaced_by": "name", "remove_after": "2027-03-31"}


def _digest(client):
    return client.get("/api/admin/ontology/descriptions").json()["digest"]


def _status(client, body=None, preview=False, **given):
    body = {**(body or EMAIL), "digest": given.pop("digest", None) or _digest(client), **given}
    send = client.post if preview else client.put
    return send("/api/admin/ontology/status" + ("/preview" if preview else ""),
                headers=_csrf_headers(client), json=body)


def _file(config_dir):
    return yaml.safe_load((config_dir / FILE).read_text())


class TestDeprecating:
    def test_it_is_written_and_reloaded_as_one_generation(self, deployer, config_dir):
        before = deployer.app.state.generation.generation

        response = _status(deployer)

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "applied"
        assert response.json()["to_generation"] == before + 1
        written = _file(config_dir)["object_types"]["Customer"]["fields"]["email"]
        assert written["status"] == "deprecated" and written["deprecation"]["replaced_by"] == "name"
        loaded = deployer.app.state.generation.config.schema["Customer"]["fields"]["email"]
        assert loaded["status"] == "deprecated"

    def test_a_link_follows_its_types(self, deployer):
        _status(deployer, {"kind": "type", "object_type": "Customer", "status": "deprecated",
                           "reason": "Retiring customers."})

        link = deployer.app.state.generation.config.schema["Customer"]["fields"]["transactions"]
        assert link["status"] == "deprecated"
        assert link["status_inherited_from"] == "Customer"

    def test_a_link_type_is_deprecated_on_its_own(self, deployer, config_dir):
        response = _status(deployer, {"kind": "link", "link": "CustomerTags", "status": "deprecated",
                                      "reason": "Tags are going."})

        assert response.status_code == 200, response.text
        assert _file(config_dir)["link_types"]["CustomerTags"]["status"] == "deprecated"
        link = deployer.app.state.generation.config.schema["Customer"]["fields"]["tags"]
        assert link["deprecation"]["reason"] == "Tags are going."

    def test_putting_it_back_makes_it_active_again(self, deployer, config_dir):
        _status(deployer)
        # The fixture grants manage:deployment in memory; a reload replaces it.
        editing._grant(deployer)

        response = _status(deployer, {"kind": "field", "object_type": "Customer", "field": "email",
                                      "status": "active"})

        assert response.status_code == 200, response.text
        email = _file(config_dir)["object_types"]["Customer"]["fields"]["email"]
        assert "status" not in email and "deprecation" not in email
        assert deployer.app.state.generation.config.schema["Customer"]["fields"]["email"].get("status") in (
            None, "active")

    def test_nothing_changes_about_who_can_read_it(self, deployer):
        preview = _status(deployer, preview=True).json()

        assert preview["needs_approval"] is False and preview["impact"]["widens"] is False

    def test_the_change_is_audited(self, deployer):
        _status(deployer)

        entries = [e for e in read_audit_log(deployer.app.state.runtime_paths.log_dir)
                   if e.get("stage") == "config_edit" and e.get("file") == FILE]
        assert entries[-1]["outcome"] == "applied" and entries[-1]["user_id"] == "ops"

    def test_a_reason_is_required_and_nothing_is_written_without_one(self, deployer, config_dir):
        before = (config_dir / FILE).read_text()

        response = _status(deployer, reason="")

        assert response.status_code == 400 and "Say why" in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before

    def test_a_replacement_that_does_not_exist_is_refused(self, deployer, config_dir):
        before = (config_dir / FILE).read_text()

        response = _status(deployer, replaced_by="nobody")

        assert response.status_code == 400 and "not a field that exists" in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before

    def test_a_stale_view_is_refused(self, deployer, config_dir):
        digest = _digest(deployer)
        path = config_dir / FILE
        path.write_text(path.read_text() + "\n# an operator was here\n")

        assert _status(deployer, digest=digest).status_code == 409
        assert "deprecated" not in path.read_text()

    def test_the_loader_has_the_last_word(self, deployer, config_dir, monkeypatch):
        before = (config_dir / FILE).read_text()
        broken = before.replace("  Customer:\n", "  Customer:\n    not_a_known_key_at_all: [\n", 1)
        monkeypatch.setattr("core.config_editing.apply_status", lambda *given: broken)

        assert _status(deployer).status_code == 400
        assert (config_dir / FILE).read_text() == before


class TestAStatusNeverWidensAccess:
    def test_if_the_permission_code_says_it_would_the_edit_is_refused_and_nothing_is_written(
            self, deployer, config_dir, monkeypatch):
        before = (config_dir / FILE).read_text()
        monkeypatch.setattr("api.routes._access_impact", lambda request, replacements: (None, {"widens": True}))

        response = _status(deployer)

        assert response.status_code == 409 and "read more" in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before


class TestThePreview:
    def test_it_writes_nothing_and_shows_the_lines(self, deployer, config_dir):
        before = (config_dir / FILE).read_text()

        preview = _status(deployer, preview=True)

        assert preview.status_code == 200, preview.text
        assert any("status: deprecated" in line for line in preview.json()["diff"])
        assert (config_dir / FILE).read_text() == before


class TestWhoMay:
    def test_only_a_manager_of_the_deployment(self, deployer):
        deployer.cookies.clear()
        deployer.app.state.user_directory.create_user("pat", "correct-pw", "us-west", "customer_service")
        _login(deployer, "pat", "correct-pw")

        assert _status(deployer, digest="x").status_code == 403
        assert _status(deployer, digest="x", preview=True).status_code == 403


class TestNothingIsLeakedToSomeoneWhoCannotDiscoverTheName:
    """A reason is free text about a name the caller may already
    discover (deliberate); the NAME a deprecation points at must not
    itself be new information. Found by an independent review, 31
    October, confirmed against the bug this fixes."""

    def _narrow(self, deployer):
        with_roles(deployer.app, narrow={"allowed_actions": frozenset(
            ["discover:Customer", "discover:Customer.transactions", "discover:Customer.tags",
             "discover:Transaction"])})
        deployer.app.state.user_directory.create_user("nar", "correct-pw", "us-west", "narrow")
        deployer.cookies.clear()
        _login(deployer, "nar", "correct-pw")
        return deployer.get("/api/me/visible-schema").json()

    def test_a_types_replacement_is_hidden_when_it_is_not_discoverable(self, deployer):
        _status(deployer, {"kind": "type", "object_type": "Customer", "status": "deprecated",
                           "reason": "Retiring.", "replaced_by": "Tag"})

        schema = self._narrow(deployer)

        assert "Tag" not in schema
        assert schema["Customer"]["deprecation"]["replaced_by"] is None
        assert schema["Customer"]["deprecation"]["reason"] == "Retiring."

    def test_a_links_inherited_status_is_hidden_when_the_other_type_is_not_discoverable(self, deployer):
        # Transaction.customer_id is the FORWARD half of CustomerTransactions
        # (the foreign key, stored on Transaction) -- it survives even when
        # Customer becomes unknown, kept as plain data (R67b): exactly the
        # case the independent review (31 October) found leaking the name.
        _status(deployer, {"kind": "type", "object_type": "Customer", "status": "deprecated",
                           "reason": "Retiring customers."})
        with_roles(deployer.app, narrow={"allowed_actions": frozenset(
            ["discover:Transaction", "discover:Transaction.customer_id"])})
        deployer.app.state.user_directory.create_user("nar3", "correct-pw", "us-west", "narrow")
        deployer.cookies.clear()
        _login(deployer, "nar3", "correct-pw")

        schema = deployer.get("/api/me/visible-schema").json()

        assert "Customer" not in schema
        link = schema["Transaction"]["fields"]["customer_id"]
        assert link["type"] == "data"
        assert link["status"] == "active" and link["status_inherited_from"] is None

    def test_a_fields_replacement_is_hidden_when_it_is_not_discoverable(self, deployer):
        # Order matters: applying a status edit RELOADS the generation
        # from the file on disk, which would wipe out a role added in
        # memory by with_roles -- so the edit goes first, as the real
        # ops user, and the narrow role is added only once it is done.
        #
        # THE DEPRECATED FIELD ITSELF STAYS DISCOVERABLE here (unlike
        # the type and link cases above, where the deprecated name
        # disappears entirely): the point is that a caller who CAN see
        # "currency" and its reason must still not learn the name
        # "category", which they cannot discover.
        _status(deployer, {"kind": "field", "object_type": "Transaction", "field": "currency",
                           "status": "deprecated", "reason": "Use amount.", "replaced_by": "category"})
        with_roles(deployer.app, narrow={"allowed_actions": frozenset(
            ["discover:Transaction", "discover:Transaction.currency", "discover:Transaction.amount"])})
        deployer.app.state.user_directory.create_user("nar2", "correct-pw", "us-west", "narrow")
        deployer.cookies.clear()
        _login(deployer, "nar2", "correct-pw")

        schema = deployer.get("/api/me/visible-schema").json()

        fields = schema.get("Transaction", {}).get("fields", {})
        assert fields["currency"]["status"] == "deprecated"
        assert fields["currency"]["deprecation"] == {"reason": "Use amount.", "replaced_by": None,
                                                      "remove_after": None}


class TestWhatAReaderSees:
    def _reader(self, deployer):
        deployer.app.state.user_directory.create_user("carla", "correct-pw", "us-west", "customer_service")
        deployer.cookies.clear()
        _login(deployer, "carla", "correct-pw")
        return deployer.get("/api/me/visible-schema").json()

    def test_a_field_carries_its_reason_replacement_and_date_as_text(self, deployer):
        _status(deployer)

        schema = self._reader(deployer)

        assert schema["Customer"]["fields"]["email"]["status"] == "deprecated"
        assert schema["Customer"]["fields"]["email"]["deprecation"] == {
            "reason": "Replaced by name.", "replaced_by": "name", "remove_after": "2027-03-31"}

    def test_a_type_carries_its_reason_and_its_links_say_which_type_they_took_it_from(self, deployer):
        _status(deployer, {"kind": "type", "object_type": "Customer", "status": "deprecated",
                           "reason": "Retiring customers."})

        schema = self._reader(deployer)

        assert schema["Customer"]["deprecation"]["reason"] == "Retiring customers."
        link = schema["Customer"]["fields"]["transactions"]
        assert link["status"] == "deprecated" and link["status_inherited_from"] == "Customer"

    def test_an_active_name_has_no_deprecation(self, deployer):
        schema = self._reader(deployer)

        assert schema["Customer"]["status"] == "active"
        assert schema["Customer"]["deprecation"] is None
        assert schema["Customer"]["fields"]["email"]["deprecation"] is None
