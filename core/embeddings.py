"""Embeddings: stored, versioned, refreshed by the sync, ranked (R45).

What a declaration means is core/ontology/semantic_search.py. This is
the machinery: where the vectors live, when they are made again, and
how a question is ranked against them.

WHERE: embeddings.db, one row per object -- the object's id, a hash of
the text it was made from, the model VERSION that made it, and the
vector, unit length, as float32. Beside the mirror rather than in it:
the vectors are derived from gold and remade from it, and nothing reads
them but the ranking below.

VERSIONED. A vector is comparable only with vectors the same weights
made, so every row carries its version (adapters/ollama_adapter: the
model's digest). A row whose text or version no longer matches is
REMOVED before anything is embedded, never kept as an approximation:
an old vector would rank a ticket by what it used to say.

REFRESHED BY THE SYNC, AFTER GOLD AND ERASURES (scripts/run_sync.py).
Only rows whose text changed are embedded again; rows gone from gold --
deleted, or erased under R13 -- are removed. WITHIN A TIME BUDGET: a
first pass over a large table on a CPU can take far longer than a sync
should, so the sync embeds what it can in `llm.embedding_budget_seconds`
and the next one carries on. A row not yet embedded is simply not
ranked. A model that cannot be reached costs the sync nothing: it says
so, and the rows wait.

RANKED EXACTLY. Cosine similarity of unit vectors is their dot product,
so ranking a question against a table is ONE matrix product -- numpy, in
milliseconds at tens of thousands of rows. Exact, not approximate: an
index (HNSW, say) is for when a table outgrows this, and measuring that
comes first. Foundry's own nearest-neighbour search returns at most a
few hundred; so does this.

NEVER SERVED. Nothing here returns a vector to a caller outside the
server, and no score reaches the screen: a cosine of 0.83 has no meaning
a person could act on, and differs by model.
"""

import hashlib
import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from core.sqlite_connection import connection_with_schema

logger = logging.getLogger(__name__)

#: The most text one row contributes. Embedding models read a few
#: thousand tokens at most; the gist of a record is at its start.
MAX_TEXT_CHARS = 2_000
#: Texts sent to the model in one call.
BATCH = 16
#: How many of the nearest rows are looked at, at most, to find the ones
#: a person may see. Bounded so a person who may see few rows of a large
#: table costs a bounded read, not the table.
MAX_SCAN = 2_000
#: The most results one ranking returns (Foundry's KNN: 1 to 100 in
#: Workshop, up to 500 in its v2 functions).
MAX_K = 100

SCHEMA = """
CREATE TABLE IF NOT EXISTS vectors (
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    -- sha256 of the text embedded: what the vector is a vector OF.
    text_hash TEXT NOT NULL,
    -- the model and weights that made it; vectors of two versions are
    -- never compared.
    version TEXT NOT NULL,
    dims INTEGER NOT NULL,
    -- unit length, float32, little-endian.
    vector BLOB NOT NULL,
    embedded_at REAL NOT NULL,
    PRIMARY KEY (object_type, object_id)
);
-- Bumped by every write to a type, so a reader knows its cached matrix
-- is stale without reading every vector again.
CREATE TABLE IF NOT EXISTS generations (
    object_type TEXT PRIMARY KEY,
    generation INTEGER NOT NULL
);
"""


def text_of(row, inputs: Iterable[str]) -> str:
    """The text a row is embedded from: its inputs' values, one per
    line, clipped. Empty when none of them says anything."""
    parts = [" ".join(str(value).split()) for name in inputs
             if (value := row.get(name)) is not None and str(value).strip()]
    return "\n".join(parts)[:MAX_TEXT_CHARS]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unit(vector) -> np.ndarray:
    """A vector as float32 of length one, or ValueError for a vector
    that is empty, not finite or all zeros -- none of which has a
    direction to compare."""
    array = np.asarray(vector, dtype=np.float32)
    if array.ndim != 1 or not array.size or not np.all(np.isfinite(array)):
        raise ValueError("not a vector")
    norm = float(np.linalg.norm(array))
    if norm == 0.0:
        raise ValueError("a zero vector has no direction")
    return array / norm


