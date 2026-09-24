"""Building gold without holding the whole table (GOLD-7).

MEASURED, WITH THE RIGHT INSTRUMENT THIS TIME. Patch 384 reported the
Arrow path peaking at 0.4 MB, using tracemalloc -- which does not see
Arrow's buffers at all, because they are allocated outside Python's
allocator. Measured by RSS instead, on 300,000 rows of six wide
string columns:

    the whole table materialised   +81.8 MB
    streamed in batches            +11.0 MB

and the 11 MB is almost entirely the SET OF IDS, which the audit needs
to find duplicates. So the residual cost is proportional to the number
of objects rather than to the width of their rows -- a table twice as
wide streams in the same memory.

WHAT MADE THIS POSSIBLE. PyIceberg's scan produces a
RecordBatchReader, and its append ACCEPTS one, so both halves stream
and nothing needs a second copy.

WHAT THE AUDIT NEEDED INSTEAD. "Are these ids unique" cannot be
answered by a batch that has not seen the others, which is why patch
384 recorded streaming as blocked. The answer is not to give up the
check but to accumulate the part that needs memory: ids, and counts.
Everything else the audit asks -- how many rows have no id, how many
lack a required property, how many point at a target that does not
exist, how many rows there are against last time -- is a running
total.

THE MESSAGES ARE THE SAME, WORD FOR WORD, as the whole-table audit.
Three implementations of one check now exist (rows, table, stream) and
they are tested against each other, because checks that are supposed
to agree and quietly drift apart are worse than one slow check.
"""

from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from core.ontology.link_types import is_reverse_link


class StreamingAudit:
    """The whole-table audit, accumulated a batch at a time."""

    def __init__(self, type_def: dict, known_ids: "dict[str, set] | None" = None):
        self._type_def = type_def
        self._known_ids = known_ids or {}
        self._id_field = type_def["id_field"]
        self._rows = 0
        self._missing_ids = 0
        self._seen: set = set()
        self._duplicated: set = set()
        self._absent_required: dict[str, int] = {}
        self._dangling: dict[str, set] = {}
        self._no_id_column = False

    def add(self, batch: pa.RecordBatch) -> None:
        """Fold one batch into the running answer."""
        table = pa.Table.from_batches([batch])
        self._rows += table.num_rows
        if self._id_field not in table.column_names:
            self._no_id_column = True
            return

        ids = table.column(self._id_field)
        self._missing_ids += ids.null_count
        for value in ids.drop_null().to_pylist():
            # THE ONE THING THAT MUST BE REMEMBERED. Everything else
            # here is a counter; uniqueness is not, and pretending
            # otherwise would mean dropping the check.
            if value in self._seen:
                self._duplicated.add(value)
            else:
                self._seen.add(value)

        fields = self._type_def.get("fields") or {}
        for field_name, field_config in fields.items():
            if field_config.get("required"):
                if field_name not in table.column_names:
                    self._absent_required[field_name] = (
                        self._absent_required.get(field_name, 0) + table.num_rows)
                else:
                    absent = table.column(field_name).null_count
                    if absent:
                        self._absent_required[field_name] = (
                            self._absent_required.get(field_name, 0) + absent)

        for field_name, field_config in fields.items():
            if field_config.get("type") != "link" or is_reverse_link(field_config):
                continue
            target = field_config.get("target")
            if target not in self._known_ids or field_name not in table.column_names:
                continue
            values = table.column(field_name).drop_null()
            if not len(values):
                continue
            absent_mask = pc.invert(pc.is_in(
                values,
                value_set=pa.array(sorted(str(value) for value in self._known_ids[target])),
            ))
            missing = set(values.filter(absent_mask).to_pylist())
            if missing:
                self._dangling.setdefault(field_name, set()).update(missing)

    @property
    def rows(self) -> int:
        return self._rows

    def problems(self, previous_count: int | None) -> list[str]:
        """The same findings, in the same words, as audit_arrow()."""
        from core.mirror.gold import MAX_DELETED_FRACTION

        if self._no_id_column:
            return [f"no {self._id_field} column"]

        problems: list[str] = []
        if self._missing_ids:
            problems.append(f"{self._missing_ids} row(s) have no {self._id_field}")
        if self._duplicated:
            shown = ", ".join(
                repr(value) for value in sorted(self._duplicated, key=repr)[:5])
            problems.append(
                f"{len(self._duplicated)} duplicate {self._id_field}(s): {shown}")
        for field_name, absent in self._absent_required.items():
            problems.append(f"{absent} row(s) are missing required {field_name}")
        for field_name, values in self._dangling.items():
            target = (self._type_def["fields"][field_name] or {}).get("target")
            shown = ", ".join(repr(value) for value in sorted(values, key=repr)[:5])
            problems.append(
                f"{len(values)} {field_name} value(s) point at no {target}: {shown}")
        if previous_count and self._rows < previous_count * (1 - MAX_DELETED_FRACTION):
            problems.append(
                f"{self._rows} rows, down from {previous_count}: more than "
                f"{MAX_DELETED_FRACTION:.0%} of the last publication is gone"
            )
        return problems


def conformed_batches(type_def: dict, reader: Any, audit: StreamingAudit):
    """Silver's batches, conformed, with the audit folded in as they go.

    A GENERATOR, so the caller can hand it straight to Iceberg's append
    and neither side ever holds more than one batch. The audit is
    accumulated HERE rather than in a second pass, because a second
    pass would read the table twice and the point is to read it once.
    """
    from core.mirror.gold_arrow import conform_arrow

    for batch in reader:
        conformed = conform_arrow(type_def, pa.Table.from_batches([batch]))
        for conformed_batch in conformed.to_batches():
            audit.add(conformed_batch)
            yield conformed_batch
