"""What blocks a removal and what it leaves behind (core/ontology/removal.py).

The blockers are the Used by report plus the pending writes the report cannot
see; the report itself is tested in test_used_by.py, and its completeness
against the loader in test_used_by_is_complete.py.
"""

from core.mirror.incremental import incremental_tables_only_read_by
from core.ontology.removal import (
    PENDING_WRITE,
    applied_writes,
    field_blockers,
    link_blockers,
    link_ends,
    stored_data,
    type_blockers,
    visible_to,
)
from core.ontology.used_by import Referrer, used_by_field, used_by_link, used_by_type
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


class TestWhatBlocksAWholeType:
    """removal.type_blockers: the Used by report for the type, plus functions,
    an incremental declaration for its only table, and pending writes on any
    of its fields."""

    def _blockers(self, log=None, object_type="Order", **given):
        return type_blockers(built._schema(), built.ROLES, built.ACTIONS, [], Log() if log is None else log,
                             object_type, **given)

    def test_it_starts_from_the_used_by_report_for_the_type(self):
        reported = used_by_type(built._schema(), built.ROLES, built.ACTIONS, [], "Order")

        assert [row.as_dict() for row in self._blockers()][:len(reported)] == [row.as_dict() for row in reported]

    def test_a_pending_write_on_any_field_of_the_type_blocks(self):
        schema = built._schema()
        field = next(iter(schema["Order"]["fields"]))

        found = self._blockers(Log(**{f"Order.{field}": {"applied": 0, "pending": 2}}))

        waiting = [(row.kind, row.place) for row in found if row.kind == PENDING_WRITE]
        assert waiting == [(PENDING_WRITE, f"Order.{field}")]

    def test_without_a_write_log_it_cannot_be_told_and_that_blocks(self):
        found = type_blockers(built._schema(), built.ROLES, built.ACTIONS, [], None, "Order")

        assert any(row.kind == PENDING_WRITE for row in found)

    def test_a_function_declaring_it_reads_the_type_blocks(self):
        class Reads:
            name = "forecast"
            reads_object_types = ["Order"]

        class Elsewhere:
            name = "other"
            reads_object_types = ["Customer"]

        found = self._blockers(functions=[Reads(), Elsewhere()])

        assert [(row.kind, row.place) for row in found if row.kind == "function"] == [("function", "function forecast")]

    def test_the_types_own_fields_are_not_hidden_from_the_person_asking(self):
        schema = built._schema()
        own = {f"Order.{name}" for name in schema["Order"]["fields"]}

        found = self._blockers()

        assert not own & {subject for row in found for subject in row.subjects}

    def test_an_incremental_declaration_for_the_only_table_that_reads_it_blocks(self):
        schema = built._schema()
        schema["Order"]["storage"] = {"silo": "main", "table": "orders", "id_column": "order_id"}
        schema["Line"]["storage"] = {"silo": "main", "table": "lines", "id_column": "line_id"}
        storage = schema["Order"]["storage"]
        silos = {storage["silo"]: {"incremental": {storage["table"]: {"cursor": "updated_at"}}}}

        only = incremental_tables_only_read_by(schema, silos, "Order")
        found = type_blockers(schema, built.ROLES, built.ACTIONS, [], Log(), "Order", incremental=only)

        assert only == [(storage["silo"], storage["table"])]
        assert [(row.kind, row.place) for row in found if row.kind == "silo"] == [
            ("silo", f"data silo {storage['silo']}, incremental")]

    def test_a_table_another_type_still_reads_does_not_block(self):
        schema = built._schema()
        schema["Order"]["storage"] = {"silo": "main", "table": "orders", "id_column": "order_id"}
        schema["Line"]["storage"] = {"silo": "main", "table": "lines", "id_column": "line_id"}
        storage = schema["Order"]["storage"]
        silos = {storage["silo"]: {"incremental": {storage["table"]: {"cursor": "updated_at"}}}}
        schema["Twin"] = {**schema["Order"], "fields": dict(schema["Order"]["fields"])}

        assert incremental_tables_only_read_by(schema, silos, "Order") == []


class TestWhatATypeLeavesBehind:
    def test_it_says_source_untouched_the_tables_stay_and_nothing_serves_it(self):
        text = " ".join(stored_data("type", None, 0))

        for words in ("Nothing is deleted from your source", "exactly as they were", "history",
                      "rebuild", "Nothing serves the type", "erasure request still reaches",
                      "no sync can change that", "partly known", "marks the erasure incomplete",
                      "--adopt", "Adopt such tables before erasing",
                      "--adopt-all-current", "refuses to run",
                      "reads the same source table"):
            assert words in text

    def test_it_does_not_claim_a_column_is_emptied(self):
        assert "Silver keeps the column" not in " ".join(stored_data("type", None, 0))

    def test_applied_edits_are_counted_only_when_there_are_some(self):
        assert not any("already applied" in line for line in stored_data("type", None, 0))
        assert "3 edit(s) already applied" in stored_data("type", None, 3)[-1]
