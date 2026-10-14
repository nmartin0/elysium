"""
One reader of a link's route (F-07), and the drift it removed.

Five adapter methods read via_table / via_column / via_target_column
themselves. The mirror's single reverse-link read had dropped
via_target_column, so a many-to-many link asked its join table for the
target type's id column -- which a join table does not have -- while
the batch read on the same adapter honoured it.
"""

import pyarrow as pa

from core.mirror.mirror_adapter import MirrorReadAdapter
from core.ontology.bindings import link_route

MANY_TO_MANY = {"type": "link", "target": "Tag", "cardinality": "many",
                "via_table": "customer_tags", "via_column": "customer_id",
                "via_target_column": "tag_ref"}
FOREIGN_KEY = {"type": "link", "target": "Transaction", "cardinality": "many",
               "via_table": "transactions", "via_column": "customer_id"}


def test_a_join_table_route_returns_its_own_target_column():
    route = link_route(MANY_TO_MANY, "tag_id")

    assert (route.table, route.column, route.result_column) == (
        "customer_tags", "customer_id", "tag_ref")


def test_a_foreign_key_route_returns_the_target_id():
    assert link_route(FOREIGN_KEY, "transaction_id").result_column == "transaction_id"


class _Reader:
    """Stands in for the mirror's scan: a join table with tag_ref, and
    no tag_id column at all -- as a real one has."""

    def __init__(self):
        self.asked_for = None

    def _scan(self, table, selected_fields=(), row_filter=None):
        self.asked_for = selected_fields
        data = {"customer_id": ["c1", "c1"], "tag_ref": ["t1", "t2"]}
        return pa.table({name: data[name] for name in selected_fields})


def test_the_mirror_single_reverse_read_follows_the_join_table():
    adapter = MirrorReadAdapter.__new__(MirrorReadAdapter)
    adapter._reader = _Reader()

    found = adapter.resolve_reverse_link("c1", MANY_TO_MANY, "tag_id")

    assert adapter._reader.asked_for == ("tag_ref",)
    assert found == ["t1", "t2"]
