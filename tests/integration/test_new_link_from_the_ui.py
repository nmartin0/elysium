"""Adding a link from the UI (the ontology's shape, 27 October), over HTTP
against a COPY of the fixture configuration -- these tests write the file.

The rules under test: the form is offered the types and the columns of the
table each is built over; a link is written and reloaded as one generation,
both directions from the one declaration; nobody can read either new
field until a grant names it; the preview says whether the source has the
column or the join table; and a name a type already uses is refused,
before anything is written.
"""

import difflib

import pytest
import yaml

from tests.conftest import read_audit_log
from tests.integration import test_editing_config_from_the_ui as editing
from tests.integration.test_api import _csrf_headers, _login

config_dir = editing.config_dir
deployer = editing.deployer
FILE = "ontology_schema.yaml"

PURCHASES = {
    "name": "CustomerPurchases",
    "source": {"object_type": "Customer", "api_name": "purchases"},
    "target": {"object_type": "Transaction", "api_name": "buyer"},
    "cardinality": "one_to_many", "foreign_key_column": "customer_id",
}
LABELS = {
    "name": "CustomerLabels",
    "source": {"object_type": "Customer", "api_name": "labels"},
    "target": {"object_type": "Tag", "api_name": "labelled"},
    "cardinality": "many_to_many",
    "join_table": {"table": "customer_tags", "source_column": "customer_id", "target_column": "tag_id"},
}


def _digest(client):
    return client.get("/api/admin/ontology/descriptions").json()["digest"]


def _link(client, body=None, preview=False, **given):
    body = {**(body or PURCHASES), "digest": given.pop("digest", None) or _digest(client), **given}
    path = "/api/admin/ontology/links" + ("/preview" if preview else "")
    send = client.post if preview else client.put
    return send(path, headers=_csrf_headers(client), json=body)


def _links(config_dir):
    return yaml.safe_load((config_dir / FILE).read_text())["link_types"]


class TestWhatTheFormOffers:
    def test_the_types_and_the_source_each_is_built_over(self, deployer):
        types = {t["name"]: t for t in deployer.get("/api/admin/ontology/linkable-types").json()["types"]}

        assert {"Customer", "Transaction", "Tag"} <= set(types)
        assert types["Customer"]["silo"] == "primary_sql"

    def test_the_columns_of_the_table_a_type_is_built_over(self, deployer):
        columns = deployer.get("/api/admin/ontology/linkable-types/Transaction/columns").json()["columns"]

        assert {"transaction_id", "customer_id", "amount"} <= set(columns)

    def test_a_source_that_cannot_be_asked_says_null(self, deployer, monkeypatch):
        monkeypatch.setattr("api.routes.live_source_adapters", lambda request: {"primary_sql": object()})

        assert deployer.get("/api/admin/ontology/linkable-types/Transaction/columns").json() == {"columns": None}

    def test_an_unknown_type_is_not_found(self, deployer):
        assert deployer.get("/api/admin/ontology/linkable-types/Nobody/columns").status_code == 404

    def test_only_a_manager_of_the_deployment_is_offered_any_of_it(self, deployer):
        deployer.cookies.clear()
        deployer.app.state.user_directory.create_user("pat", "correct-pw", "us-west", "customer_service")
        _login(deployer, "pat", "correct-pw")

        for path in ("/api/admin/ontology/linkable-types", "/api/admin/ontology/linkable-types/Customer/columns"):
            assert deployer.get(path).status_code == 403, path
        assert _link(deployer, digest="x").status_code == 403
        assert _link(deployer, digest="x", preview=True).status_code == 403


