"""An enriched field end to end (R41): declared, empty until a recipe is
approved, then filled at the next sync and served like any field --
searchable, marked inferred -- through the API.

Against a COPY of the fixture configuration with one enriched field
added, so nothing shared is written and no other test sees the field.
"""

import contextlib
import io
import json
import shutil

import pytest
import yaml
from fastapi.testclient import TestClient

import tests.integration.conftest as integration_conftest
from tests.integration.test_api import _login  # noqa: F401

RULES = [
    {"when": [{"field": "subject", "contains_any": ["refund"]}], "then": "refund"},
    {"when": [{"field": "subject", "contains_any": ["billing address"]}], "then": "billing"},
]


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    from core.deployment_loader import RuntimePaths

    # As the shared `client` fixture does: TestClient speaks plain http,
    # and a Secure cookie is never sent back over it.
    monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")

    config = tmp_path / "config"
    shutil.copytree(integration_conftest.FIXTURES_DIR, config)
    ontology = yaml.safe_load((config / "ontology_schema.yaml").read_text())
    ontology["object_types"]["SupportTicket"]["fields"]["topic"] = {
        "enrich": {"from": ["subject"], "instruction": "What the ticket is about.",
                   "choices": ["billing", "technical", "refund"]}}
    (config / "ontology_schema.yaml").write_text(yaml.safe_dump(ontology))
    policy = yaml.safe_load((config / "policy.yaml").read_text())
    policy["roles"]["debug"]["allowed_actions"] += [
        "read:SupportTicket", "read:SupportTicket.ticket_id", "read:SupportTicket.subject",
        "read:SupportTicket.topic"]
    # And a role that may READ the field and its input but not manage the
    # deployment -- so the review tests below refuse it for the grant
    # they are about, not for a missing read. (A first version gave it no
    # read on topic, and its test passed with the grant check deleted.)
    policy["roles"]["customer_service"]["allowed_actions"] += [
        "read:SupportTicket", "read:SupportTicket.subject", "read:SupportTicket.topic"]
    (config / "policy.yaml").write_text(yaml.safe_dump(policy))

    data = tmp_path / "data"
    fixtures = data / "dev_fixtures"
    fixtures.mkdir(parents=True)
    for sql, db in (("schema.sql", "mediator.db"), ("support_schema.sql", "support.db"),
                    ("risk_schema.sql", "risk.db")):
        integration_conftest._build_sqlite_db(integration_conftest.FIXTURES_DIR / sql, fixtures / db)
    (tmp_path / "log").mkdir()
    return RuntimePaths(config_dir=config, data_dir=data, log_dir=tmp_path / "log")


def _sync(paths):
    from scripts.run_sync import run_sync

    with contextlib.redirect_stdout(io.StringIO()):
        run_sync(paths)


def _client(paths):
    from api.app import create_app

    client = TestClient(create_app(paths))
    with contextlib.suppress(ValueError):  # made by an earlier app on the same data
        client.app.state.user_directory.create_user("ops", "correct-pw", "us-west", "debug")
    _login(client, "ops", "correct-pw")
    return client


def _topics(client):
    rows = client.get("/api/objects/SupportTicket/search?q=").json()["results"]
    return {row["fields"]["subject"]: row["fields"].get("topic") for row in rows}


def test_empty_until_approved_then_filled_and_searchable(deployment):
    from core.enrichment_recipes import EnrichmentRecipeStore
    from core.ontology.enriched_fields import declaration_hash, enrichment_of

    _sync(deployment)
    client = _client(deployment)

    schema = client.get("/api/me/visible-schema").json()
    assert schema["SupportTicket"]["fields"]["topic"]["inferred"] == "inferred from subject"
    # NOTHING APPROVED, NOTHING PUBLISHED.
    assert set(_topics(client).values()) == {None}

    field = yaml.safe_load((deployment.config_dir / "ontology_schema.yaml").read_text())[
        "object_types"]["SupportTicket"]["fields"]["topic"]
    store = EnrichmentRecipeStore(deployment.data_dir / "enrichment_recipes.db")
    recipe = store.propose("SupportTicket", "topic",
                           declaration_hash("SupportTicket", "topic", enrichment_of(field)),
                           RULES, {}, {})
    _sync(deployment)
    assert set(_topics(_client(deployment)).values()) == {None}, "proposed is not approved"

    store.decide(recipe, approve=True, by="ops")
    _sync(deployment)
    client = _client(deployment)

    # us-west sees cust_001's two tickets; no rule mentions a login error.
    assert _topics(client) == {"Login page returns a 500 error": None,
                               "Requesting a refund for hardware order": "refund"}
    # SERVED LIKE ANY FIELD: a filter on it finds it.
    conditions = json.dumps([{"field": "topic", "operator": "equals", "value": "refund"}])
    found = client.get("/api/objects/SupportTicket/matching-ids", params={"conditions": conditions})
    assert found.status_code == 200, found.text
    assert len(found.json()["object_ids"]) == 1


