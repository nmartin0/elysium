"""Which source tends to be right when two disagree: evidence only (R60).

THE QUESTION. Survivorship picks a value by a declared preference order
("billing wins"), and the losing value is kept in the conflicts table.
Whether that order is a GOOD one is something a deployment can only
judge from evidence, and until now there was none.

WHY THERE IS NONE IN A SNAPSHOT. With two sources, one saying Leeds and
one saying Hull, nothing in that moment says which is right: the
evidence is symmetric. Truth-discovery methods that rank sources by
agreement (Li et al., "A Survey on Truth Discovery", SIGKDD Explorations
2016) need three or more sources voting on the same item, and this
project's deployments mostly have two.

WHAT IS EVIDENCE: HOW A DISAGREEMENT ENDS. If the last recorded
disagreement had billing at Leeds and the CRM at Hull, and both now say
Hull, billing is the one that changed -- so the CRM held the value both
ended up agreeing on. Counted over many ended disagreements, that is a
track record per field and pair of sources. Dong, Berti-Equille and
Srivastava model sources over time the same way, by how their values
change, in "Truth Discovery and Copying Detection in a Dynamic World"
(PVLDB 2(1), 2009).

ITS LIMITS, STATED SO NOBODY READS MORE INTO IT:

  "Held" is not "true". Both sources ending on Hull says the CRM's value
  was the one kept, which is evidence about who was right, not proof:
  a clerk can copy a wrong value into the right system.

  Both moving to a THIRD value is no evidence either way, and is not
  counted. Neither is a disagreement still open, or one whose entity or
  source has gone.

  NO VOTING across three or more sources yet (owner, 15 October: none
  of the deployments has a field held by three).

EVIDENCE ONLY. Nothing here changes survivorship. A deployment that
finds its preferred source usually loses changes `prefer` itself.

KEPT, NOT RECOMPUTED FROM SCRATCH. An ended disagreement is recorded
once, keyed by the last conflict row's time, the first time a sync sees
it ended. Recomputing from current values every time would lose the
evidence as soon as both sources moved on again.
"""

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.erased_ids import is_erased
from core.sqlite_connection import connection_with_schema

