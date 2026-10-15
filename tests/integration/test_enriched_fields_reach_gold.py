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

    # Three tickets in the fixture: too few to write rules from after the
    # held-out half is set aside -- and the script says so, proposing nothing.
    assert script.main() == 1
    out = capsys.readouterr().out
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

    monkeypatch.setattr(script, "_gold_rows", lambda *a: _rows(16))
    monkeypatch.setattr("sys.argv", ["compile_enrichment", "SupportTicket.topic",
                                     "--sample", "16", "--candidates", "1"])
    model.rule_sets = [GOOD]
    assert script.main() == 0
    assert "PROPOSED as" in capsys.readouterr().out
    [recipe] = EnrichmentRecipeStore(deployment.data_dir / "enrichment_recipes.db").all()
    assert recipe.status == "proposed"
    assert recipe.evaluation["held_out"]["agreement"] == 1.0
    assert recipe.provenance["sample"] == 16
    _sync(deployment)
    assert set(_topics(_client(deployment)).values()) == {None}
