"""The record of what the pack's names are called now (simulator/lineage.py).

Pure bookkeeping, so tested without a database. The changes are given in
current names, as they are applied.
"""

from simulator.drift import DropColumn, DropTable, RenameColumn, RenameTable
from simulator.lineage import Lineage


def test_a_chain_of_renames_resolves_to_the_last_name():
    lineage = Lineage()
    lineage.record("s", RenameColumn("t", "a", "b"))
    lineage.record("s", RenameColumn("t", "b", "c"))

    assert lineage.column("s", "t", "a") == "c"
    assert lineage.to_original("s", "t", {"c": 1}) == {"a": 1}


def test_a_rename_then_a_drop_is_a_drop():
    lineage = Lineage()
    lineage.record("s", RenameColumn("t", "a", "b"))
    lineage.record("s", DropColumn("t", "b"))

    assert lineage.column("s", "t", "a") is None
    assert lineage.to_current("s", "t", {"a": 1, "z": 2}) == {"z": 2}


def test_columns_follow_their_table_through_a_rename():
    lineage = Lineage()
    lineage.record("s", RenameTable("t", "u"))
    lineage.record("s", RenameColumn("u", "a", "b"))

    assert lineage.table("s", "t") == "u"
    assert lineage.column("s", "t", "a") == "b"


def test_a_new_table_wearing_an_old_name_is_not_the_packs():
    # Rename t to u, then something else is created as t and changed.
    lineage = Lineage()
    lineage.record("s", RenameTable("t", "u"))
    lineage.record("s", RenameColumn("t", "x", "y"))      # the newcomer's column
    lineage.record("s", DropTable("t"))                   # the newcomer dropped

    assert lineage.table("s", "t") == "u"
    assert lineage.column("s", "t", "x") == "x"


def test_a_new_column_wearing_an_old_name_is_not_the_packs():
    lineage = Lineage()
    lineage.record("s", RenameColumn("t", "a", "b"))
    # A new column `a` appears; its value must not be read as the pack's a.
    assert lineage.to_original("s", "t", {"b": 1, "a": 2}) == {"a": 1}
    lineage.record("s", DropColumn("t", "a"))             # the newcomer dropped

    assert lineage.column("s", "t", "a") == "b"


def test_it_survives_being_written_down():
    lineage = Lineage()
    lineage.record("s", RenameTable("t", "u"))
    lineage.record("s", DropColumn("u", "a"))

    again = Lineage.from_json(lineage.to_json())

    assert again.table("s", "t") == "u" and again.column("s", "t", "a") is None
