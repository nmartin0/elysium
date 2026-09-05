"""
transform.py  (the raw -> clean stage: type casting and drift detection)

Phase 3 of the read-only mirror architecture. This is the middle stage
of the three-stage pipeline Foundry's own architecture uses, and which
Elysium previously skipped:

    raw  ->  clean  ->  ontology
     ^         ^
     |         this module
     sync (core/mirror/iceberg_sync.py)

WHY THIS EXISTS, and why the earlier decision to skip it was wrong.
The phase was originally deferred on the grounds that it "pre-computes
an MDO join" the local mirror already makes cheap. That reasoning was
entirely about join PERFORMANCE, which is not what a transform stage
is for. Checked against Foundry's own documented guidance rather than
assumed:

  - Type casting is drift DETECTION, not speed. Their build guidance
    says to explicitly cast column types in the raw -> clean transform
    "even if the schema inference from the data connection has chosen
    correct values," precisely because doing so "will help catch
    breaking changes from the source system if a column type changes
    or an invalid value creates an incorrect inference during the
    sync."
  - The ingest stage is meant to stay dumb. Foundry's own connection
    layer "deliberately offer[s] minimal options for transforming the
    data before it arrives in the destination dataset (the starting
    point of the Foundry pipeline)."

WHAT THIS FIXES CONCRETELY. Phase 4 added ontology-declared field types
(core/ontology/field_types.py) and wired the casting directly INTO
core/mirror/iceberg_sync.py -- the raw -> clean responsibility bolted
onto the ingest stage. It worked, but it put transformation in the one
place Foundry's architecture deliberately keeps free of it, and it
meant a type mismatch surfaced as a sync failure rather than as a
distinct, diagnosable drift report.

WHAT THIS DELIBERATELY IS NOT. Not a materialization of per-object-type
tables, and not a pre-computed MDO join -- that was the original
Phase 3 plan and its justification did not hold up. MDO resolution
stays where it is, at read time in DataMediator, exactly as Foundry
keeps MDOs a first-class read-time concept rather than flattening them
in a pipeline.

DRIFT IS REPORTED, NOT SWALLOWED. A column whose real values no longer
match what the ontology declares is a genuine, actionable signal that
the customer's source system changed underneath us. It produces a real
DriftReport naming the column, the declared type, and a real example
of the offending value -- never a silently substituted default, and
never a bare exception with no context about which column of which
table failed.

Used by: core/mirror/iceberg_sync.py (the sync applies this stage
         between reading raw rows and writing them)
"""

from dataclasses import dataclass, field

from core.ontology.field_types import DEFAULT_FIELD_DATA_TYPE, coerce


@dataclass(frozen=True)
class DriftedColumn:
    """One column whose real data no longer matches its declared type."""

    column: str
    declared_type: str
    # A real, offending value -- not a count, not a summary. Whoever
    # investigates needs to see what actually arrived.
    example_value: object
    row_count_checked: int


@dataclass
class TransformResult:
    """The outcome of transforming one table's raw rows.

    Carries BOTH the cleaned rows and any drift found, rather than
    raising on the first problem: a caller may legitimately want to
    know about every drifted column in one pass instead of discovering
    them one sync at a time.
    """

    rows: list[dict]
    drift: list[DriftedColumn] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.drift)


def transform_rows(rows: list[dict], columns: list[str],
                    column_types: dict[str, str] | None = None) -> TransformResult:
    """Casts every column to its ontology-declared type, reporting any
    column whose real data does not fit.

    A column with no declared type passes through as a string -- the
    same default the ontology itself applies, so a schema predating
    field types behaves exactly as before.

    Drift is collected per COLUMN, not per row: one source column that
    changed type produces one report naming a real example, rather than
    thousands of identical failures.
    """
    column_types = column_types or {}
    resolved = {column: column_types.get(column, DEFAULT_FIELD_DATA_TYPE) for column in columns}

    drift: list[DriftedColumn] = []
    drifted_columns: set[str] = set()
    cleaned: list[dict] = []

    for row in rows:
        cleaned_row = {}
        for column in columns:
            declared = resolved[column]
            try:
                cleaned_row[column] = coerce(row[column], declared)
            except (ValueError, TypeError):
                # The FIRST offending value for this column is the one
                # reported -- later ones are almost always the same
                # problem, and a report per row would bury the signal.
                if column not in drifted_columns:
                    drifted_columns.add(column)
                    drift.append(
                        DriftedColumn(
                            column=column,
                            declared_type=declared,
                            example_value=row[column],
                            row_count_checked=len(rows),
                        )
                    )
                # The raw value is kept rather than dropped or defaulted:
                # the caller decides what to do about a drifted table,
                # and silently substituting would destroy the evidence.
                cleaned_row[column] = row[column]
        cleaned.append(cleaned_row)

    return TransformResult(rows=cleaned, drift=drift)


def describe_drift(silo_name: str, table_name: str, drift: list[DriftedColumn]) -> str:
    """A real, operator-facing description of what drifted.

    Written for whoever reads a failed sync's output at 3am: it names
    the table, the column, what the ontology expected, and what
    actually arrived -- not a stack trace.
    """
    lines = [f"Schema drift in {silo_name}.{table_name}:"]
    for item in drift:
        lines.append(
            f"  column {item.column!r} is declared {item.declared_type!r} "
            f"but contains {item.example_value!r} "
            f"(checked {item.row_count_checked} rows)"
        )
    return "\n".join(lines)
