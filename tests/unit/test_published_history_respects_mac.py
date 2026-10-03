"""
The published-history route answers only what the caller may already
see.

THE RULE IS NOT NEW, and that is the point. `edit_history` settled it
from Foundry's precedent -- "users who have access to the current
state of an object can access the entire history of the object" -- so
authorization is the SAME check as reading the object. No separate
grant, and no way to learn about an object's past that you could not
learn about its present.

WHY PER-FIELD FILTERING IS THE WHOLE JOB HERE. A gold-history entry
carries the ROW AS IT STOOD, every column of it. That is strictly more
than `edit_history` carries, which holds only what changed. So a
history entry can expose a field the caller may never read, and can
expose a PAST value of a field whose present value they can read.
Filtering per object would leak both.

AN ENTRY WITH EVERY FIELD REMOVED IS STILL RETURNED. The FACT that
this object changed at that time is what a history is for, and it is
information the caller already has by being allowed to read the
object at all.

WHERE THE SPLIT IS, and why. `core/ontology` may not import
`core/mirror` -- the import contract says so, and the first version of
this broke it. The route reads the lake; the mediator decides access.
Putting the filter in the route would have put access control in two
places, which is what `edit_history` refused.
"""

import pytest


@pytest.fixture
def entries():
    return [
        {"change": "UPDATE", "changed_at": "2026-09-02T00:00:00Z",
         "publication": "s2",
         "values": {"customer_id": "c1", "name": "Ada",
                     "email": "ada@example.com", "region": "us-west"}},
        {"change": "INSERT", "changed_at": "2026-09-01T00:00:00Z",
         "publication": "s1",
         "values": {"customer_id": "c1", "name": "Ada",
                     "email": "ada@example.com", "region": "us-west"}},
    ]


class TestTheContractItKeeps:
    def test_the_mediator_owns_the_filtering(self):
        """A route that filtered would be a second place deciding one
        question."""
        from core.ontology.mediator import DataMediator

        assert hasattr(DataMediator, "filter_published_history")

    def test_it_takes_entries_rather_than_reading_them(self):
        """`core/ontology` may not import `core/mirror`. The first
        version did and broke the import contract -- 15 kept, 1
        broken."""
        import inspect

        from core.ontology.mediator import DataMediator

        signature = inspect.signature(DataMediator.filter_published_history)

        assert "entries" in signature.parameters

    def test_the_ontology_layer_does_not_import_the_mirror(self):
        from pathlib import Path

        source = Path("core/ontology/mediator.py").read_text()
        body = source[source.index("def filter_published_history"):]
        body = body[:body.index("\n    def ", 10)]

        # THE IMPORT, not the word: the docstring names gold_history
        # to explain why it is absent, which a substring check cannot
        # tell from the thing it forbids.
        imports = [line for line in body.splitlines()
                   if line.strip().startswith(("import ", "from "))]

        assert not [line for line in imports if "core.mirror" in line], imports


class TestWhatTheRouteDoes:
    def test_it_reads_then_delegates(self):
        from pathlib import Path

        source = Path("api/routes.py").read_text()
        body = source[source.index("def published_history_route"):]
        body = body[:body.index("\n@router", 10)]

        assert "read_history(" in body
        assert "filter_published_history(" in body

    def test_a_missing_history_table_is_an_empty_list_not_an_error(self):
        """Ordinary, and indistinguishable from denial by design -- the
        response must never tell the two apart."""
        from pathlib import Path

        source = Path("api/routes.py").read_text()
        body = source[source.index("def published_history_route"):]
        body = body[:body.index("\n@router", 10)]
        after = body[body.index("except HistoryNotRecorded"):]

        assert "return []" in after[:300]

    def test_the_limit_is_capped_by_the_page_size(self):
        """A caller asking for everything gets a page."""
        from pathlib import Path

        source = Path("api/routes.py").read_text()
        body = source[source.index("def published_history_route"):]
        body = body[:body.index("\n@router", 10)]

        assert "MAX_PAGE_SIZE" in body