class TestAddingALink:
    def test_it_is_written_and_reloaded_as_one_generation(self, deployer, config_dir):
        before = deployer.app.state.generation.generation

        response = _link(deployer)

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "applied"
        assert response.json()["to_generation"] == before + 1
        assert _links(config_dir)["CustomerPurchases"]["foreign_key_column"] == "customer_id"
        schema = deployer.app.state.generation.config.schema
        assert schema["Customer"]["fields"]["purchases"]["target"] == "Transaction"
        assert schema["Transaction"]["fields"]["buyer"]["target"] == "Customer"

    def test_a_many_to_many_link_is_written_with_its_join_table(self, deployer, config_dir):
        response = _link(deployer, LABELS)

        assert response.status_code == 200, response.text
        assert _links(config_dir)["CustomerLabels"]["join_table"]["table"] == "customer_tags"

    def test_nothing_already_in_the_file_changes(self, deployer, config_dir):
        before = (config_dir / FILE).read_text()

        _link(deployer)

        removed = [line for line in difflib.ndiff(before.splitlines(), (config_dir / FILE).read_text().splitlines())
                   if line[0] == "-"]
        assert removed == []

    def test_the_change_is_audited(self, deployer):
        _link(deployer)

        entries = [e for e in read_audit_log(deployer.app.state.runtime_paths.log_dir)
                   if e.get("stage") == "config_edit" and e.get("file") == FILE]
        assert entries[-1]["outcome"] == "applied" and entries[-1]["user_id"] == "ops"

    def test_nobody_can_read_either_new_field_until_a_grant_names_it(self, deployer):
        _link(deployer)
        deployer.app.state.user_directory.create_user("carla", "correct-pw", "us-west", "customer_service")
        deployer.cookies.clear()
        _login(deployer, "carla", "correct-pw")

        schema = deployer.get("/api/me/visible-schema").json()

        assert "purchases" not in schema["Customer"]["fields"]
        assert "buyer" not in schema.get("Transaction", {}).get("fields", {})

    @pytest.mark.parametrize("given, said", [
        ({"name": "CustomerTransactions"}, "already a link type"),
        ({"source": {"object_type": "Customer", "api_name": "transactions"}}, "already has a field or link"),
        ({"source": {"object_type": "Nobody", "api_name": "x"}}, "no object type"),
        ({"cardinality": "many"}, "relationship is one of"),
        ({"foreign_key_column": None}, "needs the column"),
    ])
    def test_a_refusal_writes_nothing(self, deployer, config_dir, given, said):
        before = (config_dir / FILE).read_text()

        response = _link(deployer, {**PURCHASES, **given})

        assert response.status_code == 400 and said in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before

    def test_a_stale_view_is_refused(self, deployer, config_dir):
        digest = _digest(deployer)
        path = config_dir / FILE
        path.write_text(path.read_text() + "\n# an operator was here\n")

        assert _link(deployer, digest=digest).status_code == 409
        assert "CustomerPurchases" not in path.read_text()

    def test_the_loader_has_the_last_word(self, deployer, config_dir, monkeypatch):
        before = (config_dir / FILE).read_text()
        broken = before.replace("  Customer:\n", "  Customer:\n    not_a_known_key_at_all: [\n", 1)
        monkeypatch.setattr("core.config_editing.apply_new_link", lambda *given: broken)

        assert _link(deployer).status_code == 400
        assert (config_dir / FILE).read_text() == before


# NOT TESTED HERE, AND WHY: the apply route waits for a second person when
# the permission code says a new link widens access, exactly as the field and
# type routes do. No policy can say that today -- a grant names a field that
# exists, and a link's two fields are born with it, so nothing grants them (the
# fixture has no wildcard grants). The waiting path is the same code the field
# and type routes run (_reason, the proposals store) and is tested there.


class TestThePreview:
    def test_it_writes_nothing_and_says_nothing_widens(self, deployer, config_dir):
        before = (config_dir / FILE).read_text()

        preview = _link(deployer, preview=True)

        assert preview.status_code == 200, preview.text
        assert preview.json()["needs_approval"] is False
        assert any("CustomerPurchases:" in line for line in preview.json()["diff"])
        assert (config_dir / FILE).read_text() == before

    def test_it_says_when_the_column_is_not_in_the_table(self, deployer):
        good = _link(deployer, preview=True).json()
        bad = _link(deployer, {**PURCHASES, "foreign_key_column": "nope"}, preview=True).json()

        assert good["problems"] == [] and good["checked"] is True
        assert bad["problems"] == ["The table transactions has no column nope."]

    def test_it_says_when_the_join_table_or_its_columns_are_not_there(self, deployer):
        good = _link(deployer, LABELS, preview=True).json()
        no_table = _link(deployer, {**LABELS, "join_table": {**LABELS["join_table"], "table": "nope"}},
                         preview=True).json()
        no_column = _link(deployer, {**LABELS, "join_table": {**LABELS["join_table"], "target_column": "ghost"}},
                          preview=True).json()

        assert good["problems"] == [] and good["checked"] is True
        assert no_table["problems"] == ["The source has no table nope."]
        assert no_column["problems"] == ["The table customer_tags has no column ghost."]

    def test_a_source_that_cannot_say_is_not_checked(self, deployer, monkeypatch):
        monkeypatch.setattr("api.routes.live_source_adapters", lambda request: {"primary_sql": object()})

        found = _link(deployer, preview=True).json()

        assert found["problems"] == [] and found["checked"] is False
