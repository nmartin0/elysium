"""
config_history.py  (what each configuration generation actually contained)

WHY THIS EXISTS. A generation records WHICH load it was, WHEN it
happened, and THAT the files differed (its source_digest). It does not
record WHAT THEY SAID. So after a reload, three questions had no answer
at all:

  - what did generation 7 contain?
  - what changed between 7 and 8?
  - put it back.

Before configuration could be reloaded this was tolerable: changing it
meant restarting, and a person was standing there. A SIGHUP at three in
the morning now changes the running system and leaves an audit line
saying 7 became 8, with no way to see what that WAS.

NOT SOLVED BY GIT, and assuming otherwise was a real error in the
reasoning behind HOT_RELOAD_PLAN.md. This project's own configuration
happens to live in a repository; a DEPLOYED Elysium has
/etc/elysium on an operator's machine and no relationship to any
repository. "Configuration is files, therefore versionable" is true.
"Therefore versioned" does not follow, and Elysium supplied nothing.

NOT SOLVED BY ICEBERG EITHER, which is the right tool for versioning
DATA and the wrong one for four small YAML documents. A SQLite table
beside write_log.db and artifacts.db is the proportionate mechanism and
matches how every other internal store here works.

STORES CONTENT, NOT DIFFS. A diff is derivable from two contents; a
content is not derivable from diffs unless every one since the
beginning survives. Configuration files are kilobytes, and a store that
cannot answer "what did 7 contain" without replaying history is the
same fragility this exists to remove.

WHAT IT DELIBERATELY DOES NOT DO: apply anything. Reverting is a
question of writing files back and reloading, which belongs to whoever
owns the filesystem, not to a history table. This answers "what was
it"; acting on the answer stays where the permissions are.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.sqlite_connection import connection_with_schema, immediate_transaction

SCHEMA = """
CREATE TABLE IF NOT EXISTS config_generations (
    generation    INTEGER PRIMARY KEY,
    loaded_at     TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    files         TEXT NOT NULL,
    recorded_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS config_generations_by_digest
    ON config_generations (source_digest);
"""


@dataclass(frozen=True)
class RecordedGeneration:
    """One configuration load, as it was on disk."""

    generation: int
    loaded_at: str
    source_digest: str
    # filename -> the file's text, exactly as read. Raw text rather
    # than parsed structures, for the same reason source_digest is over
    # raw bytes: the question is what was READ, and a reparsed dict
    # loses comments, ordering and anything YAML normalised away -- all
    # of which an operator comparing two generations wants to see.
    files: dict[str, str]
    recorded_at: str


class ConfigHistory:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def record(self, generation: int, loaded_at: str, source_digest: str,
               files: dict[str, str]) -> None:
        """Records a generation, ignoring a repeat of one already stored.

        IGNORING rather than replacing or raising. A generation number
        is assigned once per load and never reused, so a second record
        of the same number can only be the same load being recorded
        twice -- which happens if a caller retries. Replacing would
        rewrite history on a retry; raising would turn a harmless
        retry into a failed startup.
        """
        with self._connection() as conn, immediate_transaction(conn):
            conn.execute(
                "INSERT OR IGNORE INTO config_generations "
                "(generation, loaded_at, source_digest, files, recorded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (generation, loaded_at, source_digest, json.dumps(files),
                 datetime.now(UTC).isoformat()),
            )

    def get(self, generation: int) -> RecordedGeneration | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT generation, loaded_at, source_digest, files, recorded_at "
                "FROM config_generations WHERE generation = ?",
                (generation,),
            ).fetchone()
        return self._to_record(row) if row is not None else None

    def list_generations(self, limit: int = 50) -> list[RecordedGeneration]:
        """Most recent first.

        Bounded by default because this is read by an operator
        answering "what happened recently", and a deployment reloaded
        on a timer could accumulate thousands.
        """
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT generation, loaded_at, source_digest, files, recorded_at "
                "FROM config_generations ORDER BY generation DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def diff(self, older: int, newer: int) -> dict[str, tuple[str, str]]:
        """{filename: (before, after)} for every file that differs.

        A file present in one generation and absent from the other
        appears with "" on the missing side rather than being skipped:
        a configuration file APPEARING is a change, and one
        DISAPPEARING is a bigger one.

        Raises if either generation is unknown, rather than returning
        an empty diff. "No differences" and "I have never heard of
        generation 4" are different answers, and returning the first
        for the second is how an operator concludes nothing changed.
        """
        before = self.get(older)
        after = self.get(newer)
        missing = [n for n, r in ((older, before), (newer, after)) if r is None]
        if missing:
            raise ValueError(f"No recorded configuration for generation(s) {missing}")

        assert before is not None and after is not None
        changed = {}
        for name in sorted(set(before.files) | set(after.files)):
            old_text = before.files.get(name, "")
            new_text = after.files.get(name, "")
            if old_text != new_text:
                changed[name] = (old_text, new_text)
        return changed

    @staticmethod
    def _to_record(row: sqlite3.Row) -> RecordedGeneration:
        return RecordedGeneration(
            generation=row["generation"],
            loaded_at=row["loaded_at"],
            source_digest=row["source_digest"],
            files=json.loads(row["files"]),
            recorded_at=row["recorded_at"],
        )


def record_generation(history: "ConfigHistory", generation) -> None:
    """Records what this generation contained, never failing the caller.

    A history table that cannot be written is a degraded deployment,
    not a broken one: reads and writes work, and only the ability to
    answer "what did generation 7 contain" is lost. Refusing to start
    or refusing to reload over it would trade a working system for a
    bookkeeping problem.

    The opposite of the audit log's posture, deliberately. An access
    that cannot be recorded must not happen; a configuration whose text
    cannot be archived has already been loaded and validated.
    """
    try:
        history.record(
            generation.generation,
            generation.loaded_at.isoformat(),
            generation.source_digest,
            dict(generation.config.source_text),
        )
    except Exception as e:
        logging.getLogger(__name__).warning(f"could not record configuration generation {generation.generation}: {e}")
