"""Search by meaning, for everyone who asks (R45, 18 October).

ONE PLACE FOR THE RULES. Browse's routes and the Query agent both rank
records by meaning, and the rules must not differ between them: who may
use it (someone who may READ the type and every field its text is made
from), which records survive (only those this person may read, none
deleted), what is compared (vectors of one model version only), and
what is said when it cannot answer. They lived in the routes for a day;
the agent's step is the second caller, so they live here now, and each
caller only words the answer.

ONE PER CONFIGURATION, built with the generation (core/deployment_loader):
the embedder follows config.yaml. The vector store underneath is one per
data directory (core/embeddings.store_at), so a reload does not throw
away the matrix every search reads.
"""

import logging
import threading
import time
from dataclasses import dataclass, field

from core.embeddings import MAX_K, EmbeddingStore, nearest, unit
from core.llm.interface import LLMUnavailable
from core.ontology.semantic_search import semantic_search_of

logger = logging.getLogger(__name__)

#: How long a model's version is trusted before it is asked again: a
#: re-pulled model is noticed within this, and a question does not pay
#: for a second request to the model server every time.
VERSION_SECONDS = 300.0

NOT_OFFERED = "Search by meaning is not offered for this type."
NOT_EMBEDDED = "Nothing has been embedded for this type yet; the next sync does it."
MODEL_DOWN = "The embedding model did not answer; word search still works."
RECORD_NOT_EMBEDDED = "This record has not been embedded yet; the next sync does it."


@dataclass
class Ranked:
    """A ranking, or why there is none. `offered` False means this
    person could never rank this type by meaning -- the same answer for
    a type that does not declare it, one they may not use it on, and one
    that does not exist."""
    available: bool
    offered: bool = True
    reason: "str | None" = None
    ids: list = field(default_factory=list)
    text_fields: list = field(default_factory=list)


class MeaningSearch:
    def __init__(self, store: EmbeddingStore, embedder, schema: dict):
        self.store = store
        self.embedder = embedder
        self.schema = schema
        self._version: str | None = None
        self._version_at = 0.0
        self._lock = threading.Lock()

    def version(self) -> str:
        with self._lock:
            now = time.monotonic()
            if self._version is None or now - self._version_at > VERSION_SECONDS:
                self._version, self._version_at = self.embedder.version(), now
            return self._version

    def text_fields(self, object_type: str) -> list:
        search = semantic_search_of(self.schema.get(object_type) or {})
        return list(search.inputs) if search else []

    def _matrix(self, mediator, user_record, object_type: str):
        """(matrix, None), or (None, Ranked saying why not)."""
        if self.embedder is None or not mediator.may_search_by_meaning(user_record, object_type):
            return None, Ranked(False, offered=False, reason=NOT_OFFERED)
        matrix = self.store.matrix(object_type, self.version())
        if matrix is None:
            return None, Ranked(False, reason=NOT_EMBEDDED)
        return matrix, None

    def related(self, mediator, user_record, object_type: str, text: str, k: int,
                context=None, exclude: "set[str] | None" = None) -> Ranked:
        """The records nearest in meaning to `text`, nearest first."""
        matrix, refusal = self._matrix(mediator, user_record, object_type)
        if refusal is not None:
            return refusal
        try:
            query = unit(self.embedder.embed_query(text.strip(), timeout=20))
        except (LLMUnavailable, ValueError, IndexError) as e:
            logger.warning("search by meaning on %s: %s", object_type, e)
            return Ranked(False, reason=MODEL_DOWN)
        skip = exclude or set()
        ranked = [object_id for object_id in nearest(matrix, query) if object_id not in skip]
        return self._kept(mediator, user_record, object_type, ranked, k, context)

    def similar(self, mediator, user_record, object_type: str, object_id: str, k: int,
                context=None) -> Ranked:
        """The records nearest in meaning to one record. Its own vector is
        the question, so no model is called. A record this person cannot
        read has none -- the answer a type without the feature gives."""
        matrix, refusal = self._matrix(mediator, user_record, object_type)
        if refusal is not None:
            return refusal
        if not mediator.readable_in_order(user_record, object_type, [object_id], 1,
                                          context=context):
            return Ranked(False, offered=False, reason=NOT_OFFERED)
        try:
            position = matrix.ids.index(str(object_id))
        except ValueError:
            return Ranked(False, reason=RECORD_NOT_EMBEDDED)
        ranked = nearest(matrix, matrix.vectors[position], exclude=str(object_id))
        return self._kept(mediator, user_record, object_type, ranked, k, context)

    def _kept(self, mediator, user_record, object_type, ranked, k, context) -> Ranked:
        kept = mediator.readable_in_order(user_record, object_type, ranked,
                                          max(1, min(k, MAX_K)), context=context)
        return Ranked(True, ids=kept, text_fields=self.text_fields(object_type))
