"""Embeddings (R45): the declaration, the store, refreshing it from
gold, the ranking, and the Ollama embedder -- against a stand-in model
whose "meaning" is a handful of concepts, so nearness is predictable."""

import json

import numpy as np
import pytest

from core.embeddings import MAX_TEXT_CHARS, EmbeddingStore, nearest, refresh, text_of, unit
from core.ontology.semantic_search import semantic_search_of, validate_semantic_search

#: Words that mean the same thing share a dimension -- the property an
#: embedding model has, reduced to a dictionary.
CONCEPTS = {"refund": 0, "money": 0, "reimburse": 0,
            "twice": 1, "duplicate": 1, "double": 1,
            "login": 2, "password": 2, "sign": 2}


class ConceptModel:
    """Embeds by counting concept words; a constant fourth dimension
    keeps every vector non-zero. Records every batch it was given."""

    def __init__(self, fail=False):
        self.batches = []
        self.fail = fail

    def embed(self, texts, timeout=None):
        if self.fail:
            raise ConnectionError("model is down")
        self.batches.append(list(texts))
        vectors = []
        for text in texts:
            vector = [0.0, 0.0, 0.0, 0.1]
            for word in text.lower().replace(",", " ").split():
                if word in CONCEPTS:
                    vector[CONCEPTS[word]] += 1.0
            vectors.append(vector)
        return vectors


ROWS = [(1, "Please refund my order"), (2, "I was charged twice"),
        (3, "Cannot login to my account"), (4, "Money back for a duplicate charge")]


@pytest.fixture
def store(tmp_path):
    return EmbeddingStore(tmp_path / "embeddings.db")


class TestRefreshing:
    def test_new_rows_are_embedded_and_unchanged_ones_are_not_asked_again(self, store):
        model = ConceptModel()
        report = refresh(store, model.embed, "v1", "Ticket", ROWS, budget_seconds=60)
        assert (report.embedded, report.reused, report.removed, report.waiting) == (4, 0, 0, 0)
        model.batches.clear()
        again = refresh(store, model.embed, "v1", "Ticket", ROWS, budget_seconds=60)
        assert (again.embedded, again.reused) == (0, 4)
        assert model.batches == []

    def test_a_row_whose_text_changed_loses_its_old_vector_first(self, store):
        refresh(store, ConceptModel().embed, "v1", "Ticket", ROWS, budget_seconds=60)
        changed = [(1, "Cannot sign in"), *ROWS[1:]]
        # THE MODEL IS DOWN, so nothing new is embedded -- and still the
        # stale vector must go: ranking ticket 1 as a refund would be a
        # lie about what it says now.
        report = refresh(store, ConceptModel(fail=True).embed, "v1", "Ticket", changed,
                         budget_seconds=60)
        assert report.removed == 1 and report.waiting == 1
        assert "did not answer" in report.stopped
        assert "1" not in store.matrix("Ticket", "v1").ids

    def test_rows_gone_from_gold_and_rows_with_no_text_are_removed(self, store):
        refresh(store, ConceptModel().embed, "v1", "Ticket", ROWS, budget_seconds=60)
        report = refresh(store, ConceptModel().embed, "v1", "Ticket",
                         [ROWS[0], (2, "   "), ROWS[2]], budget_seconds=60)
        assert report.removed == 2
        assert sorted(store.matrix("Ticket", "v1").ids) == ["1", "3"]

    def test_a_new_model_version_embeds_everything_again(self, store):
        refresh(store, ConceptModel().embed, "v1", "Ticket", ROWS, budget_seconds=60)
        report = refresh(store, ConceptModel().embed, "v2", "Ticket", ROWS, budget_seconds=60)
        assert (report.removed, report.embedded) == (4, 4)
        assert store.matrix("Ticket", "v1") is None, "two versions are never compared"

    def test_the_budget_stops_it_and_the_next_run_carries_on(self, store):
        ticks = iter([0.0, 0.0, 999.0, 999.0, 999.0])
        rows = [(n, f"refund {n}") for n in range(40)]
        report = refresh(store, ConceptModel().embed, "v1", "Ticket", rows, budget_seconds=60,
                         clock=lambda: next(ticks))
        assert report.embedded == 16 and report.waiting == 24
        assert "budget" in report.stopped
        rest = refresh(store, ConceptModel().embed, "v1", "Ticket", rows, budget_seconds=60)
        assert (rest.reused, rest.embedded, rest.waiting) == (16, 24, 0)

    def test_a_model_that_changes_its_vector_length_is_stopped(self, store):
        class Wobbly(ConceptModel):
            def embed(self, texts, timeout=None):
                return [[1.0] * (2 + index) for index, _ in enumerate(texts)]

        report = refresh(store, Wobbly().embed, "v1", "Ticket", ROWS, budget_seconds=60)
        assert report.stopped == "the model returned vectors of different lengths"

    def test_the_text_is_the_inputs_values_clipped(self):
        assert text_of({"a": " Hello   there ", "b": None, "c": ""}, ["a", "b", "c"]) == "Hello there"
        assert len(text_of({"a": "x" * 5_000}, ["a"])) == MAX_TEXT_CHARS


