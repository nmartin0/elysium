"""
embedding_adapter.py  (text to vectors, through the request every server speaks)

THE ONE GENERIC REQUEST (18 October). OpenAI's embeddings request --
POST /v1/embeddings {"model", "input": [texts], "dimensions"?}, answered
{"data": [{"index", "embedding"}]} -- is the one embedding servers have
converged on: Ollama documents it (input as a string or an array of
strings, and `dimensions`), and so do vLLM, llama.cpp's server and
Hugging Face's text-embeddings-inference. Speaking it, Elysium embeds
with any of them by changing a URL. This replaced an Ollama-only client
(its /api/embed) written a day earlier.

WHERE: `llm.embedding_connection.base_url` when the embedding server is
not the chat server -- a TEI container on its own port, say -- and
otherwise the chat server's own origin, taken from `llm.connection`.

TASK PREFIXES. Some models are trained to be told what a text is for:
nomic-embed-text's card says the text "must include a task instruction
prefix" -- `search_document: ` for what is stored, `search_query: ` for
what is asked. Without them it still answers, worse. Configured per
deployment (`llm.embedding_prefixes`), defaulted for the model families
known to need them, and part of the VERSION: vectors made with and
without them are not comparable.

VERSIONED. A vector is comparable only with vectors made the same way:
the same weights and the same prefixes. `version()` names both -- the
weights by the digest an Ollama server reports, when the server is
Ollama; otherwise by the model's name, which an operator re-pulling
different weights under one name must change.
"""

import hashlib
import logging
from typing import Any
from urllib.parse import urlsplit

import requests

from adapters import http_transport
from core.llm.interface import LLMUnavailable

logger = logging.getLogger(__name__)

#: Prefixes for model families whose cards require them. Matched on the
#: start of the configured model name; `llm.embedding_prefixes` wins.
KNOWN_PREFIXES = {
    "nomic-embed-text": {"document": "search_document: ", "query": "search_query: "},
}


def server_origin(url: str) -> str:
    """scheme://host:port of a URL -- the server, whatever path the chat
    endpoint was configured with ("/api/chat", "/v1/chat/completions")."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"{url!r} is not a URL with a scheme and a host")
    return f"{parts.scheme}://{parts.netloc}"


def prefixes_for(model: str, configured: "dict | None") -> dict:
    """{"document": ..., "query": ...} for this model: as configured, or
    as its family's card requires, or none."""
    if configured is not None:
        return {"document": str(configured.get("document") or ""),
                "query": str(configured.get("query") or "")}
    for family, known in KNOWN_PREFIXES.items():
        if model.startswith(family):
            return dict(known)
    return {"document": "", "query": ""}


class OpenAICompatibleEmbedder:
    def __init__(self, model: str, origin: str, *,
                 prefixes: "dict | None" = None, timeout_seconds: float = 180,
                 api_key: "str | None" = None):
        self.model = model
        self.origin = origin.rstrip("/")
        self.prefixes = prefixes_for(model, prefixes)
        self.timeout_seconds = timeout_seconds
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else None

    def embed_documents(self, texts: "list[str]", timeout: "float | None" = None) -> list:
        """Vectors for texts that are STORED and searched among."""
        return self._embed([self.prefixes["document"] + text for text in texts], timeout)

    def embed_query(self, text: str, timeout: "float | None" = None) -> list:
        """The vector for one text a person ASKS with."""
        return self._embed([self.prefixes["query"] + text], timeout)[0]

    def _embed(self, texts: "list[str]", timeout: "float | None") -> list:
        payload: dict[str, Any] = {"model": self.model, "input": list(texts)}
        url = f"{self.origin}/v1/embeddings"
        try:
            response = http_transport.post(url, json=payload, headers=self._headers,
                                           timeout=timeout or self.timeout_seconds)
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as e:
            raise LLMUnavailable(f"The embedding server at {url} could not be reached: "
                                 f"{type(e).__name__}") from e
        except ValueError as e:
            raise LLMUnavailable(f"The embedding server at {url} did not answer JSON") from e
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            detail = body.get("error") if isinstance(body, dict) else body
            raise LLMUnavailable(f"The embedding server at {url} answered without one vector "
                                 f"per text: {detail!r}")
        # IN THE ORDER ASKED: each entry says which input it is, and the
        # format does not promise the list is in that order.
        try:
            ordered = sorted(data, key=lambda entry: int(entry["index"]))
            vectors = [entry["embedding"] for entry in ordered]
        except (KeyError, TypeError, ValueError) as e:
            raise LLMUnavailable(f"The embedding server at {url} answered without one vector "
                                 f"per text") from e
        # EVERY INPUT EXACTLY ONCE: indexes 0..n-1, nothing missing,
        # nothing twice, and each vector non-empty.
        if [int(entry["index"]) for entry in ordered] != list(range(len(texts))) or not all(
                isinstance(vector, list) and vector for vector in vectors):
            raise LLMUnavailable(f"The embedding server at {url} answered without one vector "
                                 f"per text")
        return vectors

    def version(self) -> str:
        """What makes two vectors comparable: the weights and the
        prefixes."""
        weights = self._ollama_digest() or self.model
        prefixes = ""
        if self.prefixes["document"] or self.prefixes["query"]:
            prefixes = "/p" + hashlib.sha256(
                (self.prefixes["document"] + "\x00" + self.prefixes["query"]).encode()
            ).hexdigest()[:8]
        return f"{weights}{prefixes}"

    def _ollama_digest(self) -> "str | None":
        """The model's digest when the server is Ollama, which lists them
        at /api/tags; None from any other server."""
        try:
            response = requests.get(f"{self.origin}/api/tags", timeout=10)
            response.raise_for_status()
            models = response.json().get("models") or []
        except (requests.RequestException, ValueError, AttributeError):
            return None
        wanted = {self.model, f"{self.model}:latest"}
        for entry in models:
            if isinstance(entry, dict) and entry.get("name") in wanted and entry.get("digest"):
                return f"{self.model}@{entry['digest']}"
        return None
