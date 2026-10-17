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


class TestTheOllamaEmbedder:
    def _embedder(self, monkeypatch, reply, tags=None):
        from adapters import ollama_adapter

        sent = []

        class Response:
            def __init__(self, body):
                self.body = body

            def raise_for_status(self):
                pass

            def json(self):
                return self.body

        def post(url, json, timeout, **_):
            sent.append((url, json, timeout))
            return Response(reply)

        monkeypatch.setattr(ollama_adapter.http_transport, "post", post)
        monkeypatch.setattr(ollama_adapter.requests, "get", lambda url, timeout: Response(tags or {}))
        embedder = ollama_adapter.OllamaEmbedder(
            "nomic-embed-text", {"base_url": "http://localhost:11434/api/chat"})
        return embedder, sent

    def test_it_asks_the_embed_endpoint_beside_the_chat_one(self, monkeypatch):
        embedder, sent = self._embedder(monkeypatch, {"embeddings": [[1.0, 2.0], [3.0, 4.0]]})
        assert embedder.embed(["a", "b"]) == [[1.0, 2.0], [3.0, 4.0]]
        url, payload, _ = sent[0]
        assert url == "http://localhost:11434/api/embed"
        assert payload == {"model": "nomic-embed-text", "input": ["a", "b"]}

    @pytest.mark.parametrize("reply", [
        {"embeddings": [[1.0]]},                     # one vector for two texts
        {"error": "model 'nomic-embed-text' not found"},
        {"embeddings": [[1.0], []]},
    ])
    def test_a_reply_without_one_vector_per_text_is_unavailable(self, monkeypatch, reply):
        from core.llm.interface import LLMUnavailable

        embedder, _ = self._embedder(monkeypatch, reply)
        with pytest.raises(LLMUnavailable, match="one vector per text"):
            embedder.embed(["a", "b"])

    def test_its_version_is_the_models_digest_when_the_server_says(self, monkeypatch):
        tags = {"models": [{"name": "other:latest", "digest": "aaa"},
                           {"name": "nomic-embed-text:latest", "digest": "0a109f422b47"}]}
        embedder, _ = self._embedder(monkeypatch, {}, tags)
        assert embedder.version() == "nomic-embed-text@0a109f422b47"
        bare, _ = self._embedder(monkeypatch, {}, {"models": []})
        assert bare.version() == "nomic-embed-text"


def test_the_stand_in_is_what_the_tests_say_it_is():
    """The concept model's own behaviour, so a ranking test that passes
    is about the ranking and not about a model that happened to agree."""
    vectors = ConceptModel().embed(["refund", "reimburse", "login"])
    assert vectors[0] == vectors[1] != vectors[2]
    assert json.dumps(vectors)