class TestRanking:
    def test_rows_are_ranked_by_meaning_not_by_shared_words(self, store):
        model = ConceptModel()
        refresh(store, model.embed, "v1", "Ticket", ROWS, budget_seconds=60)
        matrix = store.matrix("Ticket", "v1")
        query = unit(model.embed(["reimburse me"])[0])
        # "reimburse" shares no word with either refund ticket.
        assert nearest(matrix, query)[:2] == ["1", "4"]

    def test_the_question_itself_is_left_out_and_ties_go_to_the_smaller_id(self, store):
        refresh(store, ConceptModel().embed, "v1", "Ticket",
                [(1, "login"), (2, "password"), (3, "sign"), (4, "refund")], budget_seconds=60)
        matrix = store.matrix("Ticket", "v1")
        position = matrix.ids.index("2")
        assert nearest(matrix, matrix.vectors[position], exclude="2") == ["1", "3", "4"]

    def test_a_question_of_another_length_ranks_nothing(self, store):
        refresh(store, ConceptModel().embed, "v1", "Ticket", ROWS, budget_seconds=60)
        assert nearest(store.matrix("Ticket", "v1"), unit([1.0, 0.0])) == []

    def test_the_matrix_is_read_again_after_a_write_and_not_before(self, store, monkeypatch):
        refresh(store, ConceptModel().embed, "v1", "Ticket", ROWS[:2], budget_seconds=60)
        first = store.matrix("Ticket", "v1")
        assert store.matrix("Ticket", "v1") is first, "cached until something is written"
        refresh(store, ConceptModel().embed, "v1", "Ticket", ROWS, budget_seconds=60)
        assert len(store.matrix("Ticket", "v1").ids) == 4

    def test_a_vector_with_no_direction_is_refused(self):
        for bad in ([], [0.0, 0.0], [float("nan"), 1.0]):
            with pytest.raises(ValueError):
                unit(bad)
        assert np.isclose(np.linalg.norm(unit([3.0, 4.0])), 1.0)


def _types(**search):
    return {"Ticket": {"id_field": "ticket_id", "semantic_search": search or {"from": ["subject"]},
                       "fields": {"ticket_id": {"type": "data", "data_type": "integer"},
                                  "subject": {"type": "data"},
                                  "body": {"type": "data", "data_type": "string"},
                                  "amount": {"type": "data", "data_type": "decimal"},
                                  "email": {"type": "data", "classification": ["pii"]},
                                  "customer": {"type": "link", "target": "Customer"},
                                  "total": {"derived": {"concat": ["subject", "body"]}}}}}


class TestTheDeclaration:
    def test_a_good_one_loads(self):
        types = _types(**{"from": ["subject", "body"]})
        validate_semantic_search(types, "nomic-embed-text")
        assert semantic_search_of(types["Ticket"]).inputs == ("subject", "body")

    @pytest.mark.parametrize("declared, model, why", [
        ({"from": ["email"]}, "m", "classified.*never sent to a model"),
        ({"from": ["amount"]}, "m", "meaning is read from text"),
        ({"from": ["customer"]}, "m", "is a link"),
        ({"from": ["total"]}, "m", "is computed"),
        ({"from": ["nope"]}, "m", "does not have"),
        ({"from": ["subject", "subject"]}, "m", "names a field twice"),
        ({"from": []}, "m", "1 to 8 fields"),
        ({"from": ["subject"], "k": 3}, "m", "is {from"),
        ({"from": ["subject"]}, None, "llm.embedding_model"),
    ])
    def test_one_that_could_not_be_embedded_safely_is_refused_at_load(self, declared, model, why):
        with pytest.raises(ValueError, match=why):
            validate_semantic_search(_types(**declared), model)


