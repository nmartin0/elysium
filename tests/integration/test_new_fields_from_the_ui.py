"""Adding a field from the UI (the ontology's shape, agreed 26 October),
over HTTP against a COPY of the fixture configuration -- these tests
write the files.

The rules under test: a new field is written, bound and reloaded as one
generation; nobody can read it until a grant names it; the preview says
whether the source has the column; and it waits for a second person
EXACTLY WHEN the permission code says someone could read more.
"""

import difflib

import pytest
import yaml

from core.ontology.bindings import split_bindings
from tests.conftest import read_audit_log
from tests.integration import test_access_labels as labelled
from tests.integration import test_editing_config_from_the_ui as editing
from tests.integration.test_api import _csrf_headers, _login

config_dir = editing.config_dir
FILE = "ontology_schema.yaml"
BINDINGS = "source_bindings.yaml"


deployer = editing.deployer


@pytest.fixture
def enforcing(config_dir, request):
    return labelled._deployment(config_dir, request, enforcing=True)


@pytest.fixture
def two_files(config_dir, request):
    """The same deployment with its bindings in source_bindings.yaml."""
    schema = yaml.safe_load((config_dir / FILE).read_text())
    declaration, bindings = split_bindings(schema["object_types"])
    (config_dir / FILE).write_text(yaml.safe_dump({**schema, "object_types": declaration}, sort_keys=False))
    (config_dir / BINDINGS).write_text(yaml.safe_dump({"object_types": bindings}, sort_keys=False))
    return request.getfixturevalue("deployer")


def _digest(client):
    return client.get("/api/admin/ontology/descriptions").json()["digest"]


def _fields(client, *fields, reason=None, preview=False, digest=None):
    body = {"digest": digest or _digest(client), "fields": list(fields), "reason": reason}
    if preview:
        return client.post("/api/admin/ontology/fields/preview", headers=_csrf_headers(client), json=body)
    return client.put("/api/admin/ontology/fields", headers=_csrf_headers(client), json=body)


NICKNAME = {"object_type": "Customer", "name": "nickname", "description": "What they go by"}


def _declared(config_dir):
    return yaml.safe_load((config_dir / FILE).read_text())["object_types"]


class TestWhatTheFormOffers:
    def test_the_data_types_are_the_mirrors_own_list(self, deployer):
        from core.ontology.field_types import FIELD_DATA_TYPES

        offered = deployer.get("/api/admin/ontology/descriptions").json()["data_types"]

        assert offered == list(FIELD_DATA_TYPES) and "decimal" in offered

    def test_every_one_is_accepted(self, deployer):
        offered = deployer.get("/api/admin/ontology/descriptions").json()["data_types"]

        for index, data_type in enumerate(offered):
            response = _fields(deployer, {"object_type": "Customer", "name": f"f{index}",
                                          "data_type": data_type}, preview=True)
            assert response.status_code == 200, (data_type, response.text)


