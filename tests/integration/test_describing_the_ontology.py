"""Describing the ontology from the UI (DEV_UI 13.7), over HTTP, against a
COPY of the fixture configuration -- these tests write the file."""

import yaml

from core.intermediate_layer.auth import UserRecord
from tests.conftest import read_audit_log, with_roles
from tests.integration import test_editing_config_from_the_ui as editing
from tests.integration.test_api import _csrf_headers, _login

# THE SAME FIXTURES as the settings editor's: a copy of the fixture
# configuration, and a person holding manage:deployment.
config_dir = editing.config_dir
deployer = editing.deployer

FILE = "ontology_schema.yaml"


def _read(client):
    response = client.get("/api/admin/ontology/descriptions")
    assert response.status_code == 200, response.text
    return response.json()


def _apply(client, changes, digest=None):
    return client.put("/api/admin/ontology/descriptions", headers=_csrf_headers(client),
                      json={"digest": digest or _read(client)["digest"], "changes": changes})


def test_it_reads_what_the_file_declares_and_absent_as_null(deployer):
    types = _read(deployer)["types"]

    # From the fixture: Customer declares a description, Transaction none.
    assert types["Customer"]["description"] == "A person or organisation the business serves."
    assert types["Transaction"]["description"] is None
    assert types["Customer"]["fields"]["email"]["kind"] == "data"


def test_a_preview_shows_the_lines_and_writes_nothing(deployer, config_dir):
    before = (config_dir / FILE).read_text()
    response = deployer.post("/api/admin/ontology/descriptions/preview", headers=_csrf_headers(deployer),
                             json={"digest": _read(deployer)["digest"],
                                   "changes": [{"object_type": "Transaction", "key": "display_name",
                                                "value": "Payment"}]})

    assert response.status_code == 200, response.text
    assert "+    display_name: Payment" in response.json()["diff"]
    assert (config_dir / FILE).read_text() == before


def test_an_applied_description_reaches_every_reader(deployer, config_dir):
    before = deployer.app.state.generation.generation

    response = _apply(deployer, [
        {"object_type": "Transaction", "key": "display_name", "value": "Payment"},
        {"object_type": "Customer", "field": "email", "key": "description", "value": "Where we write."}])

    assert response.status_code == 200, response.text
    assert deployer.app.state.generation.generation > before
    # A person who may read Transaction is served the new name.
    generation = deployer.app.state.generation
    served = generation.mediator.visible_schema(UserRecord("", None, "debug"))
    assert served["Transaction"]["display_name"] == "Payment"
    assert yaml.safe_load((config_dir / FILE).read_text())["object_types"]["Customer"]["fields"][
        "email"]["description"] == "Where we write."


def test_only_the_changed_lines_differ(deployer, config_dir):
    before = (config_dir / FILE).read_text().splitlines()

    assert _apply(deployer, [{"object_type": "Customer", "key": "group", "value": "People"}]).status_code == 200

    after = (config_dir / FILE).read_text().splitlines()
    assert [line for line in after if line not in before] == ["    group: People"]
    assert len(after) == len(before) + 1


def test_a_change_since_it_was_read_is_refused_not_overwritten(deployer, config_dir):
    stale = _read(deployer)["digest"]
    path = config_dir / FILE
    path.write_text(path.read_text() + "\n# an operator's hand edit\n")

    response = _apply(deployer, [{"object_type": "Customer", "key": "group", "value": "x"}], digest=stale)

    assert response.status_code == 409
    assert "an operator's hand edit" in path.read_text()


def test_a_title_the_loader_refuses_never_reaches_the_disk(deployer, config_dir):
    """title_field must name a data field; the loader is the judge, and
    the editor runs it before writing anything."""
    before = (config_dir / FILE).read_text()

    response = _apply(deployer, [{"object_type": "Customer", "key": "title_field", "value": "nonesuch"}])

    assert response.status_code == 400
    assert "would not load" in response.json()["detail"]
    assert (config_dir / FILE).read_text() == before


def test_security_is_out_of_reach_however_it_is_asked(deployer, config_dir):
    before = (config_dir / FILE).read_text()

    response = _apply(deployer, [{"object_type": "Customer", "key": "security", "value": "none"}])

    assert response.status_code == 400
    assert (config_dir / FILE).read_text() == before


def test_it_is_audited_with_who_and_what(deployer):
    assert _apply(deployer, [{"object_type": "Customer", "field": "name", "key": "display_name",
                              "value": "Full name"}]).status_code == 200

    entries = [e for e in read_audit_log(deployer.app.state.runtime_paths.log_dir)
               if e.get("stage") == "config_edit"]
    assert entries[-1]["file"] == FILE
    assert entries[-1]["changes"] == {"Customer.name.display_name": "Full name"}


def test_it_is_recorded_as_a_generation_with_the_new_file(deployer, config_dir):
    before = deployer.app.state.generation.generation
    after = _apply(deployer, [{"object_type": "Customer", "key": "group", "value": "People"}]).json()

    # Read from the store: the reload has replaced the role this test
    # granted in memory, so the history ROUTE now refuses the caller.
    changed = deployer.app.state.config_history.diff(before, after["to_generation"])

    assert list(changed) == [FILE]
    assert "group: People" in changed[FILE][1]


def test_someone_who_manages_users_but_not_the_deployment_may_not(config_dir, client):
    with_roles(client.app, admin_only={"allowed_actions": frozenset(["manage:users"])})
    client.app.state.user_directory.create_user("hr", "correct-pw", "us-west", "admin_only")
    _login(client, "hr", "correct-pw")

    assert client.get("/api/admin/ontology/descriptions").status_code == 403
    assert client.put("/api/admin/ontology/descriptions", headers=_csrf_headers(client),
                      json={"digest": "x", "changes": [{"object_type": "Customer", "key": "group",
                                                        "value": "x"}]}).status_code == 403
