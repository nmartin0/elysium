"""Adding a type from the UI (the ontology's shape, 27 October), over HTTP
against a COPY of the fixture configuration -- these tests write the files.

The rules under test: the form is offered what the deployment's sources
hold; a new type is written, bound and reloaded as one generation; its row
rule is chosen, and `inherit` follows the source's; nobody can read it
until a role is granted it; and it waits for a second person EXACTLY WHEN
the permission code says someone could learn more (listing it to everyone).
"""

import difflib

import pytest
import yaml

from tests.integration import test_editing_config_from_the_ui as editing
from tests.integration.test_api import _csrf_headers, _login
from tests.integration.test_new_fields_from_the_ui import two_files  # noqa: F401  (a fixture)

config_dir = editing.config_dir
deployer = editing.deployer
FILE = "ontology_schema.yaml"
SILOS = "data_silos.yaml"

BUYER = {"name": "Buyer", "silo": "primary_sql", "table": "customers", "id_column": "customer_id",
         "fields": [{"name": "name"}, {"name": "region"}], "security": {"field": "region"}}


def _digest(client):
    return client.get("/api/admin/ontology/descriptions").json()["digest"]


def _type(client, body=None, preview=False, **given):
    body = {**(body or BUYER), "digest": given.pop("digest", None) or _digest(client), **given}
    path = "/api/admin/ontology/types" + ("/preview" if preview else "")
    send = client.post if preview else client.put
    return send(path, headers=_csrf_headers(client), json=body)


def _declared(config_dir):
    return yaml.safe_load((config_dir / FILE).read_text())["object_types"]


def _silo_rule(config_dir, client, rule):
    path = config_dir / SILOS
    silos = yaml.safe_load(path.read_text())
    silos["data_silos"]["primary_sql"]["security"] = rule
    path.write_text(yaml.safe_dump(silos))
    from api.reload import reload_generation
    reload_generation(client.app, requested_by="test")
    editing._grant(client)   # a reload rebuilds the roles the fixture granted in memory


class TestWhatTheFormOffers:
    def test_the_sources_and_the_rule_each_declares(self, deployer, config_dir):
        offered = {s["silo"]: s["rule"] for s in deployer.get("/api/admin/ontology/sources").json()["silos"]}
        assert offered["primary_sql"] is None

        _silo_rule(config_dir, deployer, {"field": "region"})
        offered = {s["silo"]: s["rule"] for s in deployer.get("/api/admin/ontology/sources").json()["silos"]}
        assert offered["primary_sql"] == {"field": "region"}

    def test_the_tables_and_columns_a_source_holds(self, deployer):
        tables = deployer.get("/api/admin/ontology/sources/primary_sql/tables").json()["tables"]
        columns = deployer.get("/api/admin/ontology/sources/primary_sql/columns",
                               params={"table": "customers"}).json()["columns"]

        assert "customers" in tables and "transactions" in tables
        assert not [t for t in tables if t.startswith("sqlite_")]
        assert {"customer_id", "name", "region"} <= set(columns)

    def test_a_source_that_cannot_be_asked_says_null_so_the_form_takes_it_by_hand(self, deployer, monkeypatch):
        monkeypatch.setattr("api.routes.live_source_adapters", lambda request: {"primary_sql": object()})

        assert deployer.get("/api/admin/ontology/sources/primary_sql/tables").json() == {"tables": None}
        assert deployer.get("/api/admin/ontology/sources/primary_sql/columns",
                            params={"table": "customers"}).json() == {"columns": None}

    def test_an_unknown_source_is_not_found(self, deployer):
        assert deployer.get("/api/admin/ontology/sources/nowhere/tables").status_code == 404

    def test_only_a_manager_of_the_deployment_is_offered_any_of_it(self, deployer):
        deployer.cookies.clear()
        deployer.app.state.user_directory.create_user("pat", "correct-pw", "us-west", "customer_service")
        _login(deployer, "pat", "correct-pw")

        for path in ("/api/admin/ontology/sources", "/api/admin/ontology/sources/primary_sql/tables",
                     "/api/admin/ontology/sources/primary_sql/columns?table=customers"):
            assert deployer.get(path).status_code == 403, path
        assert _type(deployer, digest="x").status_code == 403
        assert _type(deployer, digest="x", preview=True).status_code == 403


