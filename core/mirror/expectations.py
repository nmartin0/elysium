"""What silver checks on every row, and what it does about a failure
(GOLD-1, MEDALLION_PIPELINE.md's S2 and S3).

THE RULES ARE THE ONES THAT ALREADY EXIST. A field's `constraints`
block -- min/max, min_length/max_length, pattern, one_of (patch 297) --
is evaluated at the point of a WRITE. The same block is an expectation
about what a SOURCE holds, and this evaluates it there. One rule
language, declared once; `required` adds completeness, which a write
gets from the source's own NOT NULL.

THE POLICIES, and the owner's decision of September 22:

  warn (the default)  the row lands, the violation is counted and
                      reported. Precedent: per-row expectations keep
                      the record and count it, because a pipeline that
                      silently drops rows is worse than one that
                      reports them.
  quarantine          the row does NOT land in silver; it is written
                      to the quarantine table with the rule that
                      rejected it. NEVER a silent drop: the ELT
                      promise is that data is preserved along the
                      path, and bronze still holds the row as the
                      source wrote it.
  fail                the silver build stops and the mirror is
                      unchanged. Precedent: build-level checks
                      default to failing, because a table that breaks
                      a rule this badly cannot back an object type.

Accuracy is NOT checked here and never claimed: whether a value
matches the real world cannot be known from the row. Validity,
completeness and uniqueness can, and are.
"""

from dataclasses import dataclass, field
from typing import Any

from core.ontology.constraints import violation

WARN = "warn"
QUARANTINE = "quarantine"
FAIL = "fail"
POLICIES = (WARN, QUARANTINE, FAIL)


@dataclass(frozen=True)
class Violation:
    """One row failing one rule."""

    column: str
    field_name: str
    reason: str
    value: Any
    policy: str


@dataclass
class ExpectationResult:
    kept: list[dict] = field(default_factory=list)
    quarantined: list[tuple[dict, Violation]] = field(default_factory=list)
    warned: list[Violation] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        """Per rule, how many rows failed it -- the metric a run reports."""
        counts: dict[str, int] = {}
        for entry in self.warned + [v for _, v in self.quarantined]:
            counts[f"{entry.column}: {entry.reason}"] = (
                counts.get(f"{entry.column}: {entry.reason}", 0) + 1
            )
        return counts


def policy_for(field_config: dict) -> str:
    """The declared policy, or warn. Raises on an unknown one: a typo
    that silently downgraded a `fail` to nothing would be the worst
    possible failure of this feature."""
    declared = field_config.get("on_violation", WARN)
    if declared not in POLICIES:
        raise ValueError(
            f"on_violation must be one of {list(POLICIES)}, got {declared!r}."
        )
    return declared


def expectations_for(field_config: dict) -> dict | None:
    """What to check for one column, or None when it declares nothing."""
    if not field_config.get("constraints") and not field_config.get("required"):
        return None
    return {
        "field_def": field_config,
        "required": bool(field_config.get("required")),
        "policy": policy_for(field_config),
    }


def check_row(row: dict, expectations: dict[str, dict]) -> list[Violation]:
    """Every rule this row fails, in column order."""
    found = []
    for column, expected in expectations.items():
        value = row.get(column)
        field_name = expected.get("field_name", column)
        if value is None:
            if expected["required"]:
                found.append(Violation(column, field_name, "is required, and missing",
                                       None, expected["policy"]))
            # A NULL cannot violate a range or a pattern: it is the
            # absence of a value, which `required` is the rule for.
            continue
        reason = violation(expected["field_def"], value)
        if reason is not None:
            found.append(Violation(column, field_name, reason, value, expected["policy"]))
    return found


def apply_expectations(rows: list[dict], expectations: dict[str, dict]) -> ExpectationResult:
    """Rows split by what their violations' policies say to do.

    A row failing several rules is quarantined if ANY of them says so,
    and reported for each -- the strictest policy a row meets decides
    where it goes, so a `quarantine` rule is never overridden by a
    `warn` one on another column.
    """
    result = ExpectationResult()
    if not expectations:
        result.kept = list(rows)
        return result
    for row in rows:
        violations = check_row(row, expectations)
        failed = [v for v in violations if v.policy == FAIL]
        if failed:
            raise ExpectationFailed(failed[0])
        held = next((v for v in violations if v.policy == QUARANTINE), None)
        if held is not None:
            result.quarantined.append((row, held))
            continue
        result.warned.extend(v for v in violations if v.policy == WARN)
        result.kept.append(row)
    return result


class ExpectationFailed(Exception):
    """A rule declared `fail`. The build stops; the mirror is unchanged."""

    def __init__(self, violation: Violation):
        self.violation = violation
        super().__init__(
            f"{violation.column} ({violation.field_name}): {violation.reason} "
            f"-- value {violation.value!r}. This field declares on_violation: fail, "
            f"so the mirror is unchanged."
        )
