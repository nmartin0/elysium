"""Column profiles of each gold publication, and the drift between them (R7).

WHAT THE OTHER CHECKS CANNOT SEE. Expectations judge one value against
a rule; the gold audit judges a build against the last one by row count
and keys. Neither notices a column whose values are each individually
fine and collectively wrong: an email column that is suddenly 40% empty,
an amount whose average jumped tenfold because a source started
writing pence, a status that collapsed to one value. Every row passes;
the column is broken.

THE PRECEDENT IS AWS DEEQU's: compute METRICS per run (completeness,
distinct count, mean, standard deviation, min, max), keep them in a
metrics repository, and run ANOMALY checks on the series -- its
RelativeRateOfChange and OnlineNormal strategies are the two below.
Great Expectations' profilers and Monte Carlo's field health are the
same idea commercially.

PROFILED AT GOLD, because gold is what readers see -- a drift in silver
that gold's survivorship absorbed is not a reader's problem -- and per
FIELD, in the ontology's words, so a finding names a property a person
recognises rather than a source column.

ONCE PER PUBLICATION. A sync that published nothing new profiles
nothing, so an hourly sync over a quiet table does not fill the store
with identical rows, and drift is always measured between two different
publications.

THE THRESHOLDS ARE JUDGEMENTS, stated as constants, and loose on
purpose: a check that cries wolf on every sync is a check nobody reads.

LIMITED TO WHAT AN ARROW COLUMN CAN SAY CHEAPLY. Distribution shape
beyond mean and spread (a histogram, a KS test) is not computed: on a
CPU-bound deployment one pass of Arrow kernels per column is the budget.
"""

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc

from core.sqlite_connection import connection_with_schema

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS column_profiles (
    at REAL NOT NULL,
    object_type TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    field TEXT NOT NULL,
    profile TEXT NOT NULL
)
"""

#: Completeness falling by more than this (absolute) is drift: 2% empty
#: becoming 25% empty is a source that stopped sending a field.
NULL_RISE = 0.20
#: The distinct count moving by more than this RATIO either way (Deequ's
#: RelativeRateOfChange): a status column with five values collapsing to
#: one, or an id-like column suddenly repeating.
DISTINCT_CHANGE = 0.5
#: A numeric mean moving by more than this many of the PREVIOUS
#: standard deviations (Deequ's OnlineNormal): pence written as pounds.
MEAN_SIGMAS = 3.0
#: Below this many rows a profile says too little to compare.
MIN_ROWS = 20

_NUMERIC = (pa.types.is_integer, pa.types.is_floating, pa.types.is_decimal)


@dataclass(frozen=True)
class Drift:
    object_type: str
    field: str
    what: str

    def __str__(self) -> str:
        return f"{self.object_type}.{self.field}: {self.what}"


def profile_table(table: pa.Table, fields: list[str]) -> dict[str, dict]:
    """One profile per field present in the table."""
    profiles = {}
    rows = table.num_rows
    for name in fields:
        if name not in table.column_names:
            continue
        column = table.column(name)
        profile: dict = {"rows": rows, "nulls": column.null_count}
        try:
            profile["distinct"] = pc.count_distinct(column, mode="only_valid").as_py()
        except (pa.ArrowNotImplementedError, pa.ArrowInvalid):
            pass
        if any(check(column.type) for check in _NUMERIC) and rows - column.null_count > 0:
            numbers = pc.cast(column, pa.float64())
            profile["mean"] = pc.mean(numbers).as_py()
            profile["std"] = pc.stddev(numbers).as_py()
            profile["min"] = pc.min(numbers).as_py()
            profile["max"] = pc.max(numbers).as_py()
        profiles[name] = profile
    return profiles


def drift_between(object_type: str, before: dict[str, dict],
                  after: dict[str, dict]) -> list[Drift]:
    """What moved more than a threshold allows, field by field."""
    found = []
    for name, now in after.items():
        then = before.get(name)
        if not then or then.get("rows", 0) < MIN_ROWS or now.get("rows", 0) < MIN_ROWS:
            continue
        null_then = then["nulls"] / then["rows"]
        null_now = now["nulls"] / now["rows"]
        if null_now - null_then > NULL_RISE:
            found.append(Drift(object_type, name,
                               f"empty in {null_now:.0%} of rows, up from {null_then:.0%}"))
        distinct_then, distinct_now = then.get("distinct"), now.get("distinct")
        if distinct_then and distinct_now is not None:
            ratio = distinct_now / distinct_then
            if abs(ratio - 1) > DISTINCT_CHANGE:
                found.append(Drift(object_type, name,
                                   f"{distinct_now} distinct values, was {distinct_then}"))
        if then.get("std") and "mean" in now and "mean" in then:
            sigmas = abs(now["mean"] - then["mean"]) / then["std"]
            if sigmas > MEAN_SIGMAS:
                found.append(Drift(object_type, name,
                                   f"average {now['mean']:.4g}, was {then['mean']:.4g} "
                                   f"({sigmas:.1f} standard deviations)"))
    return found


class ProfileStore:
    """Every publication's profile. Never fatal, like sync_attempts."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def latest(self, object_type: str) -> "tuple[str, dict[str, dict]] | None":
        """(snapshot id, {field: profile}) of the newest profiled publication."""
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT snapshot_id FROM column_profiles WHERE object_type = ? "
                    "ORDER BY at DESC LIMIT 1", (object_type,)).fetchone()
                if row is None:
                    return None
                rows = conn.execute(
                    "SELECT field, profile FROM column_profiles "
                    "WHERE object_type = ? AND snapshot_id = ?",
                    (object_type, row["snapshot_id"])).fetchall()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"could not read column profiles: {e}")
            return None
        return row["snapshot_id"], {r["field"]: json.loads(r["profile"]) for r in rows}

    def record(self, object_type: str, snapshot_id: str, profiles: dict[str, dict]) -> None:
        try:
            with self._connection() as conn:
                now = time.time()
                conn.executemany(
                    "INSERT INTO column_profiles (at, object_type, snapshot_id, field, profile) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [(now, object_type, snapshot_id, name, json.dumps(profile))
                     for name, profile in profiles.items()])
                conn.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"could not record column profiles: {e}")


def profile_publications(catalog, object_types: dict, store: ProfileStore) -> list[Drift]:
    """Profiles every type whose publication is new; returns the drift.

    PER TYPE, NEVER FATAL: a profile that cannot be taken costs that
    type its profile and nothing else.
    """
    from core.mirror.gold import _latest_published_snapshot
    from core.ontology.gold_view import GOLD_NAMESPACE

    found: list[Drift] = []
    for object_type, type_def in object_types.items():
        try:
            table = catalog.load_table(f"{GOLD_NAMESPACE}.{object_type}")
            snapshot = _latest_published_snapshot(table)
            if snapshot is None:
                continue
            previous = store.latest(object_type)
            if previous is not None and previous[0] == str(snapshot):
                continue
            fields = list(type_def.get("fields") or {})
            profiles = profile_table(table.scan(snapshot_id=snapshot).to_arrow(), fields)
            if previous is not None:
                found.extend(drift_between(object_type, previous[1], profiles))
            store.record(object_type, str(snapshot), profiles)
        except Exception as e:  # noqa: BLE001 - see the docstring
            logger.warning(f"could not profile gold.{object_type}: {e}")
    return found
