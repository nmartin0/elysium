"""
deployment_loader.py  (generic -- org-agnostic)

Reads a deployment's config.yaml, ontology_schema.yaml, and policy.yaml
from a given directory and returns them bundled into one
DeploymentConfig object. Contains zero knowledge of any specific
organization -- only the fixed file names and key names this project's
deployment convention expects.

resolve_runtime_paths() is THE single source of truth for where
config, data, and logs live -- three genuinely independent locations,
always, not "one folder with environment variables as a special
override." Local development's own defaults (deployment/etc,
deployment/var/lib, deployment/var/log) already mirror the exact same
structure a real install uses (/etc/elysium, /var/lib/elysium,
/var/log/elysium) -- see that function's own docstring.

Two registries live here -- _ADAPTER_REGISTRY (data silos) and
_LLM_ADAPTER_REGISTRY (LLM backends) -- both hardcoded dicts today,
both exactly the place a future entry-points-based third-party
discovery mechanism would replace, without changing anything else in
this file, DataMediator, or AgentLoop.

Called by: scripts/run_deployment.py, scripts/serve_requests.py,
           api/app.py, tests/integration/conftest.py
"""

import os
from dataclasses import dataclass
from pathlib import Path

from adapters.ollama_adapter import OllamaAdapter
from adapters.sqlite_adapter import SQLiteAdapter
from core.config import load_yaml
from core.intermediate_layer.audit import AuditLog
from core.llm.concurrency_limited_adapter import ConcurrencyLimitedLLMAdapter
from core.llm.interface import LLMAdapter
from core.ontology.interface import DataSiloAdapter
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLog

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
    action_types: dict            # NAMED action types (action-types-redesign branch) --
                                   # a deployment with none declared (the overwhelmingly
                                   # common case today) gets {} here, populated explicitly
                                   # by load_deployment() below via schema_raw.get(...),
                                   # not a dataclass-level default -- same "explicit, not
                                   # silently inferred" discipline as writes_enabled/
                                   # visible_action_types in agent_step_prompt.py.


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
            # GENUINELY optional in the YAML itself -- .get() with a {}
            # default, same as enabled_tools above, NOT inside the
            # strict required-key try/except: a deployment predating
            # named actions entirely (or simply not using them) has no
            # "action_types:" key in ontology_schema.yaml at all, and
            # that must remain completely valid.
            action_types=schema_raw.get("action_types", {}),
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
    return {object_type: type_def["storage"]["silo"] for object_type, type_def in schema.items()}


@dataclass(frozen=True)
class RuntimePaths:
    config_dir: Path
    data_dir: Path
    log_dir: Path


def resolve_runtime_paths() -> RuntimePaths:
    # THE one place any of Elysium's three runtime locations get
    # decided -- config, data, and logs are three genuinely
    # independent locations ALWAYS, not "one deployment/ folder, with
    # environment variables as a special production-only override."
    # deployment/etc, deployment/var/lib, and deployment/var/log (local
    # development's own defaults) already mirror the SAME structure a
    # real install uses (/etc/elysium, /var/lib/elysium,
    # /var/log/elysium) -- local dev isn't a different, older
    # convention env vars deviate from; it's the same three-location
    # model, just with defaults that happen to live under one
    # project-relative root.
    config_dir = Path(os.environ["ELYSIUM_CONFIG_DIR"]) if "ELYSIUM_CONFIG_DIR" in os.environ \
        else Path("deployment/etc")
    data_dir = Path(os.environ["ELYSIUM_DATA_DIR"]) if "ELYSIUM_DATA_DIR" in os.environ \
        else Path("deployment/var/lib")
    log_dir = Path(os.environ["ELYSIUM_LOG_DIR"]) if "ELYSIUM_LOG_DIR" in os.environ \
        else Path("deployment/var/log")
    return RuntimePaths(config_dir, data_dir, log_dir)


def load_deployment_bundle(config_dir: Path, data_dir: Path | None = None,
                            log_dir: Path | None = None) -> tuple[DeploymentConfig, DataMediator]:
    # Loads config, builds one adapter instance per declared silo (see
    # _ADAPTER_REGISTRY above), and wires them into a DataMediator that
    # knows which object types route to which silo.
    #
    # data_dir defaults to config_dir if not given at all -- a
    # defensive fallback for a caller that doesn't go through
    # resolve_runtime_paths() (e.g. a quick script or test constructing
    # paths directly), not the normal case. Normally config_dir and
    # data_dir are genuinely different directories even in local
    # development -- see resolve_runtime_paths()'s own docstring for
    # why they're never meant to collapse to one "deployment/" folder.
    if data_dir is None:
        data_dir = config_dir

    config = load_deployment(config_dir)

    # database.path-equivalent connection fields (e.g. SQLite's "path")
    # resolve against data_dir, NOT config_dir -- the one place those
    # two directories genuinely need to differ.
    resolved_silo_configs = {}
    for silo_name, silo_config in config.silo_configs.items():
        connection = dict(silo_config["connection"])
        if "path" in connection:
            connection["path"] = data_dir / connection["path"]
        resolved_silo_configs[silo_name] = {**silo_config, "connection": connection}

    adapters = _build_adapters(resolved_silo_configs)
    silo_for_type = _build_silo_for_type(config.schema)
    # DataMediator no longer takes users/security_attribute -- identity
    # is resolved ONCE per request by the caller (see core/
    # intermediate_layer/auth.py's resolve_user_record()), not held by
    # the long-lived mediator itself.
    #
    # write_log lives alongside credentials.db, under the same
    # data_dir -- see core/ontology/write_log.py's own module
    # docstring for the mechanism. This ONE instance is the single
    # source of truth for the whole deployment -- a caller building a
    # WriteMediator around this same DataMediator reads it back via
    # mediator.write_log (see WriteMediator's own __init__), never
    # constructs or is passed a second, separate one.
    write_log = WriteLog(data_dir / "write_log.db")
    # audit_log is genuinely OPTIONAL here, unlike write_log above --
    # log_dir defaults to None (not resolved against data_dir or
    # config_dir, since it's a genuinely third, independent location --
    # see resolve_runtime_paths()'s own docstring). When None,
    # DataMediator's own constructor supplies a real, working default
    # AuditLog itself (see its own docstring for why that default
    # exists and this store is never left without one) -- nothing
    # further to do here in that case.
    audit_log = AuditLog(log_dir / "audit.log") if log_dir is not None else None
    mediator = DataMediator(config.schema, adapters, silo_for_type, config.roles,
                             write_log=write_log, audit_log=audit_log)
    return config, mediator


def load_example_queries(config_dir: Path) -> list[dict]:
    # example_queries.yaml is config-like (ships with the deployment,
    # human-authored), not real runtime data -- always resolved against
    # config_dir, never data_dir.
    raw = load_yaml(config_dir / "example_queries.yaml")
    return raw["examples"]
