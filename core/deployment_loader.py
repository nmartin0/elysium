"""
deployment_loader.py  (generic -- org-agnostic)

Reads a deployment's config.yaml, ontology_schema.yaml, and policy.yaml
from a given base directory and returns them bundled into one
DeploymentConfig object. Contains zero knowledge of any specific
organization -- only the fixed file names and key names this project's
deployment convention expects.

load_deployment_bundle() is where the adapter REGISTRY lives -- the
hardcoded {"sqlite": SQLiteAdapter} mapping below is exactly the place
a future entry-points-based third-party discovery mechanism would
replace, without changing anything else in this file or in
DataMediator.

Called by: scripts/run_deployment.py, tests/integration/conftest.py
"""

from dataclasses import dataclass
from pathlib import Path

from core.config import load_yaml
from core.ontology.interface import DataSiloAdapter
from core.ontology.mediator import DataMediator
from adapters.sqlite_adapter import SQLiteAdapter

# The adapter registry. Third-party adapters would be discovered via
# Python packaging entry points instead of a hardcoded dict -- this is
# the one place that swap would happen; nothing else in this file or in
# DataMediator needs to change to support it.
_ADAPTER_REGISTRY: dict[str, type] = {
    "sqlite": SQLiteAdapter,
}


@dataclass
class DeploymentConfig:
    base_path: Path
    ollama_url: str
    step_model: str
    synthesis_model: str
    request_timeout_seconds: int
    max_hops: int
    max_consecutive_duplicates: int
    max_consecutive_invalid_steps: int
    schema: dict
    users: dict
    security_attribute: str
    silo_configs: dict          # silo name -> {"adapter": ..., "connection": {...}}


def load_deployment(base_path: Path) -> DeploymentConfig:
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
            schema=schema_raw["object_types"],
            users=policy_raw["users"],
            security_attribute=policy_raw["security_attribute"],
            silo_configs=config["data_silos"],
        )
    except KeyError as e:
        raise ValueError(
            f"Missing expected key {e} in config.yaml, ontology_schema.yaml, "
            f"or policy.yaml under {base_path} -- check for typos or a "
            f"missing section."
        ) from e


def _build_adapters(silo_configs: dict) -> dict[str, DataSiloAdapter]:
    adapters = {}
    for silo_name, silo_config in silo_configs.items():
        adapter_key = silo_config["adapter"]
        adapter_class = _ADAPTER_REGISTRY.get(adapter_key)
        if adapter_class is None:
            raise ValueError(
                f"Unknown adapter type {adapter_key!r} for silo {silo_name!r} "
                f"-- registered adapters: {sorted(_ADAPTER_REGISTRY.keys())}"
            )
        adapters[silo_name] = adapter_class(silo_config["connection"])
    return adapters


def _build_silo_for_type(schema: dict) -> dict[str, str]:
    return {object_type: type_def["silo"] for object_type, type_def in schema.items()}


def load_deployment_bundle(deployment_dir: Path) -> tuple[DeploymentConfig, DataMediator]:
    # Loads config, builds one adapter instance per declared silo (see
    # _ADAPTER_REGISTRY above), and wires them into a DataMediator that
    # knows which object types route to which silo.
    config = load_deployment(deployment_dir)

    # base_path resolves database.path-equivalent connection fields
    # (e.g. SQLite's "path") relative to this deployment's own folder,
    # same convention as everything else in the config.
    resolved_silo_configs = {}
    for silo_name, silo_config in config.silo_configs.items():
        connection = dict(silo_config["connection"])
        if "path" in connection:
            connection["path"] = deployment_dir / connection["path"]
        resolved_silo_configs[silo_name] = {**silo_config, "connection": connection}

    adapters = _build_adapters(resolved_silo_configs)
    silo_for_type = _build_silo_for_type(config.schema)
    mediator = DataMediator(config.schema, adapters, silo_for_type)
    return config, mediator


def load_example_queries(deployment_dir: Path) -> list[dict]:
    raw = load_yaml(deployment_dir / "example_queries.yaml")
    return raw["examples"]
