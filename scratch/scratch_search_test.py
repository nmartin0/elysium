from deployments.acme_corp.ontology_adapter import search_object

print("--- Transaction search by customer_id, same region (should find both) ---")
print(search_object("us-west", "Transaction", {"customer_id": "cust_001"}))

print("--- Transaction search by customer_id, wrong region (should be []) ---")
print(search_object("us-east", "Transaction", {"customer_id": "cust_001"}))

print("--- Invalid filter key (should raise ValueError) ---")
try:
    search_object("us-west", "Customer", {"transactions": "cust_001"})
    print("ERROR: should have raised!")
except ValueError as e:
    print(f"Correctly rejected: {e}")
