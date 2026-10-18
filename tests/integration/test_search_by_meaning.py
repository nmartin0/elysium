"""Search by meaning, end to end (R45): declared, embedded by the sync,
ranked under a search and on an object -- and never past what a person
may read. Against a stand-in model whose meaning is a few concepts."""

import contextlib
import io
import shutil

import pytest
import yaml
from fastapi.testclient import TestClient

import tests.integration.conftest as integration_conftest
from tests.integration.test_api import _login  # noqa: F401

CONCEPTS = {"refund": 0, "money": 0, "reimburse": 0,
            "billing": 1, "address": 1, "invoice": 1,
            "login": 2, "password": 2, "sign": 2}

REFUND = "Requesting a refund for hardware order"
LOGIN = "Login page returns a 500 error"
BILLING = "Cannot update billing address"


class ConceptModel:
    def __init__(self):
        self.fail = False
        self.calls = 0

    def version(self):
        return "concepts@1"

    def embed(self, texts, timeout=None):
        from core.llm.interface import LLMUnavailable

        if self.fail:
            raise LLMUnavailable("the model is down")
        self.calls += 1
        vectors = []
        for text in texts:
            vector = [0.0, 0.0, 0.0, 0.05]
            for word in text.lower().split():
                if word in CONCEPTS:
                    vector[CONCEPTS[word]] += 1.0
            vectors.append(vector)
        return vectors

    # The two sides of the embedder (adapters/embedding_adapter.py).
    def embed_documents(self, texts, timeout=None):
        return self.embed(texts, timeout)

    def embed_query(self, text, timeout=None):
        return self.embed([text], timeout)[0]


@pytest.fixture
def model(monkeypatch):
    import core.deployment_loader

    stand_in = ConceptModel()
    monkeypatch.setattr(core.deployment_loader, "build_embedder", lambda config: stand_in)
    return stand_in


@pytest.fixture
def deployment(tmp_path, monkeypatch, model):
    from core.deployment_loader import RuntimePaths

    monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")
    config = tmp_path / "config"
    shutil.copytree(integration_conftest.FIXTURES_DIR, config)
    ontology = yaml.safe_load((config / "ontology_schema.yaml").read_text())
    ontology["object_types"]["SupportTicket"]["semantic_search"] = {"from": ["subject"]}
    (config / "ontology_schema.yaml").write_text(yaml.safe_dump(ontology))
    settings = yaml.safe_load((config / "config.yaml").read_text())
    settings["llm"]["embedding_model"] = "concepts"
    # THE AGENT'S STEP TOO (18 October), through the same service.
    settings["agent"]["meaning_search"] = True
    (config / "config.yaml").write_text(yaml.safe_dump(settings))
    policy = yaml.safe_load((config / "policy.yaml").read_text())
    # MAY READ TICKETS, BUT NOT THE TEXT THEY ARE EMBEDDED FROM.
    policy["roles"]["no_subject"] = {
        **{key: value for key, value in policy["roles"]["debug"].items()
           if key != "allowed_actions"},
        "allowed_actions": ["read:SupportTicket", "read:SupportTicket.ticket_id",
                            "read:SupportTicket.status"]}
    # MAY KNOW `subject` EXISTS -- discover -- but not read it.
    policy["roles"]["discovers_subject"] = {
        **policy["roles"]["no_subject"],
        "allowed_actions": [*policy["roles"]["no_subject"]["allowed_actions"],
                            "discover:SupportTicket.subject"]}
    (config / "policy.yaml").write_text(yaml.safe_dump(policy))

    data = tmp_path / "data"
    fixtures = data / "dev_fixtures"
    fixtures.mkdir(parents=True)
    for sql, db in (("schema.sql", "mediator.db"), ("support_schema.sql", "support.db"),
                    ("risk_schema.sql", "risk.db")):
        integration_conftest._build_sqlite_db(integration_conftest.FIXTURES_DIR / sql, fixtures / db)
    (tmp_path / "log").mkdir()
    paths = RuntimePaths(config_dir=config, data_dir=data, log_dir=tmp_path / "log")
    from scripts.run_sync import run_sync

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        run_sync(paths)
    (tmp_path / "sync_output.txt").write_text(output.getvalue())
    return paths


def _client(paths, username="ops", role="debug"):
    from api.app import create_app

    client = TestClient(create_app(paths))
    with contextlib.suppress(ValueError):
        client.app.state.user_directory.create_user(username, "correct-pw", "us-west", role)
    _login(client, username, "correct-pw")
    return client


