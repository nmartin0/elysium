"""
ontology_adapter.py  (acme_corp-specific -- NOT portable to other orgs)

Knows things that only apply to acme_corp: that customer data lives in
SQLite, the exact table/column names, and that "region" is the attribute
used for fine-grained access scoping. Uses the generic connectors/
driver to actually talk to the database -- this file adds the org
knowledge on top of it.

Also owns ACTIONS: the map of action_id -> function, handed to
core/intermediate_layer/action_registry.py at request time. Which
actions exist at all is itself an acme_corp-specific fact.

Called by: core/intermediate_layer/action_registry.py (via test_run.py,
           passed in as the `actions` argument)
"""

from pathlib import Path

from connectors.sqlite_connector import connect, run_query, run_query_one

DB_PATH = Path(__file__).resolve().parent / "dev_fixtures" / "mediator.db"


def get_customer_transactions(requesting_user_region: str, customer_id: str) -> list[dict]:
    conn = connect(DB_PATH)
    try:
        customer = run_query_one(
            conn,
            "SELECT customer_id, region FROM customers WHERE customer_id = ?",
            (customer_id,),
        )

        if customer is None:
            return []

        if customer["region"] != requesting_user_region:
            return []

        return run_query(
            conn,
            "SELECT transaction_id, customer_id, amount, currency, "
            "category, transaction_date FROM transactions WHERE customer_id = ?",
            (customer_id,),
        )
    finally:
        conn.close()


ACTIONS = {
    "get_customer_transactions": get_customer_transactions,
}