@dataclass
class Matrix:
    """One type's vectors of one version, ready to rank against."""
    version: str
    ids: list[str]
    vectors: np.ndarray        # rows are unit vectors, float32


@dataclass
class RefreshReport:
    embedded: int = 0
    reused: int = 0
    removed: int = 0
    #: Rows still to embed when the budget or the model ran out.
    waiting: int = 0
    #: Why it stopped early, if it did.
    stopped: "str | None" = None
    notes: list[str] = field(default_factory=list)


class EmbeddingStore:
    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._cache: dict[str, tuple[int, Matrix]] = {}
        self._lock = threading.Lock()

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def fingerprints(self, object_type: str) -> dict[str, tuple[str, str]]:
        """{object id: (text hash, version)} for every stored vector."""
        with self._connection() as conn:
            rows = conn.execute("SELECT object_id, text_hash, version FROM vectors "
                                "WHERE object_type = ?", (object_type,)).fetchall()
        return {row[0]: (row[1], row[2]) for row in rows}

    def remove(self, object_type: str, object_ids: Iterable[str]) -> int:
        ids = list(object_ids)
        if not ids:
            return 0
        with self._connection() as conn:
            conn.executemany("DELETE FROM vectors WHERE object_type = ? AND object_id = ?",
                             [(object_type, object_id) for object_id in ids])
            self._bump(conn, object_type)
            conn.commit()
        return len(ids)

    def remove_type(self, object_type: str) -> int:
        """Every vector of a type -- one no longer declared."""
        with self._connection() as conn:
            removed = conn.execute("DELETE FROM vectors WHERE object_type = ?",
                                   (object_type,)).rowcount
            self._bump(conn, object_type)
            conn.commit()
        return removed

    def declared_types(self) -> set[str]:
        with self._connection() as conn:
            return {row[0] for row in conn.execute("SELECT DISTINCT object_type FROM vectors")}

    def put(self, object_type: str, version: str,
            entries: "list[tuple[str, str, np.ndarray]]", now: "float | None" = None) -> None:
        """Stores (object id, text hash, unit vector) rows of one version."""
        if not entries:
            return
        stamp = time.time() if now is None else now
        with self._connection() as conn:
            conn.executemany(
                "INSERT INTO vectors (object_type, object_id, text_hash, version, dims, vector, "
                "embedded_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (object_type, object_id) "
                "DO UPDATE SET text_hash = excluded.text_hash, version = excluded.version, "
                "dims = excluded.dims, vector = excluded.vector, embedded_at = excluded.embedded_at",
                [(object_type, object_id, digest, version, int(vector.size),
                  vector.astype("<f4").tobytes(), stamp)
                 for object_id, digest, vector in entries])
            self._bump(conn, object_type)
            conn.commit()

    @staticmethod
    def _bump(conn: sqlite3.Connection, object_type: str) -> None:
        conn.execute("INSERT INTO generations (object_type, generation) VALUES (?, 1) "
                     "ON CONFLICT (object_type) DO UPDATE SET generation = generation + 1",
                     (object_type,))

    def _generation(self, object_type: str) -> int:
        with self._connection() as conn:
            row = conn.execute("SELECT generation FROM generations WHERE object_type = ?",
                               (object_type,)).fetchone()
        return 0 if row is None else int(row[0])

    def matrix(self, object_type: str, version: str) -> "Matrix | None":
        """The type's vectors of `version`, cached until the next write.
        None when there are none -- nothing embedded yet, or only by
        another version, which is never compared."""
        generation = self._generation(object_type)
        key = f"{object_type}\x00{version}"
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached[0] == generation:
                return cached[1]
        with self._connection() as conn:
            rows = conn.execute("SELECT object_id, dims, vector FROM vectors "
                                "WHERE object_type = ? AND version = ? ORDER BY object_id",
                                (object_type, version)).fetchall()
        if not rows:
            return None
        dims = rows[0][1]
        kept = [(row[0], row[2]) for row in rows if row[1] == dims]
        vectors = np.frombuffer(b"".join(blob for _, blob in kept), dtype="<f4").reshape(
            len(kept), dims)
        built = Matrix(version, [object_id for object_id, _ in kept], vectors)
        with self._lock:
            self._cache[key] = (generation, built)
        return built


