"""
test_run.py  (wires everything together, end to end -- for acme_corp)

Uses the MOCK router_prompt.py and synthesis_prompt.py -- no API key
required. `users` and `actions` are acme_corp's own data, passed
explicitly into the generic gateway -- nothing in core/ knows this
deployment exists.

Run from the project root:
    python3 -m deployments.acme_corp.test_run
"""

import uuid

from core.intermediate_layer.gateway import handle_request
from core.llm.router_prompt import route_query
from core.llm.synthesis_prompt import synthesize_insight

from deployments.acme_corp.policy import USERS
from deployments.acme_corp.ontology_adapter import ACTIONS


def run_example(user_id: str, query_text: str) -> None:
    print(f"--- {query_text!r} (as {user_id}) ---")

    action = route_query(user_id, query_text)
    if action["action_id"] is None:
        print("No matching action found for this query.\n")
        return

    request_id = str(uuid.uuid4())
    result = handle_request(
        USERS, ACTIONS, request_id, user_id, query_text,
        action["action_id"], action["params"],
    )

    if result["status"] != "success":
        print(f"Request {result['status']}. No data to synthesize.\n")
        return

    insight = synthesize_insight(query_text, result["records"])
    print(insight)
    print()


if __name__ == "__main__":
    run_example("user_alice", "What are cust_001's recent transactions?")
    run_example("user_alice", "What are cust_003's recent transactions?")
    run_example("user_carol", "What are cust_004's recent transactions?")
