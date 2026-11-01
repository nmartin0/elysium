"""What blocks a removal and what it leaves behind (core/ontology/removal.py).

The blockers are the Used by report plus the pending writes the report cannot
see; the report itself is tested in test_used_by.py, and its completeness
against the loader in test_used_by_is_complete.py.
"""

from core.ontology.removal import (
    PENDING_WRITE,
    applied_writes,
    field_blockers,
    link_blockers,
    link_ends,
    stored_data,
    visible_to,
)
from core.ontology.used_by import Referrer, used_by_field, used_by_link
from tests.unit import test_used_by as built


class Log:
    """Stands in for the write log's one question."""

    def __init__(self, **counts):
        self.counts = counts
        self.asked = []

    def edits_touching_field(self, object_type, field):
        self.asked.append((object_type, field))
        return self.counts.get(f"{object_type}.{field}", {"applied": 0, "pending": 0})


def blockers(log, field="price"):
    return field_blockers(built._schema(), built.ROLES, built.ACTIONS, [], log, "Order", field)


def test_the_blockers_are_the_used_by_rows_and_nothing_else_when_no_write_waits():
    reported = used_by_field(built._schema(), built.ROLES, built.ACTIONS, [], "Order", "price")

    assert blockers(Log()) == reported


def test_a_proposed_write_is_a_blocker_and_an_applied_one_is_not():
    found = blockers(Log(**{"Order.price": {"applied": 3, "pending": 2}}))

    waiting = [item for item in found if item.kind == PENDING_WRITE]
    assert [(item.place, "2 proposed" in item.says) for item in waiting] == [("Order.price", True)]
    assert applied_writes(Log(**{"Order.price": {"applied": 3, "pending": 2}}), [("Order", "price")]) == 3


def test_without_a_write_log_it_cannot_be_told_and_that_blocks():
    found = blockers(None, "mood")

    assert [(item.kind, item.place) for item in found] == [(PENDING_WRITE, "write log")]
    assert "cannot be asked" in found[0].says
    assert applied_writes(None, [("Order", "mood")]) == 0


def test_a_link_asks_the_write_log_about_both_of_its_ends():
    log = Log()

    link_blockers(built._schema(), {}, {}, [], log, "OrderLines")

    assert sorted(log.asked) == [("Line", "order"), ("Order", "lines")]


def test_a_link_lists_what_names_either_end_and_a_write_waiting_on_one():
    log = Log(**{"Line.order": {"applied": 0, "pending": 1}})

    found = link_blockers(built._schema(), {}, {}, [], log, "OrderLines")

    reported = used_by_link(built._schema(), {}, {}, [], "OrderLines")
    assert found[:len(reported)] == reported
    assert [item.place for item in found if item.kind == PENDING_WRITE] == ["Line.order"]
    assert link_ends(built._schema(), "OrderLines") == [("Order", "lines"), ("Line", "order")]


class TestWhatThePersonMaySee:
    ROWS = [Referrer("a", "plain", "names nothing else"),
            Referrer("b", "one", "names Line", ("Line",)),
            Referrer("c", "two", "names Order.cost and Line", ("Order.cost", "Line"))]

    def test_a_row_is_shown_when_every_name_it_carries_is_known(self):
        shown, hidden = visible_to(self.ROWS, lambda subject: True)

        assert shown == self.ROWS and hidden == 0

    def test_a_row_naming_one_unknown_name_is_counted_and_not_shown(self):
        shown, hidden = visible_to(self.ROWS, lambda subject: subject != "Order.cost")

        assert [item.place for item in shown] == ["plain", "one"] and hidden == 1

    def test_a_row_naming_nothing_is_always_shown(self):
        shown, hidden = visible_to(self.ROWS, lambda subject: False)

        assert [item.place for item in shown] == ["plain"] and hidden == 2


class TestWhatItLeavesBehind:
    def test_a_field_says_source_silver_bronze_gold_and_that_nothing_serves_it(self):
        text = " ".join(stored_data("field", None, 0))

        for word in ("source", "Silver", "Bronze", "Gold", "Nothing serves"):
            assert word in text

    def test_a_join_table_is_described_as_one_and_not_as_a_column(self):
        text = " ".join(stored_data("link", "many_to_many", 0))

        assert "join table" in text and "Silver keeps the column" not in text

    def test_a_foreign_key_link_goes_the_way_a_field_does(self):
        text = " ".join(stored_data("link", None, 0))

        assert "foreign key column" in text and "Silver keeps the column" in text

    def test_applied_edits_are_counted_only_when_there_are_some(self):
        assert not any("already applied" in line for line in stored_data("field", None, 0))
        assert "4 edit(s) already applied" in stored_data("field", None, 4)[-1]
