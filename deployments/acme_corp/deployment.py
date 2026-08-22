"""
deployment.py  (acme_corp-specific -- the ONE place YAML gets loaded)

Loads config.yaml, ontology_schema.yaml, and policy.yaml once, and
exposes the results as plain constants. This is the ONLY file in the
whole project that reads YAML directly -- core/ code never does, and
other deployment files (ontology_adapter.py) import SCHEMA from here
rather than reading YAML themselves. "Where does config come from" is
answered in exactly one place, so it can change later (a database, env
vars, whatever) without touching anything downstream.

Used by: deployments/acme_corp/test_run.py, ontology_adapter.py
"""

from pathlib import Path

from core.config import load_yaml

_BASE = Path(__file__).resolve().parent

_config = load_yaml(_BASE / "config.yaml")
_schema_raw = load_yaml(_BASE / "ontology_schema.yaml")
_policy_raw = load_yaml(_BASE / "policy.yaml")

OLLAMA_URL = _config["ollama"]["base_url"]
STEP_MODEL = _config["llm"]["step_model"]
SYNTHESIS_MODEL = _config["llm"]["synthesis_model"]
REQUEST_TIMEOUT_SECONDS = _config["llm"]["request_timeout_seconds"]
MAX_HOPS = _config["agent"]["max_hops"]
MAX_CONSECUTIVE_DUPLICATES = _config["agent"]["max_consecutive_duplicates"]

SCHEMA = _schema_raw["object_types"]
USERS = _policy_raw["users"]
