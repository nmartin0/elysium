"""
deployment_loader.py  (generic -- org-agnostic)

Reads a deployment's config.yaml, ontology_schema.yaml, policy.yaml,
and data_silos.yaml from a given directory and returns them bundled
into one DeploymentConfig object. Contains zero knowledge of any
specific organization -- only the fixed file names and key names this
project's deployment convention expects.

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
from core.intermediate_layer.policy_validation import validate_roles
from core.llm.concurrency_limited_adapter import ConcurrencyLimitedLLMAdapter
from core.llm.interface import LLMAdapter
from core.ontology.action_types import validate_action_types
from core.ontology.interface import DataSiloAdapter
from core.ontology.mediator import DataMediator
from core.ontology.object_type_validation import validate_object_types
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


def _require_str(value, description: str) -> None:
    # Catches the "Norway problem" directly: YAML's own implicit type
    # coercion (an unquoted no/yes/on/off/true/false becomes a real
    # bool; an unquoted date-like value like 2024-01-01 becomes a real
    # datetime.date; a leading-zero numeral like 010 becomes octal-
    # interpreted 8) can silently turn what an admin plainly INTENDED
    # as a string identifier -- an object type name, a field name, a
    # role name, a grant string -- into something else entirely. Every
    # position this checks is later matched via an EXACT string
    # comparison against a genuinely runtime-supplied string (
    # authorize()'s own action_id in role["allowed_actions"], a dict
    # lookup by object_type/field name) -- a coerced, non-string value
    # here doesn't just look wrong, it silently, permanently never
    # matches anything real again, exactly the class of bug this
    # deployment's own config loading now refuses to let through.
    # Found directly, empirically, not assumed -- see core/
    # deployment_loader.py's own AI-notes for the real test that
    # confirmed this (a role literally named "no" resolving to the
    # Python boolean False, not the string "no").
    if not isinstance(value, str):
        raise ValueError(
            f"{description} is {value!r} ({type(value).__name__}), not a string -- "
            f"quote it in the YAML (e.g. \"no\" instead of no)."
        )


def validate_identifier_types(schema_raw: dict, policy_raw: dict) -> None:
    # Runs BEFORE anything else below even attempts to interpret
    # schema_raw/policy_raw's own contents -- core/ontology/action_
    # types.py's own validate_action_types() and core/intermediate_
    # layer/policy_validation.py's own validate_roles() both assume
    # every name they're comparing is already a genuine string; this
    # is the check that makes that assumption safe to make, catching
    # the "looks like a string, silently isn't" class of mistake
    # BEFORE either of them ever runs. See _require_str()'s own
    # docstring for the full reasoning.
    object_types = schema_raw.get("object_types", {})
    for object_type_name, object_type_def in object_types.items():
        _require_str(object_type_name, "An object_type name")
        if "id_field" in object_type_def:
            _require_str(object_type_def["id_field"], f"{object_type_name!r}'s own id_field")
        if "title_field" in object_type_def:
            _require_str(object_type_def["title_field"], f"{object_type_name!r}'s own title_field")
        security = object_type_def.get("security", {})
        if "field" in security:
            _require_str(security["field"], f"{object_type_name!r}'s own security.field")
        if "via_field" in security:
            _require_str(security["via_field"], f"{object_type_name!r}'s own security.via_field")
        for field_name in object_type_def.get("fields", {}):
            _require_str(field_name, f"A field name on {object_type_name!r}")

    action_types = schema_raw.get("action_types", {})
    for action_type_name, action_def in action_types.items():
        _require_str(action_type_name, "An action_type name")
        for param_name in action_def.get("parameters", {}):
            _require_str(param_name, f"A parameter name on {action_type_name!r}")
        for affected_type in action_def.get("affected_object_types") or []:
            _require_str(affected_type, f"An affected_object_types entry on {action_type_name!r}")
        for i, sub_write in enumerate(action_def.get("sub_writes") or []):
            if "object_type" in sub_write:
                _require_str(sub_write["object_type"], f"{action_type_name!r}'s sub_writes[{i}].object_type")

    roles = policy_raw.get("roles", {})
    for role_name, role_def in roles.items():
        _require_str(role_name, "A role name")
        for grant in role_def.get("allowed_actions") or []:
            _require_str(grant, f"A grant in role {role_name!r}'s allowed_actions")

    for user_id in policy_raw.get("users", {}):
        _require_str(user_id, "A user_id in policy.yaml's own users section")


def load_deployment(base_path: Path) -> DeploymentConfig:
    config = load_yaml(base_path / "config.yaml")
    schema_raw = load_yaml(base_path / "ontology_schema.yaml")
    policy_raw = load_yaml(base_path / "policy.yaml")
    data_silos_raw = load_yaml(base_path / "data_silos.yaml")

    validate_identifier_types(schema_raw, policy_raw)

    # tools.enabled is genuinely OPTIONAL -- a deployment with no tools
    # declared (or no "tools" section at all) is completely valid, unlike
    # every other field below. Uses .get() with a default specifically
    # so this stays outside the strict required-key error handling.
    enabled_tools = config.get("tools", {}).get("enabled", [])

    try:
        deployment_config = DeploymentConfig(
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
            silo_configs=data_silos_raw["data_silos"],
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
        raise ValueError(f"Missing expected key {e} in config.yaml/ontology_schema.yaml/policy.yaml.") from e

    # A SEPARATE validation pass, deliberately after the try/except
    # above -- by this point every basic required key is already
    # confirmed present; this checks the DEEPER structure of every
    # action_type (see core/ontology/action_types.py's own module
    # docstring for the full reasoning on why this belongs here, at
    # load time, not deferred to propose_action() -- including why a
    # missing "sub_writes" is now REJECTED, not silently skipped).
    validate_action_types(deployment_config.action_types, deployment_config.schema)

    # title_field -- an OPTIONAL, per-object-type display-name
    # declaration (see core/ontology/object_type_validation.py's own
    # module docstring for the full reasoning, including what's
    # DELIBERATELY still deferred).
    validate_object_types(deployment_config.schema)

    # Every role's own grants, checked against what they actually
    # reference -- see core/intermediate_layer/policy_validation.py's
    # own module docstring for the full reasoning: authorize() itself
    # does a bare exact-string match with no existence-checking of its
    # own, so a typo'd grant here would otherwise never fail loudly
    # anywhere, just silently never match.
    validate_roles(deployment_config.roles, deployment_config.schema, deployment_config.action_types,
                    deployment_config.enabled_tools)

    return deployment_config


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


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# RESOLVED (kept for history):
# - data_silos.yaml was split out of config.yaml into its own,
#   fourth required file (config.yaml, ontology_schema.yaml, policy.
#   yaml, data_silos.yaml) -- load_deployment() now reads it directly
#   and pulls silo_configs from ITS "data_silos" key, not config's own.
#   A genuine separation-of-concerns split, not just a rename:
#   connection details (hosts, credentials, paths) are a different
#   kind of configuration than operational tuning (which model, how
#   many hops), often owned or secured differently in a real
#   deployment -- and matches this project's own existing "one file
#   per concern" convention (ontology_schema.yaml for the data model,
#   policy.yaml for RBAC/MAC) rather than being the one exception to
#   it. Every real/template/fixture config directory (deployment/etc,
#   templates, tests/integration/fixtures) was split and re-verified
#   by actually loading it through load_deployment(), not just edited
#   by inspection -- including the three-silo fixtures case, confirmed
#   through a real, no-Ollama integration test run afterward. scripts/
#   lint_deployment.py needed no functional changes at all: its
#   existing generic OSError/yaml.YAMLError/ValueError handling around
#   load_deployment() already covers a missing, malformed, or
#   incomplete data_silos.yaml exactly the way it already covered the
#   other three files -- confirmed directly with a new, dedicated test
#   (tests/unit/test_lint_deployment.py's own test_missing_data_silos_
#   file_returns_false), not assumed safe by the wrapper design alone.
#
# - _require_str()'s own error message, and the "Missing expected
#   key" message in load_deployment()'s own try/except, were both
#   trimmed to one line each, per the user's own explicit request for
#   compiler-style brevity -- the "Norway problem" explanation
#   _require_str() used to spell out inline (unquoted no/yes/date-
#   like values/octal numerals all silently coercing) moved to this
#   function's own comment above the isinstance() check instead; the
#   raised string itself now just names the bad value and the fix
#   ("quote it"), matching every other validator touched the same
#   pass (see core/ontology/action_types.py's own AI-notes for the
#   identical change made there).
#
# CONTEXT: validate_identifier_types() was added during a deliberate,
# requested audit of scripts/lint_deployment.py's own reliability
# against real, established YAML/config-validator failure modes -- see
# that script's own AI-notes for the other three fixes from the same
# pass. This one specifically was PROMOTED from a private
# (_validate_identifier_types) to a public function partway through
# that same work: it started as something ONLY load_deployment()
# itself would ever call, but the linter genuinely needs to call it
# too (to distinguish "a structural/identifier problem, fail fast" from
# "an action_type/role problem, collect every one of them" -- see the
# linter's own docstring). No existing precedent anywhere in this
# codebase for importing an underscore-prefixed function across module
# boundaries (checked directly, not assumed) -- promoting it, rather
# than importing the private name anyway, was the right call to keep
# that project-wide convention intact, matching how validate_action_
# types()/validate_roles() are ALSO already public for the identical
# reason (each has more than one real caller).
#
# DEFERRED (known, intentional, not yet built):
# - validate_identifier_types() checks identifiers (keys, and the few
#   VALUES that function as identifiers -- id_field, security.field,
#   security.via_field, grant strings) for being genuine strings, not
#   other YAML-coercible VALUES a mutation's own "value" could still
#   silently become (a date, an octal-interpreted number). See
#   core/config.py's own AI-notes for why that narrower, value-level
#   gap was deliberately left for a future, separate, more schema-
#   aware pass rather than addressed here or at the generic YAML-
#   loading level.
#
# RESOLVED (kept for history):
# - security.via_field itself used to be missing from this exact
#   check -- security.field got _require_str(), via_field silently
#   didn't. Found and fixed alongside core/ontology/object_type_
#   validation.py's own new referential validation for both (see that
#   module's own docstring for the fuller, four-part gap this closed
#   together).
