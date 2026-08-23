"""
deployment_loader.py  (generic -- org-agnostic)

Reads a deployment's config.yaml, ontology_schema.yaml, and policy.yaml
from a given base directory and returns their contents as explicit
values. Contains zero knowledge of any specific organization -- only
the fixed file names and key names this project's deployment convention
expects. Any org's deployment folder that follows this convention can
use this exact function.

Called by: each deployment's own thin entry point (e.g.
           deployments/acme_corp/deployment.py), passed that
           deployment's own directory.
"""

from pathlib import Path
from types import SimpleNamespace

from core.config import load_yaml


def load_deployment(base_path: Path) -> SimpleNamespace:
    config = load_yaml(base_path / "config.yaml")
    schema_raw = load_yaml(base_path / "ontology_schema.yaml")
    policy_raw = load_yaml(base_path / "policy.yaml")

    return SimpleNamespace(
        base_path=base_path,
        OLLAMA_URL=config["ollama"]["base_url"],
        STEP_MODEL=config["llm"]["step_model"],
        SYNTHESIS_MODEL=config["llm"]["synthesis_model"],
        REQUEST_TIMEOUT_SECONDS=config["llm"]["request_timeout_seconds"],
        MAX_HOPS=config["agent"]["max_hops"],
        MAX_CONSECUTIVE_DUPLICATES=config["agent"]["max_consecutive_duplicates"],
        MAX_CONSECUTIVE_INVALID_STEPS=config["agent"]["max_consecutive_invalid_steps"],
        DB_PATH=base_path / config["database"]["path"],
        SCHEMA=schema_raw["object_types"],
        USERS=policy_raw["users"],
        SECURITY_ATTRIBUTE=policy_raw["security_attribute"],
    )
