"""
deployment_loader.py  (generic -- org-agnostic)

Reads a deployment's config.yaml, ontology_schema.yaml, and policy.yaml
from a given base directory and returns them bundled into one
DeploymentConfig object. Contains zero knowledge of any specific
organization -- only the fixed file names and key names this project's
deployment convention expects.

Two registries live here -- _ADAPTER_REGISTRY (data silos) and
_LLM_ADAPTER_REGISTRY (LLM backends) -- both hardcoded dicts today,
both exactly the place a future entry-points-based third-party
discovery mechanism would replace, without changing anything else in
this file, DataMediator, or AgentLoop.

Called by: scripts/run_deployment.py, tests/integration/conftest.py
"""

from dataclasses import dataclass
from pathlib import Path

from core.config import load_yaml
from core.ontology.interface import DataSiloAdapter
from core.ontology.mediator import DataMediator
from core.llm.interface import LLMAdapter
from core.llm.concurrency_limited_adapter import ConcurrencyLimitedLLMAdapter
from adapters.sqlite_adapter import SQLiteAdapter
from adapters.ollama_adapter import OllamaAdapter

_ADAPTER_REGISTRY: dict[str, type] = {
    "sqlite": SQLiteAdapter,
}

_LLM_ADAPTER_REGISTRY: dict[str, type] = {
    "ollama": OllamaAdapter,
}


@dataclass
class DeploymentConfig:
    base_path: Path
    llm_provider: str            # e.g. "ollama" -- key into _LLM_ADAPTER_REGISTRY
    llm_connection: dict           # opaque to core/ -- e.g. {"base_url": ..., "request_timeout_seconds": ...}
    step_model: str
    synthesis_model: str
    max_hops: int
    max_consecutive_duplicates: int
    max_consecutive_invalid_steps: int
    max_concurrent_requests: int   # dispatch-layer thread pool size
    schema: dict
    users: dict
    roles: dict                    # role name -> {"allowed_actions": [...]} -- RBAC
    security_attribute: str         # MAC -- e.g. "region"
    silo_configs: dict          # silo name -> {"adapter": ..., "connection": {...}}
    enabled_tools: list[str]      # from config.yaml tools.enabled -- GENUINELY optional,
                                   # unlike everything else here (see load_deployment())


def _freeze_roles(roles_raw: dict) -> dict:
    # Converts each role's allowed_actions from a plain list to a
    # frozenset, ONCE, here, at load time -- authorize() is called on
    # every object touched, every field read, every write, every tool
    # call, so a real role's allowed_actions (a dozen-plus entries in
    # a typical deployment) being a list would mean a genuine O(n)
    # linear scan on every single one of those checks. Converting once
    # here makes every downstream authorize() call real O(1), for free.
    return {
        role_name: {**role_def, "allowed_actions": frozenset(role_def.get("allowed_actions", []))}
        for role_name, role_def in roles_raw.items()
    }


def load_deployment(base_path: Path) -> DeploymentConfig:
    config = load_yaml(base_path / "config.yaml")
    schema_raw = load_yaml(base_path / "ontology_schema.yaml")
    policy_raw = load_yaml(base_path / "policy.yaml")

    # tools.enabled is genuinely OPTIONAL -- a deployment with no tools
    # declared (or no "tools" section at all) is completely valid, unlike
    # every other field below. Uses .get() with a default specifically
    # so this stays outside the strict required-key error handling.
    enabled_tools = config.get("tools", {}).get("enabled", [])

    try:
        return DeploymentConfig(
            base_path=base_path,
            llm_provider=config["llm"]["provider"],
            llm_connection=config["llm"]["connection"],
            step_model=config["llm"]["step_model"],
            synthesis_model=config["llm"]["synthesis_model"],
            max_hops=config["agent"]["max_hops"],
            max_consecutive_duplicates=config["agent"]["max_consecutive_duplicates"],
            max_consecutive_invalid_steps=config["agent"]["max_consecutive_invalid_steps"],
            max_concurrent_requests=config["agent"].get("max_concurrent_requests", 4),
            schema=schema_raw["object_types"],
            users=policy_raw["users"],
            roles=_freeze_roles(policy_raw["roles"]),
            security_attribute=policy_raw["security_attribute"],
            silo_configs=config["data_silos"],
            enabled_tools=enabled_tools,
        )
    except KeyError as e:
        raise ValueError(
            f"Missing expected key {e} in config.yaml, ontology_schema.yaml, "
            f"or policy.yaml under {base_path} -- check for typos or a "
            f"missing section."
        ) from e


def build_llm_adapter(config: DeploymentConfig, model: str) -> LLMAdapter:
    # The one place an LLM adapter gets constructed -- used for BOTH the
    # step-selection and synthesis clients. Always wrapped in
    # ConcurrencyLimitedLLMAdapter -- concrete adapters never throttle
    # themselves, core/ enforces uniformly based on what each declares.
    adapter_class = _LLM_ADAPTER_REGISTRY.get(config.llm_provider)
    if adapter_class is None:
        raise ValueError(
            f"Unknown LLM provider {config.llm_provider!r} -- registered "
            f"providers: {sorted(_LLM_ADAPTER_REGISTRY.keys())}"
        )
    return ConcurrencyLimitedLLMAdapter(adapter_class(model, config.llm_connection))


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
    # DataMediator no longer takes users/security_attribute -- identity
    # is resolved ONCE per request by the caller (see core/
    # intermediate_layer/auth.py's resolve_user_record()), not held by
    # the long-lived mediator itself.
    mediator = DataMediator(config.schema, adapters, silo_for_type, config.roles)
    return config, mediator


def load_example_queries(deployment_dir: Path) -> list[dict]:
    raw = load_yaml(deployment_dir / "example_queries.yaml")
    return raw["examples"]
