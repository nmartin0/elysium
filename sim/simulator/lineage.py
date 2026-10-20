"""What the pack's names are called now (REAL_SOURCES.md O3).

A pack names its tables and columns once. A schema change -- scheduled
in the pack, or applied live -- renames or drops some of them in the
database. The simulated business has to follow, as a real one does:
the application ships with the migration, so after `quantity` becomes
`qty` the next sale is written to `qty`, and after `note` is dropped
nothing writes `note` any more. Until this, it kept the pack's names
and the next tick failed ("table 'readings' has no column(s)
['quantity']"), even when the change was applied by the engine itself.

So every place the business turns a pack name into SQL asks this first,
and every row it reads back is given the pack's names again, so that its
own logic -- `subject.x`, `picked.t.x` -- keeps working.

What the world exports follows the database, not the pack: a renamed
column is renamed in the CSV header and the API's keys, and a dropped
one is gone from them. That is how a real report behaves, and it is the
"headers change between exports" item of REAL_SOURCES.md.

Kept with the world (state.json), because a resume reads the schema
from the database and would otherwise meet the new names with nothing
to say what they used to be.
"""

from typing import Any


class Lineage:
    """Pack names to current names, per silo; None for dropped."""

    def __init__(self) -> None:
        #: (silo, pack table) -> current table name, or None if dropped.
        self._tables: dict[tuple[str, str], str | None] = {}
        #: (silo, pack table, pack column) -> current column, or None.
        self._columns: dict[tuple[str, str, str], str | None] = {}

    # -- asking ------------------------------------------------------------

    def table(self, silo: str, table: str) -> str | None:
        return self._tables.get((silo, table), table)

    def column(self, silo: str, table: str, column: str) -> str | None:
        return self._columns.get((silo, table, column), column)

    def to_current(self, silo: str, table: str, row: dict[str, Any]) -> dict[str, Any]:
        """A row the business wrote, keyed as the database is now; values
        for dropped columns are left out, as the updated application would."""
        current = {}
        for name, value in row.items():
            now = self.column(silo, table, name)
            if now is not None:
                current[now] = value
        return current

    def to_original(self, silo: str, table: str, row: dict[str, Any]) -> dict[str, Any]:
        """A row read from the database, keyed as the pack names it.

        A column the pack does not know -- one added later under a name
        a pack column has since given up -- is left out, or its value
        would be read as the pack column's.
        """
        original = {}
        for name, value in row.items():
            pack = self._pack_column(silo, table, name)
            if pack is not None:
                original[pack] = value
        return original

    @property
    def empty(self) -> bool:
        return not self._tables and not self._columns

    # -- recording ---------------------------------------------------------

    def record(self, silo: str, change: Any) -> None:
        """Follow one schema change, given in CURRENT names as it was
        applied."""
        from simulator import drift

        # A change to something the pack does not know (a table or column
        # added later) changes nothing the business uses, so it is not
        # recorded.
        if isinstance(change, (drift.RenameColumn, drift.DropColumn)):
            pack_table = self._pack_table(silo, change.table)
            column = change.old_name if isinstance(change, drift.RenameColumn) else change.column
            pack_column = None if pack_table is None else self._pack_column(silo, pack_table, column)
            if pack_table is not None and pack_column is not None:
                self._columns[(silo, pack_table, pack_column)] = (
                    change.new_name if isinstance(change, drift.RenameColumn) else None)
        elif isinstance(change, (drift.RenameTable, drift.DropTable)):
            current = change.old_name if isinstance(change, drift.RenameTable) else change.table
            pack_table = self._pack_table(silo, current)
            if pack_table is not None:
                self._tables[(silo, pack_table)] = (
                    change.new_name if isinstance(change, drift.RenameTable) else None)
        # Additions, type changes and rescales keep every name.

    def _pack_table(self, silo: str, current: str) -> str | None:
        """Which pack table a current name is; None if it is none of the
        pack's -- a name the pack's own table has since given up, now
        worn by something added later."""
        for (s, pack), now in self._tables.items():
            if s == silo and now == current:
                return pack
        return None if (silo, current) in self._tables else current

    def _pack_column(self, silo: str, table: str, current: str) -> str | None:
        """Which pack column a current name is; None as for _pack_table."""
        for (s, t, pack), now in self._columns.items():
            if s == silo and t == table and now == current:
                return pack
        return None if (silo, table, current) in self._columns else current

    # -- keeping -----------------------------------------------------------

    def to_json(self) -> dict:
        return {"tables": [[s, t, now] for (s, t), now in self._tables.items()],
                "columns": [[s, t, c, now] for (s, t, c), now in self._columns.items()]}

    @classmethod
    def from_json(cls, data: dict | None) -> "Lineage":
        lineage = cls()
        for s, t, now in (data or {}).get("tables", []):
            lineage._tables[(s, t)] = now
        for s, t, c, now in (data or {}).get("columns", []):
            lineage._columns[(s, t, c)] = now
        return lineage

# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section
# whenever something genuinely open, deferred, or rejected comes up here.
# =============================================================================
#
# RESOLVED (20 October, review): a table or column added later under a name
# a pack name had given up was taken for the pack's. _pack_table and
# _pack_column now answer None for such a name; tests/test_lineage.py.
#
# DELIBERATE: the oracle (oracle.py) still reads the pack's names, so a
# watched column that is renamed reads as gone. It is the yardstick for what
# a consumer should see, and translating it would hide the very change it is
# there to notice.
#
# DELIBERATE: a pack migration that drops a column its own events write is
# followed, not fatal. It used to crash the world (tests/test_migrations.py
# says why that changed). Making a broken migration crash the application,
# as an uncoordinated real one does, could be a per-pack option in step 2.