# Shown in the browser only from this many ended disagreements, and then
# rounded to the nearest ten per cent (owner, 15 October). The counts
# span every compartment; a share, rounded, says much less about how
# many there are than "7 of 9" would.
SHOWN_FROM = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS ended_disagreements (
    object_type      TEXT NOT NULL,
    entity_id        TEXT NOT NULL,
    field            TEXT NOT NULL,
    -- The last conflict row's recorded_at: one disagreement, however
    -- many publications it lasted.
    last_recorded_at TEXT NOT NULL,
    held_source      TEXT NOT NULL,
    moved_source     TEXT NOT NULL,
    observed_at      TEXT NOT NULL,
    PRIMARY KEY (object_type, entity_id, field, last_recorded_at)
);
"""


@dataclass(frozen=True)
class Ended:
    entity_id: str
    field: str
    last_recorded_at: str
    held_source: str
    moved_source: str


def ended_disagreements(conflict_rows: Iterable[Mapping[str, Any]],
                        current: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> list[Ended]:
    """Disagreements that have ended, and which side's value both hold.

    `conflict_rows` are the conflicts table's rows; only "property" ones
    are disagreements about a value. `current` is entity -> field ->
    source -> value as the sources hold them now.
    """
    latest: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in conflict_rows:
        if row.get("kind") != "property" or not row.get("field"):
            continue
        key = (str(row["entity_id"]), str(row["field"]))
        if key not in latest or str(row.get("recorded_at")) > str(latest[key].get("recorded_at")):
            latest[key] = row
    found = []
    for (entity_id, field_name), row in sorted(latest.items()):
        chosen_source = str(row.get("chosen_source") or "")
        losing_source = str(row.get("losing_source") or "")
        if not chosen_source or not losing_source:
            continue
        values = (current.get(entity_id) or {}).get(field_name) or {}
        if chosen_source not in values or losing_source not in values:
            continue  # the entity, or one of the sources, has gone
        now_chosen, now_losing = values[chosen_source], values[losing_source]
        if now_chosen is None or now_losing is None or str(now_chosen) != str(now_losing):
            continue  # still disagreeing, or one has nothing to say
        agreed = str(now_chosen)
        # A NULL SIDE IS NOT A VALUE: str(None) is "None", which a real
        # value can equal.
        if row.get("losing") is not None and agreed == str(row["losing"]):
            held, moved = losing_source, chosen_source
        elif row.get("chosen") is not None and agreed == str(row["chosen"]):
            held, moved = chosen_source, losing_source
        else:
            continue  # both moved to a third value: no evidence either way
        found.append(Ended(entity_id, field_name, str(row.get("recorded_at")), held, moved))
    return found


def current_values(type_def: dict, resolution: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """entity -> field -> source -> value, as each source holds it now:
    what survivorship chose between, before it chose. Named the way the
    conflicts table names sources."""
    from core.mirror.survivorship import _column_for, _source_name

    fields = list(type_def.get("fields") or {})
    found: dict[str, dict[str, dict[str, Any]]] = {}
    for entity_id, members in resolution.entities.items():
        per_field: dict[str, dict[str, Any]] = {}
        for field_name in fields:
            for storage_key, row in members.items():
                column = _column_for(type_def, field_name, storage_key)
                if column is not None and column in row:
                    per_field.setdefault(field_name, {})[_source_name(storage_key)] = row[column]
        found[str(entity_id)] = per_field
    return found


@dataclass(frozen=True)
class TrackRecord:
    field: str
    sources: tuple[str, str]  # sorted
    held: Mapping[str, int]   # source -> times its value was the one kept

    @property
    def total(self) -> int:
        return sum(self.held.values())

    def leader(self) -> "tuple[str, float]":
        """The source held more often, and its share. Ties go to the
        first by name, so the answer does not depend on row order."""
        source = max(sorted(self.sources), key=lambda name: self.held.get(name, 0))
        return source, self.held.get(source, 0) / self.total if self.total else 0.0

    def shown(self) -> "dict | None":
        """What the browser may see: the leader and its share rounded to
        the nearest ten per cent, from SHOWN_FROM ended disagreements.
        No counts."""
        if self.total < SHOWN_FROM:
            return None
        source, share = self.leader()
        return {"source": source, "about_percent": int(round(share * 10) * 10)}


class SourceRecordStore:
    def __init__(self, database: Path):
        self._database = database
        with self._connection():
            pass

    def _connection(self):
        return connection_with_schema(self._database, SCHEMA)

    def record(self, object_type: str, ended: Iterable[Ended]) -> int:
        """Keep each ended disagreement once. Returns how many were new."""
        now = datetime.now(UTC).isoformat()
        added = 0
        with self._connection() as conn:
            for item in ended:
                try:
                    conn.execute(
                        "INSERT INTO ended_disagreements VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (object_type, item.entity_id, item.field, item.last_recorded_at,
                         item.held_source, item.moved_source, now))
                    added += 1
                except sqlite3.IntegrityError:
                    pass  # already kept
            conn.commit()
        return added

    def track_records(self, object_type: str) -> dict[tuple[str, frozenset], TrackRecord]:
        """(field, the pair of sources) -> its track record."""
        held: dict[tuple[str, frozenset], dict[str, int]] = {}
        with self._connection() as conn:
            for row in conn.execute(
                    "SELECT field, held_source, moved_source, COUNT(*) AS n "
                    "FROM ended_disagreements WHERE object_type = ? "
                    "GROUP BY field, held_source, moved_source", (object_type,)):
                key = (row["field"], frozenset((row["held_source"], row["moved_source"])))
                counts = held.setdefault(key, {})
                counts[row["held_source"]] = counts.get(row["held_source"], 0) + row["n"]
        return {key: TrackRecord(key[0], tuple(sorted(key[1])), counts)  # type: ignore[arg-type]
                for key, counts in held.items()}

    def forget_erased(self, key_hash, hashes_by_type: dict) -> int:
        """Every ended disagreement about an erased record, gone (R13), as
        MergeDecisionStore.forget_erased does for proposals. Returns how
        many. An erased person's track-record entries would otherwise
        say "this entity's email was disputed and settled", which is a
        fact about them."""
        if not hashes_by_type:
            return 0
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT rowid, object_type, entity_id FROM ended_disagreements").fetchall()
            doomed = [(row["rowid"],) for row in rows
                      if is_erased(key_hash, hashes_by_type, row["object_type"], row["entity_id"])]
            conn.executemany("DELETE FROM ended_disagreements WHERE rowid = ?", doomed)
            conn.commit()
        return len(doomed)
