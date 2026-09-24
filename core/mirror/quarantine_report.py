"""What the pipeline held back, and why (OPEN_RISKS item 1).

THE PROBLEM THIS EXISTS FOR. A quarantined row is ABSENT from silver
and therefore from gold, by design -- it failed a rule the deployment
declared, and letting it through would put data in the ontology that
the ontology says is invalid. But absence reads as LOSS. A person
looking at 4,000 customers when their database has 4,200 has no way to
tell whether 200 rows were rejected on purpose, dropped by a bug, or
never existed.

SO THE COUNTS ARE THE POINT, not the rows. The rows themselves stay
in bronze exactly as the source wrote them, and the quarantine table
records the id, the rule that caught it and the value -- appended, so
a run's findings do not erase the last run's. What was missing is
anything that says "this happened" anywhere a person looks.

WHY THIS IS A SEPARATE MODULE rather than a query in a route: the same
counts belong in three places -- the mirror panel, the health check,
and (when it exists) the pipeline canvas's silver lane -- and three
copies of a query that must agree is how they stop agreeing.

WHAT IT DELIBERATELY DOES NOT DO: show the values. A quarantined row
failed a rule about its CONTENT, so the value that failed is often the
sensitive part -- a malformed national insurance number is still a
national insurance number. Counts and rule names are safe to show
anyone who may see the table at all; the values need the same
authorisation as the object, which is a question for the UI patch that
displays them, not for this one.
"""

from dataclasses import dataclass, field

from pyiceberg.exceptions import NoSuchNamespaceError, NoSuchTableError

QUARANTINE_PREFIX = "quarantine_"


@dataclass
class TableQuarantine:
    """What one source table had held back."""

    silo: str
    table: str
    rows: int = 0
    # rule -> how many rows it caught, so an operator sees WHICH rule
    # is rejecting rather than only that something is.
    by_reason: dict[str, int] = field(default_factory=dict)
    last_detected_at: str | None = None

    @property
    def worst_reason(self) -> str | None:
        if not self.by_reason:
            return None
        return max(self.by_reason.items(), key=lambda entry: entry[1])[0]


def quarantine_for(catalog, silo: str, table: str) -> TableQuarantine:
    """One table's held-back rows, or an empty report if it has none.

    AN ABSENT TABLE IS NOT AN ERROR: a deployment whose rules have
    never fired has no quarantine namespace at all, which is the
    normal and happy case.
    """
    report = TableQuarantine(silo=silo, table=table)
    try:
        rows = catalog.load_table(
            f"{QUARANTINE_PREFIX}{silo}.{table}").scan().to_arrow().to_pylist()
    except (NoSuchTableError, NoSuchNamespaceError, FileNotFoundError):
        return report

    held: set[str] = set()
    for row in rows:
        object_id = row.get("object_id")
        if object_id is not None:
            held.add(str(object_id))
        reason = row.get("reason") or "unknown"
        report.by_reason[reason] = report.by_reason.get(reason, 0) + 1
        detected = row.get("detected_at")
        if detected and (report.last_detected_at is None
                          or detected > report.last_detected_at):
            report.last_detected_at = detected
    # ROWS, NOT FINDINGS. One row can fail two rules, and reporting
    # "2 rows quarantined" for one bad customer would make the number
    # mean nothing next to a row count.
    report.rows = len(held)
    return report


def quarantine_summary(catalog, targets) -> dict:
    """Totals across every table, for the health check.

    SHAPED FOR A GLANCE: how many rows are held back in total, and how
    many tables have any. A health check that listed every rule would
    be read by nobody.
    """
    total_rows = 0
    affected = []
    for target in targets:
        report = quarantine_for(catalog, target.silo_name, target.table_name)
        if report.rows:
            total_rows += report.rows
            affected.append(f"{report.silo}.{report.table}")
    return {"rows": total_rows, "tables": sorted(affected)}
