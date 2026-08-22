from pathlib import Path
from core.config import load_yaml

base = Path("deployments/acme_corp")
print("--- config.yaml ---")
print(load_yaml(base / "config.yaml"))
print("--- ontology_schema.yaml ---")
print(load_yaml(base / "ontology_schema.yaml"))
print("--- policy.yaml ---")
print(load_yaml(base / "policy.yaml"))