class TestTheEmbedder:
    """The one request every embedding server speaks (18 October)."""

    def _embedder(self, monkeypatch, reply, tags=None, model="nomic-embed-text", **options):
        from adapters import embedding_adapter

        sent = []

        class Response:
            def __init__(self, body, status=200):
                self.body = body
                self.status = status

            def raise_for_status(self):
                if self.status >= 400:
                    raise embedding_adapter.requests.HTTPError(str(self.status))

            def json(self):
                return self.body

        def post(url, json, timeout, headers=None, **_):
            sent.append((url, json, headers))
            return Response(reply)

        monkeypatch.setattr(embedding_adapter.http_transport, "post", post)
        monkeypatch.setattr(embedding_adapter.requests, "get",
                            lambda url, timeout: Response(tags or {}, 200 if tags else 404))
        embedder = embedding_adapter.OpenAICompatibleEmbedder(
            model, embedding_adapter.server_origin("http://localhost:11434/api/chat"), **options)
        return embedder, sent

    @staticmethod
    def _data(*vectors, order=None):
        indexes = order or list(range(len(vectors)))
        return {"data": [{"index": index, "embedding": vectors[index]} for index in indexes]}

    def test_it_asks_the_generic_endpoint_on_the_chat_servers_origin(self, monkeypatch):
        embedder, sent = self._embedder(monkeypatch, self._data([1.0, 2.0], [3.0, 4.0]),
                                        model="all-minilm")
        assert embedder.embed_documents(["a", "b"]) == [[1.0, 2.0], [3.0, 4.0]]
        url, payload, headers = sent[0]
        assert url == "http://localhost:11434/v1/embeddings"
        assert payload == {"model": "all-minilm", "input": ["a", "b"]}
        assert headers is None

    def test_vectors_come_back_in_the_order_asked_whatever_order_they_arrive(self, monkeypatch):
        embedder, _ = self._embedder(monkeypatch, self._data([1.0], [2.0], [3.0], order=[2, 0, 1]),
                                     model="all-minilm")
        assert embedder.embed_documents(["a", "b", "c"]) == [[1.0], [2.0], [3.0]]

    def test_a_model_that_needs_task_prefixes_gets_them(self, monkeypatch):
        """nomic-embed-text's card: the text "must include a task
        instruction prefix" -- one for what is stored, one for what is
        asked."""
        embedder, sent = self._embedder(monkeypatch, self._data([1.0]))
        embedder.embed_documents(["refund please"])
        embedder.embed_query("money back")
        assert sent[0][1]["input"] == ["search_document: refund please"]
        assert sent[1][1]["input"] == ["search_query: money back"]

    def test_configured_prefixes_win_and_empty_means_none(self, monkeypatch):
        embedder, sent = self._embedder(monkeypatch, self._data([1.0]),
                                        prefixes={"document": "", "query": ""})
        embedder.embed_query("x")
        assert sent[0][1]["input"] == ["x"]

    @pytest.mark.parametrize("reply", [
        {"data": [{"index": 0, "embedding": [1.0]}]},          # one vector for two texts
        {"error": {"message": "model not found"}},
        {"data": [{"index": 0, "embedding": [1.0]}, {"index": 0, "embedding": [2.0]}]},
        {"data": [{"index": 0, "embedding": [1.0]}, {"index": 1, "embedding": []}]},
    ])
    def test_a_reply_without_one_vector_per_text_is_unavailable(self, monkeypatch, reply):
        from core.llm.interface import LLMUnavailable

        embedder, _ = self._embedder(monkeypatch, reply)
        with pytest.raises(LLMUnavailable, match="one vector per text"):
            embedder.embed_documents(["a", "b"])

    def test_its_version_names_the_weights_and_the_prefixes(self, monkeypatch):
        tags = {"models": [{"name": "nomic-embed-text:latest", "digest": "0a109f422b47"}]}
        ollama, _ = self._embedder(monkeypatch, {}, tags)
        assert ollama.version().startswith("nomic-embed-text@0a109f422b47/p")
        unprefixed, _ = self._embedder(monkeypatch, {}, None, model="all-minilm")
        assert unprefixed.version() == "all-minilm", "another server: the name, no digest"
        other_prefixes, _ = self._embedder(monkeypatch, {}, tags, prefixes={"document": "d: ",
                                                                            "query": "q: "})
        assert other_prefixes.version() != ollama.version()

    def test_a_smaller_size_is_asked_for_and_held_to(self, monkeypatch):
        """Matryoshka (18 October): `dimensions` is sent, and a server
        answering another length is refused -- never cut down here, which
        is right only for a model trained for it."""
        from core.llm.interface import LLMUnavailable

        embedder, sent = self._embedder(monkeypatch, self._data([0.5] * 4), dimensions=4)
        assert embedder.embed_query("x") == [0.5] * 4
        assert sent[0][1]["dimensions"] == 4
        too_long, _ = self._embedder(monkeypatch, self._data([0.5] * 8), dimensions=4)
        with pytest.raises(LLMUnavailable, match="not the 4 asked for"):
            too_long.embed_query("x")

    def test_without_a_size_none_is_sent(self, monkeypatch):
        embedder, sent = self._embedder(monkeypatch, self._data([1.0]))
        embedder.embed_query("x")
        assert "dimensions" not in sent[0][1]

    def test_the_size_is_part_of_the_version(self, monkeypatch):
        full, _ = self._embedder(monkeypatch, {}, None, model="all-minilm")
        small, _ = self._embedder(monkeypatch, {}, None, model="all-minilm", dimensions=256)
        assert (full.version(), small.version()) == ("all-minilm", "all-minilm/256d")

    def test_a_key_is_sent_as_a_bearer_token(self, monkeypatch):
        embedder, sent = self._embedder(monkeypatch, self._data([1.0]), api_key="sekret")
        embedder.embed_query("x")
        assert sent[0][2] == {"Authorization": "Bearer sekret"}


