from deployments.acme_corp.ontology_adapter import search_object, get_field

print("--- search_object: same-region customer ---")
print(search_object("us-west", "Customer", {"customer_id": "cust_001"}))

print("--- search_object: cross-region customer ---")
print(search_object("us-west", "Customer", {"customer_id": "cust_003"}))

print("--- get_field: plain data field ---")
print(get_field("us-west", "Customer", "cust_001", "region"))

print("--- get_field: forward link (Transaction.customer_id) ---")
print(get_field("us-west", "Transaction", 1, "customer_id"))

print("--- get_field: reverse link (Customer.transactions) ---")
print(get_field("us-west", "Customer", "cust_001", "transactions"))

print("--- get_field: same transaction, wrong region (should be None) ---")
print(get_field("us-east", "Transaction", 1, "amount"))

print("--- get_field: same transaction, right region (real value) ---")
print(get_field("us-west", "Transaction", 1, "amount"))
