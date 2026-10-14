"""What people asked Elysium to remember about objects (E-14).

THE OWNER'S DESIGN, 14 Oct, in three answers:

  WHAT    a fact about ONE object, in a sentence -- "disputed two
          charges in March". Not a preference about a person.
  WRITTEN only when a person asks. Nothing is stored because the model
          judged it worth keeping, so the model cannot fill memory with
          its own guesses -- or with an instruction planted in the data
          it read, which is how agent memory gets poisoned.
  STALE   when any field it was written from has changed since. A stale
          memory is shown as stale and never given to the agent.

SO A MEMORY CARRIES ITS SOURCES: the fields of the object the writer
could read when they wrote it, each with a fingerprint of its value then.
Those are what make it stale, and -- core/memory/guard.py -- what decide
who may see it: anyone who may read the object AND every one of those
fields, since the sentence may say something derived from any of them.

FINGERPRINTS, NOT VALUES. The store never holds a copy of the data a
memory was derived from; a sha256 of each value is enough to notice it
changed, and a memories.db read by someone who should not see the fields
gives them nothing.

PLAIN ROWS, NO AUTHORISATION HERE. This module stores and finds; every
decision about who sees what is MemoryGuard's, one place, like reads are
the mediator's.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.sqlite_connection import connection_with_schema

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    text TEXT NOT NULL,
    -- {field: sha256 of its value when written}
    sources TEXT NOT NULL,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS memories_object ON memories (object_type, object_id);
"""

#: The longest a memory may be: a fact, not a document.
MAX_TEXT = 500


def fingerprint(value) -> str:
    """A value's fingerprint: equal values, equal prints, across a
    restart and across types that print the same (7 and Decimal("7")
    are one value to a reader)."""
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Memory:
    memory_id: str
    object_type: str
    object_id: str
    text: str
    sources: dict
    author: str
    created_at: str


class MemoryStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def add(self, object_type: str, object_id, text: str, sources: dict, author: str) -> Memory:
        text = " ".join(str(text).split())
        if not text:
            raise ValueError("A memory needs some text.")
        if len(text) > MAX_TEXT:
            raise ValueError(f"A memory is at most {MAX_TEXT} characters; this is {len(text)}.")
        memory = Memory(str(uuid.uuid4()), object_type, str(object_id), text, dict(sources),
                        author, datetime.now(UTC).isoformat())
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO memories (memory_id, object_type, object_id, text, sources, author, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (memory.memory_id, object_type, memory.object_id, text,
                 json.dumps(memory.sources, sort_keys=True), author, memory.created_at))
            conn.commit()
        return memory

    def about(self, object_type: str, object_id) -> list[Memory]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE object_type = ? AND object_id = ? "
                "ORDER BY created_at", (object_type, str(object_id))).fetchall()
        return [self._memory(row) for row in rows]

    def get(self, memory_id: str) -> "Memory | None":
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM memories WHERE memory_id = ?",
                               (memory_id,)).fetchone()
        return self._memory(row) if row else None

    def remove(self, memory_id: str) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
            conn.commit()

    def forget_objects(self, keys) -> int:
        """Every memory about these (object type, object id) pairs, gone --
        what an erasure (R13) does to them. Returns how many."""
        removed = 0
        with self._connection() as conn:
            for object_type, object_id in keys:
                removed += conn.execute(
                    "DELETE FROM memories WHERE object_type = ? AND object_id = ?",
                    (object_type, str(object_id))).rowcount
            conn.commit()
        return removed

    def forget_erased(self, key_hash, hashes_by_type: dict[str, set[str]]) -> int:
        """Every memory about an object in an erasure register, gone (R13).

        Handed the register's hasher and hashes rather than the register,
        because core/mirror owns erasure and sits ABOVE this package. A
        scan, since the register holds only salted hashes and no id can
        be looked up from one; memories are few, written by hand.

        WHY BESIDE forget_objects: a restore brings back an older
        memories.db with the register that outlived it, and only hashes
        say which of the restored memories were about erased people.
        """
        if not hashes_by_type:
            return 0
        with self._connection() as conn:
            rows = conn.execute("SELECT memory_id, object_type, object_id FROM memories").fetchall()
            doomed = [(row["memory_id"],) for row in rows
                      if key_hash(row["object_type"], row["object_id"])
                      in hashes_by_type.get(row["object_type"], ())]
            conn.executemany("DELETE FROM memories WHERE memory_id = ?", doomed)
            conn.commit()
        return len(doomed)

    @staticmethod
    def _memory(row) -> Memory:
        return Memory(row["memory_id"], row["object_type"], row["object_id"], row["text"],
                      json.loads(row["sources"]), row["author"], row["created_at"])