class TestAddingAField:
    def test_it_is_written_and_reloaded_as_one_generation(self, deployer, config_dir):
        before = deployer.app.state.generation.generation

        response = _fields(deployer, NICKNAME)

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "applied"
        assert response.json()["to_generation"] == before + 1
        assert _declared(config_dir)["Customer"]["fields"]["nickname"] == {
            "type": "data", "description": "What they go by"}
        assert deployer.app.state.generation.mediator.schema["Customer"]["fields"]["nickname"]

    def test_everything_else_in_the_file_is_as_it_was(self, deployer, config_dir):
        before = (config_dir / FILE).read_text()

        _fields(deployer, NICKNAME)

        changes = [line for line in difflib.ndiff(before.splitlines(), (config_dir / FILE).read_text().splitlines())
                   if line[0] in "+-"]
        assert changes == ["+       nickname:", "+         type: data", "+         description: What they go by"]

    def test_the_change_is_audited(self, deployer):
        _fields(deployer, NICKNAME)

        entries = [e for e in read_audit_log(deployer.app.state.runtime_paths.log_dir)
                   if e.get("stage") == "config_edit" and e.get("file") == FILE]
        assert entries[-1]["outcome"] == "applied" and entries[-1]["user_id"] == "ops"

    def test_nobody_can_read_it_until_a_grant_names_it(self, deployer):
        _fields(deployer, NICKNAME)
        deployer.app.state.user_directory.create_user("carla", "correct-pw", "us-west", "customer_service")
        deployer.cookies.clear()
        _login(deployer, "carla", "correct-pw")

        fields = deployer.get("/api/me/visible-schema").json()["Customer"]["fields"]

        assert "email" in fields and "nickname" not in fields

    def test_a_stale_view_is_refused(self, deployer, config_dir):
        digest = _digest(deployer)
        path = config_dir / FILE
        path.write_text(path.read_text() + "\n# an operator was here\n")

        response = _fields(deployer, NICKNAME, digest=digest)

        assert response.status_code == 409
        assert "nickname" not in path.read_text()

    @pytest.mark.parametrize("field, said", [
        ({"object_type": "Customer", "name": "email"}, "already a field"),
        ({"object_type": "Nobody", "name": "x"}, "no object type"),
        ({"object_type": "Customer", "name": "x", "data_type": "blob"}, "data type"),
    ])
    def test_a_refusal_writes_nothing(self, deployer, config_dir, field, said):
        before = (config_dir / FILE).read_text()

        response = _fields(deployer, field)

        assert response.status_code == 400 and said in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before

    def test_the_loader_has_the_last_word(self, deployer, config_dir, monkeypatch):
        """Whatever the editor writes, the loader judges it before it
        lands: a result that would not load is refused, with the loader's
        reason, and the file is not touched."""
        before = (config_dir / FILE).read_text()
        broken = before.replace("  Customer:\n", "  Customer:\n    not_a_known_key_at_all: [\n", 1)
        monkeypatch.setattr("core.config_editing.apply_new_fields", lambda *given: (broken, None))

        response = _fields(deployer, NICKNAME)

        assert response.status_code == 400
        assert (config_dir / FILE).read_text() == before

    def test_a_person_who_cannot_manage_the_deployment_is_refused(self, deployer):
        deployer.cookies.clear()
        deployer.app.state.user_directory.create_user("pat", "correct-pw", "us-west", "customer_service")
        _login(deployer, "pat", "correct-pw")

        assert _fields(deployer, NICKNAME, digest="x").status_code == 403
        assert _fields(deployer, NICKNAME, digest="x", preview=True).status_code == 403


class TestThePreview:
    def test_it_writes_nothing_and_says_nothing_widens(self, deployer, config_dir):
        before = (config_dir / FILE).read_text()

        preview = _fields(deployer, NICKNAME, preview=True)

        assert preview.status_code == 200, preview.text
        assert preview.json()["needs_approval"] is False
        assert preview.json()["impact"]["roles"] == []
        assert any(line == "+      nickname:" for line in preview.json()["diff"])
        assert (config_dir / FILE).read_text() == before

    def test_it_says_whether_the_source_has_the_column(self, deployer):
        has = {"object_type": "Customer", "name": "nick", "column": "name"}
        lacks = {"object_type": "Customer", "name": "nickname"}

        found = _fields(deployer, has, lacks, preview=True).json()["fields"]

        assert found == [
            {"object_type": "Customer", "field": "nick", "column": "name", "source_has_column": True},
            {"object_type": "Customer", "field": "nickname", "column": "nickname", "source_has_column": False}]

    def test_a_source_that_cannot_say_is_not_checked(self, deployer, monkeypatch):
        class Down:
            def columns_present(self, table):
                raise RuntimeError("down")

        monkeypatch.setattr("api.routes.live_source_adapters", lambda request: {"primary_sql": Down()})

        found = _fields(deployer, NICKNAME, preview=True).json()["fields"]

        assert found[0]["source_has_column"] is None

    def test_a_source_that_reports_no_columns_is_not_checked(self, deployer, monkeypatch):
        """An empty answer is how an adapter says it does not know, as the
        sync reads it -- not "the table has no columns"."""
        class Unknown:
            def columns_present(self, table):
                return set()

        monkeypatch.setattr("api.routes.live_source_adapters", lambda request: {"primary_sql": Unknown()})

        assert _fields(deployer, NICKNAME, preview=True).json()["fields"][0]["source_has_column"] is None

    def test_a_source_with_no_way_to_ask_is_not_checked(self, deployer, monkeypatch):
        monkeypatch.setattr("api.routes.live_source_adapters", lambda request: {"primary_sql": object()})

        assert _fields(deployer, NICKNAME, preview=True).json()["fields"][0]["source_has_column"] is None