def refresh(store: EmbeddingStore, embed: Callable[[list[str]], list], version: str,
            object_type: str, rows: "Iterable[tuple[object, str]]", budget_seconds: float,
            clock: Callable[[], float] = time.monotonic) -> RefreshReport:
    """Brings one type's vectors up to date with its gold rows.

    `rows` are (object id, text) for every row gold holds now; `embed`
    takes texts and returns vectors in order, raising for a model that
    cannot be reached. Stale and orphaned vectors go first, so whatever
    happens after, nothing ranks by text a row no longer has."""
    report = RefreshReport()
    started = clock()
    current = {str(object_id): text for object_id, text in rows}
    stored = store.fingerprints(object_type)

    wanted: dict[str, tuple[str, str]] = {}
    for object_id, text in current.items():
        # NOTHING TO SAY HAS NO MEANING to rank by: blank text is no row.
        if text and text.strip():
            wanted[object_id] = (text, text_hash(text))
    stale = [object_id for object_id, (digest, made_by) in stored.items()
             if object_id not in wanted or wanted[object_id][1] != digest or made_by != version]
    report.removed = store.remove(object_type, stale)
    kept = set(stored) - set(stale)
    report.reused = len(kept)

    to_embed = [(object_id, text, digest) for object_id, (text, digest) in wanted.items()
                if object_id not in kept]
    dims: int | None = None
    for start in range(0, len(to_embed), BATCH):
        if clock() - started >= budget_seconds:
            report.stopped = f"the {budget_seconds:g}-second budget ran out"
            break
        batch = to_embed[start:start + BATCH]
        try:
            vectors = embed([text for _, text, _ in batch])
        except Exception as e:  # noqa: BLE001 - a model that is down costs the sync nothing
            report.stopped = f"the embedding model did not answer ({type(e).__name__}: {e})"
            break
        entries = []
        for (object_id, _, digest), vector in zip(batch, vectors, strict=True):
            try:
                made = unit(vector)
            except ValueError:
                report.notes.append(f"{object_id}: the model returned no usable vector")
                continue
            if dims is None:
                dims = int(made.size)
            elif made.size != dims:
                report.stopped = "the model returned vectors of different lengths"
                break
            entries.append((object_id, digest, made))
        store.put(object_type, version, entries)
        report.embedded += len(entries)
        if report.stopped:
            break
    report.waiting = len(to_embed) - report.embedded - len(report.notes)
    return report


def nearest(matrix: Matrix, query: np.ndarray, exclude: "str | None" = None,
            limit: int = MAX_SCAN) -> list[str]:
    """Object ids, nearest first, at most `limit` -- for the caller to
    keep the ones a person may see. `query` is a unit vector of the
    matrix's version."""
    if query.size != matrix.vectors.shape[1]:
        return []
    scores = matrix.vectors @ query
    count = min(limit + (1 if exclude is not None else 0), len(scores))
    if count <= 0:
        return []
    # argpartition finds the top `count` without sorting the rest;
    # only those are sorted. Ties go to the smaller id, so a ranking is
    # the same every time it is asked.
    top = np.argpartition(-scores, count - 1)[:count] if count < len(scores) else np.arange(len(scores))
    ordered = sorted(top.tolist(), key=lambda index: (-float(scores[index]), matrix.ids[index]))
    return [matrix.ids[index] for index in ordered if matrix.ids[index] != exclude][:limit]