def _subjects(response) -> list:
    assert response.status_code == 200, response.text
    return [row["fields"]["subject"] for row in response.json()["results"]]


def test_the_sync_embeds_every_ticket_once(deployment, model):
    from core.embeddings import EmbeddingStore

    printed = (deployment.data_dir.parent / "sync_output.txt").read_text()
    assert "embeddings  SupportTicket: 3 embedded, 0 unchanged, 0 removed" in printed
    matrix = EmbeddingStore(deployment.data_dir / "embeddings.db").matrix("SupportTicket",
                                                                          "concepts@1")
    assert len(matrix.ids) == 3


def test_a_search_finds_by_meaning_what_its_words_did_not(deployment):
    client = _client(deployment)
    # "money back" is in no subject; the refund ticket means it.
    words = client.get("/api/objects/SupportTicket/search", params={"q": "money back"}).json()
    assert words["total_matches"] == 0
    related = client.get("/api/objects/SupportTicket/related-in-meaning", params={"q": "money back"})
    assert related.json()["available"] is True
    assert related.json()["text_fields"] == ["subject"], "what a result is best named by"
    subjects = _subjects(related)
    assert subjects[0] == REFUND
    # cust_003's ticket is in another region: never ranked for us-west,
    # however near it is.
    assert BILLING not in subjects


def test_a_word_match_is_not_repeated_as_a_meaning_match(deployment):
    client = _client(deployment)
    assert REFUND not in _subjects(client.get("/api/objects/SupportTicket/related-in-meaning",
                                              params={"q": "refund"}))


def test_similar_records_rank_by_the_objects_own_vector_without_calling_the_model(
        deployment, model):
    client = _client(deployment)
    ids = {row["fields"]["subject"]: row["id"] for row in client.get(
        "/api/objects/SupportTicket/search", params={"q": ""}).json()["results"]}
    calls = model.calls
    similar = client.get(f"/api/objects/SupportTicket/{ids[REFUND]}/similar")
    assert _subjects(similar) == [LOGIN], "itself left out; the other region's ticket never shown"
    assert model.calls == calls


def test_without_reading_the_text_there_is_no_search_by_meaning(deployment):
    """Someone refused `subject` must not be able to ask which tickets
    read like "refund" -- and is told exactly what an undeclared type
    tells anyone."""
    client = _client(deployment, "nosubject", "no_subject")
    refused = client.get("/api/objects/SupportTicket/related-in-meaning", params={"q": "refund"})
    undeclared = client.get("/api/objects/Customer/related-in-meaning", params={"q": "refund"})
    unknown = client.get("/api/objects/Nope/related-in-meaning", params={"q": "refund"})
    assert refused.json() == undeclared.json() == unknown.json() == {
        "available": False, "offered": False,
        "reason": "Search by meaning is not offered for this type.", "results": [],
        "text_fields": []}
    assert client.get("/api/objects/SupportTicket/1/similar").json()["available"] is False


def test_a_model_that_is_down_says_so_and_word_search_is_untouched(deployment, model):
    client = _client(deployment)
    model.fail = True
    related = client.get("/api/objects/SupportTicket/related-in-meaning", params={"q": "money"})
    assert related.json() == {"available": False, "offered": True, "results": [],
                              "text_fields": [],
                              "reason": "The embedding model did not answer; word search "
                                        "still works."}
    assert client.get("/api/objects/SupportTicket/search", params={"q": "refund"}).json()[
        "total_matches"] == 1


def test_no_vector_is_ever_served(deployment):
    client = _client(deployment)
    body = client.get("/api/objects/SupportTicket/related-in-meaning",
                      params={"q": "money back"}).text
    assert "vector" not in body and "score" not in body


def test_a_deleted_record_is_never_ranked(deployment, monkeypatch):
    client = _client(deployment)
    write_log = client.app.state.generation.mediator.write_log
    monkeypatch.setattr(write_log, "deleted_object_ids",
                        lambda object_type: {"1"} if object_type == "SupportTicket" else set())
    ids = {row["fields"]["subject"]: row["id"] for row in client.get(
        "/api/objects/SupportTicket/search", params={"q": ""}).json()["results"]}
    assert _subjects(client.get(f"/api/objects/SupportTicket/{ids[REFUND]}/similar")) == []