class TestAddingAType:
    def test_it_is_written_and_reloaded_as_one_generation(self, deployer, config_dir):
        before = deployer.app.state.generation.generation

        response = _type(deployer)

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "applied"
        assert response.json()["to_generation"] == before + 1
        assert _declared(config_dir)["Buyer"]["security"] == {"field": "region"}
        assert deployer.app.state.generation.config.schema["Buyer"]["storage"]["table"] == "customers"

    def test_everything_else_in_the_file_is_as_it_was(self, deployer, config_dir):
        before = (config_dir / FILE).read_text()

        _type(deployer)

        removed = [line for line in difflib.ndiff(before.splitlines(), (config_dir / FILE).read_text().splitlines())
                   if line[0] == "-"]
        assert removed == []

    def test_the_change_is_audited(self, deployer):
        from tests.conftest import read_audit_log

        _type(deployer)

        entries = [e for e in read_audit_log(deployer.app.state.runtime_paths.log_dir)
                   if e.get("stage") == "config_edit" and e.get("file") == FILE]
        assert entries[-1]["outcome"] == "applied" and entries[-1]["user_id"] == "ops"

    def test_nobody_can_read_it_and_nobody_is_told_it_exists(self, deployer):
        _type(deployer)
        deployer.app.state.user_directory.create_user("carla", "correct-pw", "us-west", "customer_service")
        deployer.cookies.clear()
        _login(deployer, "carla", "correct-pw")

        assert "Buyer" not in deployer.get("/api/me/visible-schema").json()

    def test_inherit_follows_the_sources_rule_live(self, deployer, config_dir):
        _silo_rule(config_dir, deployer, {"field": "region"})

        response = _type(deployer, {**BUYER, "security": "inherit"})

        assert response.status_code == 200, response.text
        assert _declared(config_dir)["Buyer"]["security"] == "inherit"
        assert deployer.app.state.generation.mediator.schema["Buyer"]["security"] == {"field": "region"}

    def test_inherit_from_a_source_with_no_rule_is_refused_and_writes_nothing(self, deployer, config_dir):
        before = (config_dir / FILE).read_text()

        response = _type(deployer, {**BUYER, "security": "inherit"})

        assert response.status_code == 400 and "declares no row rule" in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before

    @pytest.mark.parametrize("given, said", [
        ({"security": None}, "Choose who may see"),
        ({"name": "Customer"}, "already an object type"),
        ({"silo": "nowhere"}, "no source"),
        ({"fields": []}, "at least one field"),
    ])
    def test_a_refusal_writes_nothing(self, deployer, config_dir, given, said):
        before = (config_dir / FILE).read_text()

        response = _type(deployer, {**BUYER, **given})

        assert response.status_code == 400 and said in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before

    def test_a_stale_view_is_refused(self, deployer, config_dir):
        digest = _digest(deployer)
        path = config_dir / FILE
        path.write_text(path.read_text() + "\n# an operator was here\n")

        assert _type(deployer, digest=digest).status_code == 409
        assert "Buyer" not in path.read_text()

    def test_the_loader_has_the_last_word(self, deployer, config_dir, monkeypatch):
        before = (config_dir / FILE).read_text()
        broken = before.replace("  Customer:\n", "  Customer:\n    not_a_known_key_at_all: [\n", 1)
        monkeypatch.setattr("core.config_editing.apply_new_type", lambda *given: (broken, None))

        assert _type(deployer).status_code == 400
        assert (config_dir / FILE).read_text() == before


class TestThePreview:
    def test_it_writes_nothing_and_says_nothing_widens(self, deployer, config_dir):
        before = (config_dir / FILE).read_text()

        preview = _type(deployer, preview=True)

        assert preview.status_code == 200, preview.text
        assert preview.json()["needs_approval"] is False
        assert any(line == "+  Buyer:" for line in preview.json()["diff"])
        assert (config_dir / FILE).read_text() == before

    def test_it_says_whether_the_source_has_the_table_and_columns(self, deployer):
        good = _type(deployer, preview=True).json()
        bad = _type(deployer, {**BUYER, "table": "nope"}, preview=True).json()
        ghost = {**BUYER, "security": "unrestricted", "fields": [{"name": "name"}, {"name": "ghost"}]}
        odd = _type(deployer, ghost, preview=True).json()

        assert good["source_has_table"] is True and good["columns_missing"] == []
        assert bad["source_has_table"] is False
        assert odd["columns_missing"] == ["ghost"]

    def test_a_source_that_cannot_say_is_not_checked(self, deployer, monkeypatch):
        monkeypatch.setattr("api.routes.live_source_adapters", lambda request: {"primary_sql": object()})

        found = _type(deployer, preview=True).json()

        assert found["source_has_table"] is None and found["columns_checked"] is False


class TestListingItToEveryone:
    def test_it_says_the_type_exists_so_it_waits_with_a_reason(self, deployer, config_dir):
        before = (config_dir / FILE).read_text()
        listed = {**BUYER, "discoverable": True}

        preview = _type(deployer, listed, preview=True).json()
        refused = _type(deployer, listed)
        waiting = _type(deployer, listed, reason="Heliograph wants it findable")

        assert preview["needs_approval"] is True
        assert refused.status_code == 400 and "Say why" in refused.json()["detail"]
        assert waiting.json()["status"] == "waiting"
        assert (config_dir / FILE).read_text() == before


class TestTheBindings:
    def test_the_source_is_bound_in_the_bindings_file_in_the_same_generation(self, two_files, config_dir):  # noqa: F811
        before = two_files.app.state.generation.generation

        response = _type(two_files)

        assert response.status_code == 200, response.text
        assert response.json()["to_generation"] == before + 1
        assert "storage" not in _declared(config_dir)["Buyer"]
        bound = yaml.safe_load((config_dir / "source_bindings.yaml").read_text())["object_types"]["Buyer"]
        assert bound["storage"]["table"] == "customers"

    def test_the_preview_names_the_bindings_file_and_does_not_show_it(self, two_files):  # noqa: F811
        preview = _type(two_files, preview=True).json()

        assert any("source_bindings.yaml" in line and "not shown" in line for line in preview["diff"])
        assert not any("table: customers" in line for line in preview["diff"])