def test_an_approved_vote_fills_the_field_and_its_review_shows_every_set(deployment):
    """A combined recipe (EVAPORATE-Code+) is stored, reviewed and run like
    one set: gold takes the weighted vote, and a tie is left empty."""
    from core.enrichment_recipes import EnrichmentRecipeStore
    from core.ontology.enriched_fields import check_recipe, declaration_hash, enrichment_of

    _sync(deployment)
    field = yaml.safe_load((deployment.config_dir / "ontology_schema.yaml").read_text())[
        "object_types"]["SupportTicket"]["fields"]["topic"]
    enrichment = enrichment_of(field)
    vote = check_recipe({"combine": "weighted_vote", "members": [
        # "refund" alone says refund; the two lighter sets together say
        # billing for it, and win. "500 error": technical against
        # refund at equal weight -- a tie, so empty.
        {"weight": 2.0, "rules": [{"when": [{"field": "subject", "contains_any": ["refund"]}],
                                   "then": "refund"}]},
        {"weight": 1.5, "rules": [{"when": [{"field": "subject", "contains_any": ["hardware"]}],
                                   "then": "billing"}]},
        {"weight": 1.0, "rules": [{"when": [{"field": "subject", "contains_any": ["order"]}],
                                   "then": "billing"},
                                  {"when": [{"field": "subject", "contains_any": ["error"]}],
                                   "then": "technical"}]},
        {"weight": 1.0, "rules": [{"when": [{"field": "subject", "contains_any": ["500"]}],
                                   "then": "refund"}]}]}, enrichment)
    store = EnrichmentRecipeStore(deployment.data_dir / "enrichment_recipes.db")
    recipe_id = store.propose("SupportTicket", "topic",
                              declaration_hash("SupportTicket", "topic", enrichment), vote,
                              {"held_out": {"agreement": 1.0}, "chose": "vote"},
                              {"model": "m", "compartment": "us-west"})
    client = _client(deployment)
    [shown] = client.get("/api/enrichment-recipes").json()["recipes"]
    assert [rule_set["weight"] for rule_set in shown["rule_sets"]] == [2.0, 1.5, 1.0, 1.0]
    assert shown["rule_sets"][2]["rules"] == ["If subject mentions 'order': billing",
                                              "If subject mentions 'error': technical"]

    store.decide(recipe_id, approve=True, by="ops")
    _sync(deployment)
    assert _topics(_client(deployment)) == {"Login page returns a 500 error": None,
                                            "Requesting a refund for hardware order": "billing"}


def test_the_compile_script_proposes_and_changes_nothing(deployment, monkeypatch, capsys):
    """scripts/compile_enrichment.py against real gold and the recipe
    store, with the model scripted: it reads the field's inputs, labels a
    sample, proposes -- and the field stays empty until someone approves."""
    import scripts.compile_enrichment as script
    from core.enrichment_recipes import EnrichmentRecipeStore
    from tests.unit.test_enrichment_compiler import GOOD, ScriptedModel

    _sync(deployment)
    monkeypatch.setenv("ELYSIUM_CONFIG_DIR", str(deployment.config_dir))
    monkeypatch.setenv("ELYSIUM_DATA_DIR", str(deployment.data_dir))
    monkeypatch.setenv("ELYSIUM_LOG_DIR", str(deployment.log_dir))
    model = ScriptedModel(rule_sets=[GOOD])
    monkeypatch.setattr(script, "build_llm_adapter", lambda config, name: model)
    monkeypatch.setattr("sys.argv", ["compile_enrichment", "SupportTicket.topic",
                                     "--sample", "3", "--candidates", "1"])

    # TWO COMPARTMENTS (cust_001 is us-west, cust_003 us-east): it will not
    # sample across them, because whoever approves must be cleared for
    # every row the rules' words came from (R61's rule).
    assert script.main() == 1
    assert "2 security compartments" in capsys.readouterr().err
    assert model.calls == []

    # Within one: two tickets, too few to write rules from once the
    # held-out half is set aside -- said, and nothing proposed.
    monkeypatch.setattr("sys.argv", ["compile_enrichment", "SupportTicket.topic",
                                     "--sample", "3", "--candidates", "1",
                                     "--compartment", "us-west"])
    assert script.main() == 1
    out = capsys.readouterr().out
    assert "2 rows in compartment 'us-west'" in out
    assert "NOTHING PROPOSED" in out
    assert EnrichmentRecipeStore(deployment.data_dir / "enrichment_recipes.db").all() == []
    # Every label it got is cached: the next run asks the model nothing again.
    asked = len(model.calls)
    model.rule_sets = [GOOD]
    script.main()
    assert len(model.calls) == asked

    # WITH ENOUGH ROWS, it proposes -- stored, judged on rows it never
    # saw, and still nothing published.
    from tests.unit.test_enrichment_compiler import _rows

    # Ids no ticket has, so every row resolves to one (empty) compartment.
    monkeypatch.setattr(script, "_gold_rows",
                        lambda *a: [{**row, "ticket_id": 1000 + row["ticket_id"]} for row in _rows(16)])
    monkeypatch.setattr("sys.argv", ["compile_enrichment", "SupportTicket.topic",
                                     "--sample", "16", "--candidates", "1"])
    model.rule_sets = [GOOD]
    assert script.main() == 0
    assert "PROPOSED as" in capsys.readouterr().out
    [recipe] = EnrichmentRecipeStore(deployment.data_dir / "enrichment_recipes.db").all()
    assert recipe.status == "proposed"
    assert recipe.evaluation["held_out"]["agreement"] == 1.0
    assert recipe.provenance["sample"] == 16
    assert "compartment" in recipe.provenance
    _sync(deployment)
    assert set(_topics(_client(deployment)).values()) == {None}


