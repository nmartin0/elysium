"""
deployment_loader.py  (generic -- org-agnostic)

Reads a deployment's config.yaml, ontology_schema.yaml, and policy.yaml
from a given base directory and returns them bundled into one
DeploymentConfig object. Contains zero knowledge of any specific
organization -- only the fixed file names and key names this project's
deployment convention expects.

Returns a @dataclass rather than a plain dict or SimpleNamespace --
per Python's own docs, dataclasses are the idiomatic way to bundle
named, related data together. Every field is declared with a type, so
an editor can autocomplete deployment.step_model and flag a typo like
deployment.setp_model immediately, instead of failing at runtime.

Called by: each deployment's own thin entry point (e.g.
           deployments/acme_corp/deployment.py), passed that
           deployment's own directory.
"""

from dataclasses import dataclass
from pathlib import Path

from core.config import load_yaml


@dataclass
class DeploymentConfig:
    # Everything a deployment needs, in one bundle -- see field-level
    # comments below for what each one means and where it's used.
    base_path: Path
    ollama_url: str            # where core/llm/ollama_client.py sends requests
    step_model: str            # model used for core/agent/agentic_loop.py's step selection
    synthesis_model: str       # model used for final answer synthesis
    request_timeout_seconds: int
    max_hops: int               # hard cap on agent loop iterations
    max_consecutive_duplicates: int
    max_consecutive_invalid_steps: int
    db_path: Path                # this deployment's actual SQLite file
    schema: dict                  # object types/fields, see core/ontology/schema.py
    users: dict                    # who exists and their security attribute value + permissions
    security_attribute: str         # which field on a user record is the security value


def load_deployment(base_path: Path) -> DeploymentConfig:
    # Reads all three YAML files for one deployment and returns every
    # value the rest of the project needs, bundled into one object.
    config = load_yaml(base_path / "config.yaml")
    schema_raw = load_yaml(base_path / "ontology_schema.yaml")
    policy_raw = load_yaml(base_path / "policy.yaml")

    try:
        return DeploymentConfig(
            base_path=base_path,
            ollama_url=config["ollama"]["base_url"],
            step_model=config["llm"]["step_model"],
            synthesis_model=config["llm"]["synthesis_model"],
            request_timeout_seconds=config["llm"]["request_timeout_seconds"],
            max_hops=config["agent"]["max_hops"],
            max_consecutive_duplicates=config["agent"]["max_consecutive_duplicates"],
            max_consecutive_invalid_steps=config["agent"]["max_consecutive_invalid_steps"],
            # database.path in config.yaml is relative to this deployment's
            # own folder, not absolute -- e.g. "dev_fixtures/mediator.db"
            # resolves to <base_path>/dev_fixtures/mediator.db.
            db_path=base_path / config["database"]["path"],
            schema=schema_raw["object_types"],
            users=policy_raw["users"],
            security_attribute=policy_raw["security_attribute"],
        )
    except KeyError as e:
        raise ValueError(
            f"Missing expected key {e} in config.yaml, ontology_schema.yaml, "
            f"or policy.yaml under {base_path} -- check for typos or a "
            f"missing section."
        ) from e
