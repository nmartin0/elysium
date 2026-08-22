import json
import requests

SYSTEM_PROMPT = """You translate user requests into a single JSON action.

The ONLY action available is:
  action_id: "get_customer_transactions"
  params: {"customer_id": "<a string like cust_001>"}

Respond with ONLY a JSON object, no other text, in this exact shape:
  {"action_id": "get_customer_transactions", "params": {"customer_id": "cust_001"}}

If the request doesn't match this action, respond with:
  {"action_id": null, "params": {}}
"""


def ask(query_text: str) -> None:
    response = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "qwen2.5:3b",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": query_text},
            ],
            "format": "json",  # tells Ollama to constrain output to valid JSON
            "stream": False,
        },
    )
    response.raise_for_status()
    raw_content = response.json()["message"]["content"]

    print(f"Query: {query_text!r}")
    print(f"Raw model output: {raw_content}")
    parsed = json.loads(raw_content)  # will raise if it's not valid JSON at all
    print(f"Parsed: {parsed}")
    print()


if __name__ == "__main__":
    ask("What are cust_001's recent transactions?")
    ask("Show me everything for customer cust_007")
    ask("What's the weather like today?")  # should NOT match our one action
