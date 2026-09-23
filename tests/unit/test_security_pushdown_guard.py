"""
What the MAC pushdown refuses TODAY, pinned before gold moves it.

WHY THIS FILE EXISTS, AND WHY IT COMES FIRST. GOLD-3 re-keys
_pushable_security_column, whose guard currently reads "same adapter
AND same storage block". On gold every object type is one table in one
namespace, so that comparison stops distinguishing anything -- and it
does not fail loudly when it stops.

WHAT IT ACTUALLY BREAKS, MEASURED RATHER THAN ASSUMED. The control for
these tests (remove the guard, run them) showed the failure is NOT a
widening, which is what OPEN_RISKS.md first recorded. check_access()
runs per candidate id unconditionally after the read, so MAC is
enforced whatever the pushdown does. The pushdown exists to make the
database return only permitted rows, which is what makes a LIMIT
correct rather than a guess.

So a lost guard pushes a column name into a table that may hold a
different column of the same name, and the query silently DROPS rows
the user is entitled to -- a silent DENIAL, not a silent grant. The
control proved it: with the guard gone, a us-east user searching by a
support field got [] instead of their own customer.

That is still a real fault, and a nastier one to notice than an
exception: nobody reports the rows they never saw.

THE TESTS ARE STATED IN ROWS wherever possible, so they survive any
re-keying of the guard -- including gold's.
"""

import sqlite3

import pytest

from core.deployment_loader import _WRITE_ADAPTER_REGISTRY, _build_adapters
from core.filters import as_equality_conditions
from core.intermediate_layer.audit import AuditLog
from core.intermediate_layer.auth import UserRecord
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLogWriter

# Customer spans two storages IN THE SAME SILO. Its security field
# lives in the primary one; `region` ALSO exists in the second table,
# meaning something else entirely -- a service region, not a customer's.
SCHEMA = {
    "Customer": {
        "id_field": "customer_id",
        "security": {"field": "region"},
        "storage": {
            "silo": "primary_sql",
            "table": "customers",
            "id_column": "customer_id",
        },
        "additional_storage": {
            "support": {
                "silo": "primary_sql",
                "table": "support_cases",
                "id_column": "cust_ref",
            },
        },
        "fields": {
            "customer_id": {"type": "data"},
            "region": {"type": "data"},
            "name": {"type": "data"},
            # Same NAME in the other table, different MEANING.
            "case_region": {"type": "data", "storage": "support",
                             "column": "region"},
            "case_status": {"type": "data", "storage": "support",
                             "column": "status"},
        },
    },
}

ROLES = {
    "analyst": {
        "allowed_actions": [
            "read:Customer", "read:Customer.customer_id", "read:Customer.region",
            "read:Customer.name", "read:Customer.case_region",
            "read:Customer.case_status",
        ],
    },
}

WEST = UserRecord("user_west", "us-west", "analyst")


@pytest.fixture
def mediator(tmp_path, isolated_audit_log):
    database = tmp_path / "primary.db"
    conn = sqlite3.connect(database)
    conn.executescript("""
        CREATE TABLE customers (customer_id TEXT PRIMARY KEY, region TEXT, name TEXT);
        INSERT INTO customers VALUES ('cust_001', 'us-west', 'Ada Okafor');
        INSERT INTO customers VALUES ('cust_002', 'us-east', 'Ben Carter');
        INSERT INTO customers VALUES ('cust_003', 'eu-west', 'Cleo Nkemdirim');

        -- `region` here is the SUPPORT region, not the customer's, and
        -- cust_002's is 'us-west' while the customer is 'us-east'.
        CREATE TABLE support_cases (cust_ref TEXT PRIMARY KEY, region TEXT, status TEXT);
        INSERT INTO support_cases VALUES ('cust_001', 'us-west', 'open');
        INSERT INTO support_cases VALUES ('cust_002', 'us-west', 'open');
        INSERT INTO support_cases VALUES ('cust_003', 'us-west', 'closed');
    """)
    conn.commit()
    conn.close()
    adapters = _build_adapters(
        {"primary_sql": {"adapter": "sqlite", "connection": {"path": database}}},
        _WRITE_ADAPTER_REGISTRY,
    )
    return DataMediator(SCHEMA, adapters, {"Customer": "primary_sql"}, ROLES,
                         write_log=WriteLogWriter(tmp_path / "write_log.db"),
                         audit_log=AuditLog(isolated_audit_log / "audit.log"))


def _pushed(mediator, storage_name=None):
    """The column the MAC filter would become for one storage, or None."""
    adapter, config = mediator._resolve_shared_storage(
        "Customer", ["case_status"] if storage_name == "support" else ["name"],
    )
    return mediator._pushable_security_column("Customer", adapter, config)


class TestWhatIsPushedAndWhatIsNot:
    def test_the_security_field_is_pushed_for_its_own_table(self, mediator):
        """`region` lives in `customers`, so `WHERE region = ?` says the
        whole rule and a LIMIT after it is correct."""
        assert _pushed(mediator) == "region"

    def test_it_is_REFUSED_for_a_different_table_in_the_same_silo(self, mediator):
        """THE GUARD UNDER TEST. Same adapter, different storage block:
        `region` exists in support_cases too, and means something else."""
        assert _pushed(mediator, "support") is None


class TestTheRowsAreRightEitherWay:
    """A refused pushdown falls back to a RESIDUAL filter, not to no
    filter. These tests are stated in rows, so they survive any
    re-keying of the guard -- including gold's."""

    def test_searching_by_a_primary_field_sees_only_its_own_region(self, mediator):
        found = mediator.search_object(
            WEST, "Customer", as_equality_conditions({"name": "Ada Okafor"}),
        )

        assert found == ["cust_001"]

    def test_a_customer_in_another_region_is_not_returned(self, mediator):
        found = mediator.search_object(
            WEST, "Customer", as_equality_conditions({"name": "Ben Carter"}),
        )

        assert found == []

    def test_a_same_named_column_in_another_table(self, mediator):
        """THE DANGEROUS CASE, and the reason this file exists.

        Every support case has region 'us-west'. A us-west user
        searching support_cases must still see ONLY cust_001, because
        MAC is about the CUSTOMER's region -- which lives in the other
        table. If the guard is ever lost, the filter is pushed onto
        support_cases.region, every row matches, and this returns three
        customers instead of one: a SILENT WIDENING, visible here as a
        wrong row set rather than an exception.
        """
        found = mediator.search_object(
            WEST, "Customer", as_equality_conditions({"case_status": "open"}),
        )

        assert found == ["cust_001"]

    def test_and_the_closed_case_in_another_region_stays_hidden(self, mediator):
        found = mediator.search_object(
            WEST, "Customer", as_equality_conditions({"case_status": "closed"}),
        )

        assert found == []

    def test_a_user_of_another_region_sees_their_own(self, mediator):
        east = UserRecord("user_east", "us-east", "analyst")

        found = east_found = mediator.search_object(
            east, "Customer", as_equality_conditions({"case_status": "open"}),
        )

        assert east_found == ["cust_002"] and found == ["cust_002"]

    def test_a_user_with_no_security_value_sees_nothing(self, mediator):
        nobody = UserRecord("user_none", None, "analyst")

        found = mediator.search_object(
            nobody, "Customer", as_equality_conditions({"case_status": "open"}),
        )

        assert found == []
