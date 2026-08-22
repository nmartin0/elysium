from deployments.acme_corp.ontology_adapter import search_object, get_field

print("--- search_object: same-region customer (should find cust_001) ---")
print(search_object("us-west", "Customer", {"customer_id": "cust_001"}))

print("--- search_object: cross-region customer (should be []) ---")
print(search_object("us-west", "Customer", {"customer_id": "cust_003"}))

print("--- get_field: plain data field ---")
print(get_field("us-west", "Customer", "cust_001", "region"))

print("--- get_field: forward link (Customer -> its transactions) ---")
transaction_ids = get_field("us-west", "Customer", "cust_001", "transactions")
print(transaction_ids)

print("--- get_field: data field on the linked object ---")
print(get_field("us-west", "Transaction", transaction_ids[0], "amount"))

print("--- get_field: reverse link (Transaction -> its owning Customer) ---")
print(get_field("us-west", "Transaction", transaction_ids[0], "customer_id"))

print("--- get_field: SAME transaction, WRONG region (should be None) ---")
print(get_field("us-east", "Transaction", transaction_ids[0], "amount"))

print("--- get_field: transaction_id 5 belongs to cust_003 (us-east) ---")
print("  requested as us-west (should be None, blocked):")
print(get_field("us-west", "Transaction", 5, "amount"))
print("  requested as us-east (should return the real amount):")
print(get_field("us-east", "Transaction", 5, "amount"))