class TestTheBindings:
    def test_the_column_is_bound_in_the_bindings_file_in_the_same_generation(self, two_files, config_dir):
        before = two_files.app.state.generation.generation

        response = _fields(two_files, {**NICKNAME, "column": "name"})

        assert response.status_code == 200, response.text
        assert response.json()["to_generation"] == before + 1
        assert "column" not in _declared(config_dir)["Customer"]["fields"]["nickname"]
        bound = yaml.safe_load((config_dir / BINDINGS).read_text())["object_types"]["Customer"]["fields"]
        assert bound["nickname"] == {"column": "name"}

    def test_the_preview_names_the_bindings_file_and_does_not_show_it(self, two_files):
        preview = _fields(two_files, {**NICKNAME, "column": "name"}, preview=True).json()

        assert any(BINDINGS in line and "not shown" in line for line in preview["diff"])
        assert not any("column: name" in line for line in preview["diff"])


class TestWhenAGrantAlreadyNamesIt:
    """labelled_reader holds read:label:pii and no field by name: a new
    field labelled pii is readable by it the moment it exists. Not
    access-neutral, so it waits -- asked of the permission code."""

    PII = {"object_type": "Customer", "name": "passport", "labels": ["pii"]}

    def test_it_waits_with_a_reason(self, enforcing, config_dir):
        before = (config_dir / FILE).read_text()

        preview = _fields(enforcing, self.PII, preview=True).json()
        refused = _fields(enforcing, self.PII)
        waiting = _fields(enforcing, self.PII, reason="passports are collected now")

        assert preview["needs_approval"] is True
        gained = {(r["role"], f["field"]) for r in preview["impact"]["roles"] for f in r["fields_gained"]}
        assert ("labelled_reader", "passport") in gained
        assert refused.status_code == 400 and "Say why" in refused.json()["detail"]
        assert waiting.json()["status"] == "waiting"
        assert (config_dir / FILE).read_text() == before

    def test_the_second_person_applies_it(self, enforcing, config_dir):
        _fields(enforcing, self.PII, reason="passports are collected now")
        labelled._as(enforcing, "rita")
        [proposal] = enforcing.get("/api/admin/config-proposals").json()["proposals"]

        assert proposal["kind"] == "shape" and proposal["reason"] == "passports are collected now"
        response = enforcing.post(f"/api/admin/config-proposals/{proposal['proposal_id']}/approve",
                                  headers=_csrf_headers(enforcing))

        assert response.status_code == 200, response.text
        assert "passport" in _declared(config_dir)["Customer"]["fields"]

    def test_the_proposer_cannot_approve_their_own(self, enforcing):
        from api.reload import reload_generation

        labelled._roles(enforcing.app.state.runtime_paths.config_dir, both=["manage:deployment", "manage:roles"])
        reload_generation(enforcing.app, requested_by="test")
        enforcing.app.state.user_directory.create_user("bea", "correct-pw", "us-west", "both")
        labelled._as(enforcing, "bea")
        _fields(enforcing, self.PII, reason="passports are collected now")
        [proposal] = enforcing.get("/api/admin/config-proposals").json()["proposals"]

        response = enforcing.post(f"/api/admin/config-proposals/{proposal['proposal_id']}/approve",
                                  headers=_csrf_headers(enforcing))

        assert response.status_code == 409