class TestReviewingARecipe:
    """GET /api/enrichment-recipes and POST .../decide."""

    def _propose(self, deployment, compartment="us-west", digest=None):
        from core.enrichment_recipes import EnrichmentRecipeStore
        from core.ontology.enriched_fields import declaration_hash, enrichment_of

        field = yaml.safe_load((deployment.config_dir / "ontology_schema.yaml").read_text())[
            "object_types"]["SupportTicket"]["fields"]["topic"]
        digest = digest or declaration_hash("SupportTicket", "topic", enrichment_of(field))
        return EnrichmentRecipeStore(deployment.data_dir / "enrichment_recipes.db").propose(
            "SupportTicket", "topic", digest, RULES, {"held_out": {"agreement": 1.0}},
            {"model": "m", "compartment": compartment})

    def test_the_approver_reads_the_rules_in_plain_words_and_the_inbox_counts_it(self, deployment):
        _sync(deployment)
        self._propose(deployment)
        client = _client(deployment)

        [recipe] = client.get("/api/enrichment-recipes").json()["recipes"]
        assert recipe["rules"] == ["If subject mentions 'refund': refund",
                                   "If subject mentions 'billing address': billing"]
        assert recipe["current"] is True and recipe["status"] == "proposed"
        assert client.get("/api/me/inbox").json()["enrichment"] == 1

    def test_another_compartments_recipe_is_not_shown_or_decidable(self, deployment):
        """The rules' words came from us-east rows; a us-west reviewer is
        not cleared for them (R61's rule)."""
        _sync(deployment)
        recipe_id = self._propose(deployment, compartment="us-east")
        client = _client(deployment)

        assert client.get("/api/enrichment-recipes").json()["recipes"] == []
        assert client.get("/api/me/inbox").json()["enrichment"] == 0
        decided = client.post(f"/api/enrichment-recipes/{recipe_id}/decide", json={"approve": True},
                              headers=_csrf(client))
        assert decided.status_code == 404

    def test_without_manage_deployment_it_is_not_there(self, deployment):
        _sync(deployment)
        recipe_id = self._propose(deployment)
        client = _client(deployment)
        client.app.state.user_directory.create_user("agent", "correct-pw", "us-west", "customer_service")
        _login(client, "agent", "correct-pw")

        assert client.get("/api/me/visible-schema").json()["SupportTicket"]["fields"]["topic"][
            "readable"] is True, "the role must be able to read the field, or this proves nothing"
        assert client.get("/api/enrichment-recipes").json()["recipes"] == []
        assert client.post(f"/api/enrichment-recipes/{recipe_id}/decide", json={"approve": True},
                           headers=_csrf(client)).status_code == 404

    def test_approving_is_audited_and_happens_once(self, deployment):
        from tests.conftest import read_audit_log

        _sync(deployment)
        recipe_id = self._propose(deployment)
        client = _client(deployment)

        approved = client.post(f"/api/enrichment-recipes/{recipe_id}/decide", json={"approve": True},
                               headers=_csrf(client))
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        again = client.post(f"/api/enrichment-recipes/{recipe_id}/decide", json={"approve": False},
                            headers=_csrf(client))
        assert again.status_code == 409
        [entry] = [e for e in read_audit_log(deployment.log_dir) if e.get("stage") == "enrichment_decision"]
        assert (entry["recipe_id"], entry["decision"], entry["field"]) == (recipe_id, "approved", "topic")

    def test_rules_for_a_question_nobody_asks_any_more_cannot_be_approved(self, deployment):
        _sync(deployment)
        recipe_id = self._propose(deployment, digest="an-older-question")
        client = _client(deployment)

        [recipe] = client.get("/api/enrichment-recipes").json()["recipes"]
        assert recipe["current"] is False
        assert client.get("/api/me/inbox").json()["enrichment"] == 0
        refused = client.post(f"/api/enrichment-recipes/{recipe_id}/decide", json={"approve": True},
                              headers=_csrf(client))
        assert refused.status_code == 409
        assert "question has changed" in refused.json()["detail"]


def _csrf(client):
    from tests.integration.test_api import _csrf_headers

    return _csrf_headers(client)
