"""The rules that fired and let the row through anyway.

WHAT IS LOST WITHOUT THIS. A declared expectation has three policies.
`fail` stops the build and the refusal is recorded as a sync attempt.
`quarantine` holds the row back and writes a finding to the lake, with
the rule that caught it. `warn` keeps the row -- and the finding lived
in a log line on whatever process ran the sync, which on an unattended
on-prem deployment is a file nobody opens.

SO THE PERMISSIVE POLICY WAS THE INVISIBLE ONE, which is the wrong way
round. A quarantined row is absent and the absence is explained. A
warned row is PRESENT, in silver, in gold and on screen, identical to
a row that broke no rule -- and the deployment declared a rule about
it precisely because somebody wanted to know.

DEV_UI.md section 5 item 6 asks for "failing expectations" beside the
quarantined rows, and this is the half that had nowhere to come from.

COUNTS PER RULE PER RUN, NOT A ROW PER FINDING, and the asymmetry with
quarantine is deliberate rather than an inconsistency.

A quarantine rule should catch few rows; if it catches many, that is
itself the finding, and one lake row per held row is affordable. A
WARN rule is the one the deployment has already decided to tolerate,
so it may legitimately fire on most of a large table on every sync --
and the quarantine table is appended and never pruned. Recording warn
findings the same way would grow without bound for exactly the case
somebody has said is fine. Counts are bounded by rules x runs, and
counts are what the mirror panel displays.

ONE HOME EACH, which is the rule this store exists to respect. A
quarantined finding is read back out of the lake by
`quarantine_report.py`; a warned one is read back out of here.
Nothing is recorded in both places, because two stores holding one
number is how they stop agreeing.

A SEPARATE FILE FROM sync_attempts.db, though it is modelled on it
line for line. They are written at different moments -- an attempt is
recorded whether or not the table was ever read, a warning only once
the rows have been checked -- and a store that must survive a sync
that never got as far as reading has no business sharing a schema
with one that only exists when it did.
"""

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.sqlite_connection import connection_with_schema

# HOW LONG A WARNING IS WORTH KEEPING.
#
# Thirty days, matching sync_attempts for the reason that store gives:
# it covers "what happened last night" and "has this been firing all
# month" without keeping a year of noise. Stated rather than imported,
# because the two are unrelated stores whose numbers agreeing is a
# coincidence rather than a shared decision.
RETENTION_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS expectation_warnings (
    at REAL NOT NULL,
    silo TEXT NOT NULL,
    table_name TEXT NOT NULL,
    -- WHICH COLUMN, SEPARATE FROM THE REASON. A reason names the rule
    -- and not the column, so two columns failing the same way are one
    -- key if they are stored joined -- which makes the count
    -- undividable and, beside a table size, wrong.
    column_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    -- How many rows failed it in THIS run. Not cumulative: a reader
    -- asking "is this getting worse" needs the per-run figure, and a
    -- running total can be derived from these while the reverse is
    -- not true.
    rows INTEGER NOT NULL,
    -- WHICH RUN, so a warning can be lined up against the sync attempt
    -- and the gold publication it happened in. Nullable for the same
    -- reason sync_attempts' is: a caller that does not know its run
    -- should say so rather than invent one.
    run_id TEXT
);
-- Every read is "what has been warning about this table lately", so
-- the pair is the index. One on time alone would still scan a table's
-- whole history.
CREATE INDEX IF NOT EXISTS expectation_warnings_table_at
    ON expectation_warnings (silo, table_name, at);
"""


@dataclass(frozen=True)
class Warning_:
    """One rule's findings in one run, as a reader sees it.

    THE TRAILING UNDERSCORE is not style. `Warning` is a builtin
    exception type, and a dataclass shadowing it in a module that also
    swallows exceptions is a trap worth one ugly character.
    """

    at: datetime
    column: str
    reason: str
    rows: int


class ExpectationWarnings:
    """Records the rules that warned, and answers what has been warning.

    NEVER RAISES INTO THE SYNC, which is the bargain every store beside
    the mirror makes: a sync whose data work succeeded must not fail
    because its bookkeeping did. Failures are swallowed, and the cost
    of that is stated plainly -- a warning that could not be written is
    a warning nobody sees, which is no worse than the log line it
    replaces and no better.
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def record(self, silo: str, table_name: str, warnings: list,
               run_id: str | None = None) -> None:
        """Records one run's warnings for one table. Silent on failure.

        NOTHING IS WRITTEN FOR A CLEAN RUN. A row per table per sync
        saying "no rules warned" would be the bulk of this store on a
        healthy deployment, and "when did this last warn" is answered
        by the absence.
        """
        if not warnings:
            return
        # ONE TIMESTAMP FOR THE WHOLE RUN, read once rather than per
        # row. `latest_for` groups a run by its `at`, and calling
        # time.time() inside the comprehension gave every rule a
        # slightly different one -- so a run that warned about four
        # columns reported one. Caught by a test asserting that one
        # run's rules are all reported; it would have shipped as "the
        # panel only ever shows a single rule", which looks like a
        # display bug and is not one.
        at = time.time()
        try:
            with self._connection() as conn:
                conn.executemany(
                    "INSERT INTO expectation_warnings "
                    "(at, silo, table_name, column_name, reason, rows, run_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(at, silo, table_name, rule.column, rule.reason,
                      rule.rows, run_id) for rule in warnings],
                )
                # EXPLICIT, because open_connection sets
                # isolation_level='' -- an implicit transaction opens on
                # the first write and is ROLLED BACK on close unless
                # committed. sync_attempts lost its rows this way once.
                conn.commit()
        except Exception:  # noqa: BLE001 - see the class docstring
            return

    def latest_for(self, silo: str, table_name: str) -> list[Warning_]:
        """The most recent run's warnings for one table, or empty.

        THE LAST RUN, NOT EVERY RUN. A rule fixed on Tuesday should
        stop being reported on Wednesday, and summing the history would
        keep it on screen for thirty days -- which is how a panel
        becomes one people stop reading.
        """
        try:
            with self._connection() as conn:
                latest = conn.execute(
                    "SELECT MAX(at) AS at FROM expectation_warnings "
                    "WHERE silo = ? AND table_name = ?",
                    (silo, table_name),
                ).fetchone()
                if latest is None or latest["at"] is None:
                    return []
                rows = conn.execute(
                    "SELECT at, column_name, reason, rows FROM expectation_warnings "
                    "WHERE silo = ? AND table_name = ? AND at = ? "
                    "ORDER BY rows DESC, column_name, reason",
                    (silo, table_name, latest["at"]),
                ).fetchall()
        except Exception:  # noqa: BLE001 - see the class docstring
            return []

        return [
            Warning_(
                at=datetime.fromtimestamp(row["at"], tz=UTC),
                column=row["column_name"],
                reason=row["reason"],
                rows=row["rows"],
            )
            for row in rows
        ]

    def forget_older_than(self, days: int = RETENTION_DAYS) -> int:
        """Drops warnings nobody will ask about. Returns how many."""
        cutoff = time.time() - days * 86400
        try:
            with self._connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM expectation_warnings WHERE at < ?", (cutoff,),
                )
                conn.commit()
                return cursor.rowcount
        except Exception:  # noqa: BLE001 - see the class docstring
            return 0