class TestTheFilteringItself:
    """The behaviour, against a real mediator rather than its source."""

    @pytest.fixture
    def mediator(self, tmp_path, isolated_audit_log):
        import sqlite3

        from core.deployment_loader import (
            _READ_ADAPTER_REGISTRY,
            _build_adapters,
        )
        from core.intermediate_layer.audit import AuditLog
        from core.ontology.mediator import DataMediator
        from core.ontology.write_log import WriteLogWriter

        schema = {
            "Customer": {
                "id_field": "customer_id",
                "security": {"field": "region"},
                "storage": {"silo": "p", "table": "customers",
                             "id_column": "customer_id"},
                "fields": {
                    "customer_id": {"data_type": "string"},
                    "name": {"data_type": "string"},
                    "email": {"data_type": "string"},
                    "region": {"data_type": "string"},
                },
            },
        }
        roles = {
            "full": {"allowed_actions": [
                "read:Customer", "read:Customer.customer_id",
                "read:Customer.name", "read:Customer.email",
                "read:Customer.region"]},
            "partial": {"allowed_actions": [
                "read:Customer", "read:Customer.customer_id",
                "read:Customer.name", "read:Customer.region"]},
            "none": {"allowed_actions": []},
        }
        database = tmp_path / "p.db"
        conn = sqlite3.connect(database)
        conn.executescript(
            "CREATE TABLE customers (customer_id TEXT PRIMARY KEY, "
            "name TEXT, email TEXT, region TEXT);"
            "INSERT INTO customers VALUES "
            "('c1', 'Ada', 'ada@example.com', 'us-west');")
        conn.commit()
        conn.close()
        adapters = _build_adapters(
            {"p": {"adapter": "sqlite", "connection": {"path": str(database)}}},
            _READ_ADAPTER_REGISTRY,
        )
        return DataMediator(
            schema, adapters, {"Customer": "p"}, roles,
            write_log=WriteLogWriter(tmp_path / "wl.db"),
            audit_log=AuditLog(isolated_audit_log / "audit.log"))

    @staticmethod
    def _user(role):
        from core.intermediate_layer.auth import UserRecord

        # A REAL MAC VALUE, because check_access denies outright when
        # `security_value is None` -- the first version of this fixture
        # passed None and every test saw an empty list, which looked
        # like the filter working and was the fixture failing.
        return UserRecord(f"u_{role}", "us-west", role)

    def test_a_caller_with_every_grant_sees_every_field(self, mediator,
                                                         entries):
        out = mediator.filter_published_history(
            self._user("full"), "Customer", "c1", entries)

        assert len(out) == 2
        assert out[0]["values"]["email"] == "ada@example.com"

    def test_a_field_they_cannot_read_is_removed(self, mediator, entries):
        """THE CASE THIS EXISTS FOR. A history entry carries the whole
        row, so filtering per object would hand over the email address
        merely because it changed."""
        out = mediator.filter_published_history(
            self._user("partial"), "Customer", "c1", entries)

        assert len(out) == 2
        assert "email" not in out[0]["values"]
        assert out[0]["values"]["name"] == "Ada"

    def test_the_fact_of_the_change_survives_the_filtering(self, mediator,
                                                            entries):
        """An entry with every field removed is still returned: the FACT
        that this object changed at that time is what a history is
        for."""
        out = mediator.filter_published_history(
            self._user("partial"), "Customer", "c1", entries)

        assert [e["change"] for e in out] == ["UPDATE", "INSERT"]
        assert [e["changed_at"] for e in out] == [
            "2026-09-02T00:00:00Z", "2026-09-01T00:00:00Z"]

    def test_a_caller_who_cannot_read_the_object_gets_nothing(self, mediator,
                                                               entries):
        """Uniform denial: never distinguishable from 'no history'."""
        assert mediator.filter_published_history(
            self._user("none"), "Customer", "c1", entries) == []
