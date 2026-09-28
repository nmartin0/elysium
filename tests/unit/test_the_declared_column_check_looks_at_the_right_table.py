"""
The declared-column check looks at the table the type declares
(PA001-A18).

TWO FAULTS, both measured on deployments that are doing nothing wrong.

BY TABLE NAME ALONE. The match compared the bare name --
`name.split(".", 1)[1] == table_name` -- so two silos each holding a
table called `customers` both matched, and `matching[0]` took
whichever sorted first. A type declaring silo `q` was checked against
`p.customers` and reported a column missing from a table it does not
use. `customers` is not an unusual name for two databases to share.

THE PRIMARY TABLE ONLY. A fused type keeps some fields in another silo
entirely -- that is what `additional_storage` is for -- and every
field was checked against the primary table. So a healthy fused
deployment reported

    Customer.score: declared but column 'score' is missing from
    p.customers

for a column sitting exactly where the ontology says it should be, in
q.risk.

THIS IS PA001-I1 ONE FUNCTION ALONG, and the same reasoning applies:
"a check that always reports problems on a healthy deployment trains
operators to ignore it". I1 was the gold tables; this is fused types
and any deployment whose silos share a table name.

WHAT IS DELIBERATELY UNCHANGED: a column that is genuinely absent is
still reported, and now names the table it is genuinely absent from.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.integrity import check_mirror


def _silo(path, ddl, row):
    conn = sqlite3.connect(path)
    conn.execute(ddl)
    conn.execute(row)
    conn.commit()
    conn.close()
    return SQLiteReadAdapter({"path": path})


class TestAFusedType:
    @pytest.fixture
    def fused(self, tmp_path):
        adapters = {
            "p": _silo(tmp_path / "a.db",
                        "CREATE TABLE customers (id TEXT PRIMARY KEY, name TEXT, "
                        "region TEXT)",
                        "INSERT INTO customers VALUES ('c1','Ada','us-west')"),
            "q": _silo(tmp_path / "b.db",
                        "CREATE TABLE risk (id TEXT PRIMARY KEY, score TEXT)",
                        "INSERT INTO risk VALUES ('c1','0.4')"),
        }
        sync = IcebergMirrorSync(tmp_path / "m", adapters)
        sync.sync_table("p", "customers", "id", ["id", "name", "region"], {})
        sync.sync_table("q", "risk", "id", ["id", "score"], {})
        schema = {"Customer": {
            "id_field": "id", "security": {"field": "region"},
            "storage": {"silo": "p", "table": "customers", "id_column": "id"},
            "additional_storage": {"risk": {"silo": "q", "table": "risk",
                                             "id_column": "id"}},
            "fields": {"id": {"type": "data"}, "name": {"type": "data"},
                        "region": {"type": "data"},
                        "score": {"type": "data", "storage": "risk"}}}}
        return sync, schema

    def test_a_healthy_one_reports_nothing(self, fused):
        """THE REGRESSION TEST. `score` lives in q.risk, exactly where
        the ontology says."""
        sync, schema = fused

        assert check_mirror(sync.catalog, schema).problems == []

    def test_a_column_missing_from_the_ADDITIONAL_table_is_caught(self, fused):
        """The other direction: checking the right table means faults
        there are found too, which the old code could not do at all."""
        sync, schema = fused
        schema["Customer"]["fields"]["ghost"] = {"type": "data",
                                                  "storage": "risk"}

        problems = check_mirror(sync.catalog, schema).problems

        assert any("ghost" in p and "q.risk" in p for p in problems)


class TestTwoSilosSharingATableName:
    @pytest.fixture
    def collision(self, tmp_path):
        adapters = {
            "p": _silo(tmp_path / "a.db",
                        "CREATE TABLE customers (id TEXT PRIMARY KEY, name TEXT, "
                        "region TEXT)",
                        "INSERT INTO customers VALUES ('c1','Ada','us-west')"),
            "q": _silo(tmp_path / "b.db",
                        "CREATE TABLE customers (id TEXT PRIMARY KEY, other TEXT)",
                        "INSERT INTO customers VALUES ('x','y')"),
        }
        sync = IcebergMirrorSync(tmp_path / "m", adapters)
        sync.sync_table("p", "customers", "id", ["id", "name", "region"], {})
        sync.sync_table("q", "customers", "id", ["id", "other"], {})
        schema = {"Customer": {
            "id_field": "id", "security": {"field": "other"},
            "storage": {"silo": "q", "table": "customers", "id_column": "id"},
            "fields": {"id": {"type": "data"}, "other": {"type": "data"}}}}
        return sync, schema

    def test_the_declared_silo_is_the_one_checked(self, collision):
        """THE REGRESSION TEST. `other` exists in q.customers; the
        check was reading p.customers."""
        sync, schema = collision

        assert check_mirror(sync.catalog, schema).problems == []

    def test_a_real_fault_names_the_declared_table(self, collision):
        """Not just that it is caught -- that the message points at
        the table the operator has to look in."""
        sync, schema = collision
        schema["Customer"]["fields"]["ghost"] = {"type": "data"}

        problems = check_mirror(sync.catalog, schema).problems

        assert any("q.customers" in p for p in problems)
        assert not any("p.customers" in p for p in problems)


class TestATableThatIsNotThere:
    def test_it_is_still_reported(self, tmp_path):
        """The check's original purpose, kept."""
        adapters = {"p": _silo(tmp_path / "a.db",
                                "CREATE TABLE other (id TEXT PRIMARY KEY)",
                                "INSERT INTO other VALUES ('x')")}
        sync = IcebergMirrorSync(tmp_path / "m", adapters)
        sync.sync_table("p", "other", "id", ["id"], {})
        schema = {"Customer": {
            "id_field": "id", "security": {"field": "region"},
            "storage": {"silo": "p", "table": "absent", "id_column": "id"},
            "fields": {"id": {"type": "data"}}}}

        problems = check_mirror(sync.catalog, schema).problems

        assert any("absent" in p and "not in the mirror" in p for p in problems)