def test_a_record_in_another_region_has_no_similar_records_for_you(deployment):
    """Ticket 3 is cust_003's, outside us-west. Asking for its neighbours
    must read as asking about a type that does not offer this -- not
    reveal that it exists, or what it is near."""
    client = _client(deployment)
    assert client.get("/api/objects/SupportTicket/3/similar").json() == {
        "available": False, "offered": False,
        "reason": "Search by meaning is not offered for this type.", "results": [],
        "text_fields": []}


def test_a_failure_to_embed_never_fails_the_sync(deployment, monkeypatch):
    import core.deployment_loader
    from scripts.run_sync import run_sync

    def broken(config):
        raise RuntimeError("no embedder today")

    monkeypatch.setattr(core.deployment_loader, "build_embedder", broken)
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        run_sync(deployment)
    printed = output.getvalue()
    assert "WARNING embeddings not refreshed: no embedder today" in printed
    assert "finished: ok" in printed


def test_a_type_no_longer_declared_loses_its_vectors(deployment):
    from core.embeddings import EmbeddingStore
    from scripts.run_sync import run_sync

    schema_path = deployment.config_dir / "ontology_schema.yaml"
    ontology = yaml.safe_load(schema_path.read_text())
    del ontology["object_types"]["SupportTicket"]["semantic_search"]
    schema_path.write_text(yaml.safe_dump(ontology))
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        run_sync(deployment)
    assert "SupportTicket: no longer declared; 3 vector(s) removed" in output.getvalue()
    assert EmbeddingStore(deployment.data_dir / "embeddings.db").declared_types() == set()


def test_knowing_a_field_exists_is_not_reading_it(deployment):
    """A discover-only grant puts `subject` in the visible schema, marked
    unreadable. Ranking by its meaning would read it."""
    client = _client(deployment, "discoverer", "discovers_subject")
    fields = client.get("/api/me/visible-schema").json()["SupportTicket"]["fields"]
    assert fields["subject"]["readable"] is False, "the case this test is about"
    assert client.get("/api/objects/SupportTicket/related-in-meaning",
                      params={"q": "refund"}).json()["offered"] is False


def test_the_query_agent_ranks_by_meaning_through_the_same_rules(deployment):
    """The configured loop, its model scripted: a search_meaning step
    reaches the deployment's embedder and store, and keeps what Browse
    keeps -- the refund ticket first, never the other region's."""
    from core.intermediate_layer.auth import UserRecord
    from tests.conftest import scripted_llm_client

    client = _client(deployment)
    loop = client.app.state.generation.loop
    loop.client = scripted_llm_client([
        {"step": "search_meaning", "object_type": "SupportTicket", "text": "money back"},
        {"step": "finish"}])
    result = loop.run(UserRecord("ops", "us-west", "debug"), "tickets about getting money back?")
    [entry] = [item for item in result.gathered if item["step"] == "search_meaning"]
    subjects = {row["id"]: row["fields"]["subject"] for row in client.get(
        "/api/objects/SupportTicket/search", params={"q": ""}).json()["results"]}
    assert [subjects[str(found)] for found in entry["result"]][0] == REFUND
    assert BILLING not in [subjects.get(str(found)) for found in entry["result"]]


def test_the_visible_schema_says_which_types_rank_by_meaning(deployment):
    reader = _client(deployment).get("/api/me/visible-schema").json()
    assert reader["SupportTicket"]["searchable_by_meaning"] is True
    assert reader["Customer"]["searchable_by_meaning"] is False
    discoverer = _client(deployment, "discoverer", "discovers_subject").get(
        "/api/me/visible-schema").json()
    assert discoverer["SupportTicket"]["searchable_by_meaning"] is False


def test_the_agent_step_without_an_embedding_model_is_refused_at_load(deployment):
    from core.deployment_loader import build_generation

    settings_path = deployment.config_dir / "config.yaml"
    settings = yaml.safe_load(settings_path.read_text())
    del settings["llm"]["embedding_model"]
    ontology_path = deployment.config_dir / "ontology_schema.yaml"
    ontology = yaml.safe_load(ontology_path.read_text())
    del ontology["object_types"]["SupportTicket"]["semantic_search"]
    settings_path.write_text(yaml.safe_dump(settings))
    ontology_path.write_text(yaml.safe_dump(ontology))
    with pytest.raises(ValueError, match="agent.meaning_search needs llm.embedding_model"):
        build_generation(deployment.config_dir, deployment.data_dir, deployment.log_dir)