def test_the_stand_in_is_what_the_tests_say_it_is():
    """The concept model's own behaviour, so a ranking test that passes
    is about the ranking and not about a model that happened to agree."""
    vectors = ConceptModel().embed(["refund", "reimburse", "login"])
    assert vectors[0] == vectors[1] != vectors[2]
    assert json.dumps(vectors)


class TestTheSettings:
    """`llm.embedding_*` in config.yaml, checked at load (18 October)."""

    def _config(self, provider="ollama", **overrides):
        from types import MappingProxyType, SimpleNamespace

        settings = {"embedding_model": "nomic-embed-text", "embedding_prefixes": None,
                    "embedding_dimensions": None,
                    "embedding_connection": MappingProxyType({}),
                    "llm_connection": MappingProxyType(
                        {"base_url": "http://ollama.internal:11434/api/chat"}),
                    "llm_provider": provider}
        settings.update(overrides)
        return SimpleNamespace(**settings)

    def test_any_provider_embeds_at_the_chat_servers_origin(self):
        from core.deployment_loader import build_embedder

        for provider in ("ollama", "vllm"):
            assert build_embedder(self._config(provider)).origin == "http://ollama.internal:11434"

    def test_the_configured_size_reaches_the_embedder(self):
        from core.deployment_loader import build_embedder

        assert build_embedder(self._config(embedding_dimensions=512)).dimensions == 512
        assert build_embedder(self._config(embedding_dimensions=None)).dimensions is None

    def test_a_separate_embedding_server_is_used_when_named(self):
        from types import MappingProxyType

        from core.deployment_loader import build_embedder

        embedder = build_embedder(self._config(embedding_connection=MappingProxyType(
            {"base_url": "http://tei:8080", "api_key": "k"})))
        assert embedder.origin == "http://tei:8080"

    def test_a_provider_with_no_server_is_told_to_name_one(self):
        from types import MappingProxyType

        from core.deployment_loader import build_embedder

        with pytest.raises(ValueError, match="embedding_connection.base_url"):
            build_embedder(self._config("claude_agent_sdk", llm_connection=MappingProxyType({})))

    @pytest.mark.parametrize("llm, why", [
        ({"embedding_model": "  "}, "name of an embedding model"),
        ({"embedding_budget_seconds": 0}, "seconds above 0"),
        ({"embedding_prefixes": {"doc": "x"}}, "document: <text>, query: <text>"),
        ({"embedding_prefixes": {"document": 3}}, "document: <text>, query: <text>"),
        ({"embedding_connection": {"base_url": "x", "password": "p"}}, "base_url, api_key"),
        ({"embedding_dimensions": 8}, "16 to 8192"),
        ({"embedding_dimensions": "512"}, "16 to 8192"),
        ({"embedding_dimensions": True}, "16 to 8192"),
    ])
    def test_a_bad_setting_is_refused_with_the_reason(self, llm, why):
        from core.deployment_loader import _embedding_settings

        with pytest.raises(ValueError, match=why):
            _embedding_settings(llm)

    def test_a_key_is_read_from_the_environment_by_reference(self, monkeypatch):
        from core.deployment_loader import _embedding_settings

        monkeypatch.setenv("EMBED_KEY", "from-env")
        settings = _embedding_settings({"embedding_model": "m",
                                        "embedding_connection": {"api_key": "${EMBED_KEY}"}})
        assert settings.connection["api_key"] == "from-env"
