"""What the pipeline held back, and why (the invisible-quarantine risk).

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


@dataclass(frozen=True)
class QuarantineRule:
    """One rule, on one column, and how many rows it caught.

    WHY THIS IS KEYED ON THE COLUMN AS WELL AS THE REASON, and the
    distinction decides whether a RATE built from it means anything.

    `by_reason` below counts FINDINGS keyed on the reason text alone.
    Two different columns can fail the same way in one row -- `email`
    and `name` both "is required, and missing" -- and that row is
    counted twice. As a way of picking the loudest rule that is
    harmless; as the numerator of a percentage it is wrong, and wrong
    in the direction that looks precise.

    A row can fail a given (column, rule) pair at most once, because
    `check_row` evaluates each column's expectations once and each
    rule yields one violation. So `rows` here IS a row count and can
    be divided by a table's size.
    """

    column: str
    reason: str
    rows: int


@dataclass
class TableQuarantine:
    """What one source table had held back."""

    silo: str
    table: str
    rows: int = 0
    # rule -> how many rows it caught, so an operator sees WHICH rule
    # is rejecting rather than only that something is.
    by_reason: dict[str, int] = field(default_factory=dict)
    # THE SAME FINDINGS, SPLIT BY COLUMN TOO. Kept beside `by_reason`
    # rather than replacing it: `worst_reason` and the mirror route's
    # `quarantine_reason` are built on that one and are correct for
    # what they do, and a shape change would have rewritten two
    # working things to add a third.
    rules: list[QuarantineRule] = field(default_factory=list)
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
    # (column, reason) -> the distinct ids that pair caught. A SET
    # rather than a counter, because the same row can be written again
    # by a later run -- the quarantine table is APPENDED, never
    # overwritten, so counting findings would make a rule look worse
    # every night without the data changing.
    per_rule: dict[tuple[str, str], set[str]] = {}
    for index, row in enumerate(rows):
        object_id = row.get("object_id")
        if object_id is not None:
            held.add(str(object_id))
        reason = row.get("reason") or "unknown"
        report.by_reason[reason] = report.by_reason.get(reason, 0) + 1
        column = row.get("column") or row.get("field") or "unknown"
        # A FINDING WITH NO ID COUNTS AS ITS OWN ROW. It happens: a row
        # whose id column is itself empty fails "is required, and
        # missing" with nothing to key on. Deduping those together
        # would report one row when fifty came in; the sentinel keeps
        # them distinct. `report.rows` below still omits them, which is
        # a separate and older under-count -- noted rather than changed
        # here, because it is what `quarantined_rows` has always meant.
        identity = str(object_id) if object_id is not None else f"\x00no-id-{index}"
        per_rule.setdefault((str(column), reason), set()).add(identity)
        detected = row.get("detected_at")
        if detected and (report.last_detected_at is None
                          or detected > report.last_detected_at):
            report.last_detected_at = detected

    # LOUDEST FIRST, then alphabetically so the order is stable
    # between requests -- a list that reshuffles on refresh is one
    # nobody can compare against what they read a minute ago.
    report.rules = sorted(
        (QuarantineRule(column=column, reason=reason, rows=len(ids))
         for (column, reason), ids in per_rule.items()),
        key=lambda rule: (-rule.rows, rule.column, rule.reason),
    )
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
