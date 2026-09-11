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

import hashlib
import itertools
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from pyiceberg.catalog.sql import SqlCatalog

from adapters.claude_agent_sdk_adapter import ClaudeAgentSDKAdapter
from adapters.ollama_adapter import OllamaAdapter
from adapters.sqlite_adapter import SQLiteReadAdapter, SQLiteWriteAdapter
from core.config import load_yaml
from core.functions.registry import validate_function_declarations
from core.intermediate_layer.audit import AuditLog
from core.intermediate_layer.policy_validation import validate_roles
from core.llm.concurrency_limited_adapter import ConcurrencyLimitedLLMAdapter
from core.llm.interface import LLMAdapter
from core.mirror.mirror_adapter import MirrorReadAdapter
from core.ontology.action_types import validate_action_types
from core.ontology.interface import ExternalReadAdapter, ExternalWriteAdapter
from core.ontology.link_types import expand_link_types, validate_link_types
from core.ontology.mediator import DataMediator
from core.ontology.object_type_validation import validate_object_types
from core.ontology.submission_criteria import validate_action_type_criteria
from core.ontology.write_log import WriteLogReader, WriteLogWriter

# Two real, SEPARATE registries -- not one, mapping to a (read, write)
# tuple -- confirmed this is the clearer shape: _build_adapters() below
# takes an explicit `registry` parameter naming exactly which one it's
# building from, so a caller (and a reader) can see directly which real
# capability a given call produces, rather than needing to also track
# an index into a tuple. See core/ontology/interface.py's own AI-notes
# for the fuller story behind why DataSiloAdapter itself split into
# ExternalReadAdapter/ExternalWriteAdapter, which is the real reason
# this registry split exists at all.
_READ_ADAPTER_REGISTRY: dict[str, type] = {
    "sqlite": SQLiteReadAdapter,
}

_WRITE_ADAPTER_REGISTRY: dict[str, type] = {
    "sqlite": SQLiteWriteAdapter,
}

_LLM_ADAPTER_REGISTRY: dict[str, type] = {
    "ollama": OllamaAdapter,
    # Runs the local `claude` CLI, so calls draw on the operator's
    # Claude subscription Agent SDK credit rather than separately
    # billed API credits. See the adapter's own module docstring.
    "claude_agent_sdk": ClaudeAgentSDKAdapter,
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
    read_from_mirror: bool        # Phase 4 of the read-only mirror architecture -- serve
                                   # READS from the local Iceberg mirror rather than querying
                                   # the customer's own databases live. Writes are unaffected
                                   # either way: they always go to the real database. False by
                                   # default, so the live path stays the default until a
                                   # deployment explicitly opts in. See ROADMAP.md.
    action_types: dict            # NAMED action types (action-types-redesign branch) --
                                   # a deployment with none declared (the overwhelmingly
                                   # common case today) gets {} here, populated explicitly
                                   # by load_deployment() below via schema_raw.get(...),
                                   # not a dataclass-level default -- same "explicit, not
                                   # silently inferred" discipline as writes_enabled/
                                   # visible_action_types in agent_step_prompt.py.

    # --- WHICH CONFIGURATION THIS IS -------------------------------
    #
    # Elysium reads these four files once at startup. Nothing today can
    # say WHICH configuration was in force for a given audit entry or a
    # given pending write, because there has only ever been one. That
    # stops being true the moment configuration can be reloaded while
    # running, and it is already not quite true now: a restart with
    # edited files produces a second configuration that the log cannot
    # distinguish from the first.
    #
    # Stamped on the audit log and on pending writes rather than kept
    # here alone -- see HOT_RELOAD_PLAN.md step 1. This is the whole of
    # step 1a: identity only, no reloading, no behaviour change.
    #
    # Modelled on Palantir treating version as a PARAMETER carried by
    # each operation rather than a global the server swaps: every
    # Foundry Ontology call names the ontology it acts against.
    generation: int               # monotonic within one process, first load is 1
    loaded_at: datetime           # when this configuration was read, UTC and aware
    source_digest: str            # sha256 over the four files' bytes -- see _source_digest()


# Assigned by the loader, never by a caller, so two callers cannot mint
# the same number. Guarded because a reload triggered by a signal
# handler and one triggered by an HTTP request could otherwise race
# (step 3), and getting the counter right later is harder than getting
# it right now.
_generation_lock = threading.Lock()
_generation_counter = itertools.count(1)


def _next_generation() -> int:
    with _generation_lock:
        return next(_generation_counter)


# The four files that ARE the deployment. Named once so that
# _source_digest() and load_deployment() cannot drift into disagreeing
# about what a deployment consists of -- the same reasoning as the step
# vocabulary probe in tests/unit/test_step_vocabulary_consistency.py.
CONFIG_FILENAMES = ["config.yaml", "ontology_schema.yaml", "policy.yaml", "data_silos.yaml"]


def _source_digest(base_path: Path, filenames: list[str]) -> str:
    """A stable fingerprint of the configuration files on disk.

    Over the RAW BYTES, not the parsed structures, and deliberately:
    the question this answers is "are these the same files as last
    time", which is about what was read, not about what it meant.
    Comparing parsed dicts would call a comment change identical and a
    key reordering different, both backwards for this purpose.

    Sorted by filename so the digest does not depend on iteration
    order, and each file's name is fed in alongside its content so that
    moving text between two files changes the digest.

    A missing file is fed as its name with no content rather than
    raising. load_deployment() below reports a missing file far better
    than a hash function could, and this must not become a second,
    worse place that error surfaces.
    """
    digest = hashlib.sha256()
    for name in sorted(filenames):
        digest.update(name.encode())
        path = base_path / name
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()


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


def _resolve_models(llm_config: dict) -> tuple[str, str]:
    """Returns (step_model, synthesis_model) from either config form.

    TWO FORMS, and exactly one per deployment:

        model: "phi4-mini"          # one model serves every call
        step_model / synthesis_model  # a different model for each

    The single form exists because running two models means Ollama
    loading and evicting between them -- measured at 12-47 seconds per
    load on CPU-only hardware, paid at least once per query. One model
    stays resident.

    Naming BOTH forms is rejected rather than resolved by precedence.
    A deployment that sets `model` and `step_model` has two plausible
    intentions and no way to signal which, and silently preferring one
    means the operator's next debugging session starts from a false
    belief about which model ran. Fails at load, like every other
    deployment-configuration error.
    """
    single = llm_config.get("model")
    step = llm_config.get("step_model")
    synthesis = llm_config.get("synthesis_model")

    if single is not None:
        if step is not None or synthesis is not None:
            raise ValueError(
                "config.yaml llm: set EITHER 'model' (one model for every call) "
                "OR both 'step_model' and 'synthesis_model', never both forms."
            )
        return single, single

    if step is None or synthesis is None:
        missing = [name for name, value in (("step_model", step), ("synthesis_model", synthesis))
                   if value is None]
        raise ValueError(
            f"config.yaml llm: missing {missing}. Set 'model' for one model serving "
            f"every call, or both 'step_model' and 'synthesis_model' for two."
        )
    return step, synthesis


def load_deployment(base_path: Path) -> DeploymentConfig:
    # Digested BEFORE parsing, so the fingerprint describes exactly the
    # bytes this load saw. Taking it afterwards would leave a window in
    # which a file changed between being read and being hashed.
    source_digest = _source_digest(base_path, CONFIG_FILENAMES)

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

    # Validated HERE, at load, alongside every other deployment config
    # error. A function declaring an object type the ontology does not
    # have would otherwise surface mid-conversation, after a user has
    # already asked a question, as a failure whose message names
    # nothing useful. Foundry runs its own compatibility checks before
    # publishing a function for the same reason.
    # LINK TYPES: validated then expanded into the per-field entries
    # every read path already consumes. The authoring surface is
    # link_types; the field form is internal and never authored -- see
    # core/ontology/link_types.py for why the old per-field
    # declarations had to go rather than be extended.
    object_types_raw = schema_raw.get("object_types", {})
    link_types_raw = schema_raw.get("link_types", {})
    validate_link_types(link_types_raw, object_types_raw)
    schema_raw["object_types"] = expand_link_types(link_types_raw, object_types_raw)

    validate_function_declarations(enabled_tools, schema_raw["object_types"])

    step_model, synthesis_model = _resolve_models(config["llm"])

    try:
        deployment_config = DeploymentConfig(
            generation=_next_generation(),
            loaded_at=datetime.now(UTC),
            source_digest=source_digest,
            base_path=base_path,
            llm_provider=config["llm"]["provider"],
            llm_connection=config["llm"]["connection"],
            step_model=step_model,
            synthesis_model=synthesis_model,
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
            # GENUINELY optional, defaulting to False -- a deployment
            # that has never run a sync (or simply wants live reads)
            # must stay completely valid, and the live path stays the
            # default until a deployment explicitly opts in. Phase 4 of
            # the read-only mirror architecture; see ROADMAP.md.
            read_from_mirror=config.get("mirror", {}).get("read_from_mirror", False),
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
    # Separate call because core/ontology/action_types.py may not
    # import core/ontology/submission_criteria.py -- they are siblings
    # in pyproject.toml's core.ontology layering. See that function's
    # own docstring.
    validate_action_type_criteria(deployment_config.action_types)

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


def _mirror_last_synced_at(config: DeploymentConfig, data_dir: Path) -> str | None:
    # The OLDEST last-sync time across every mirrored table, not the
    # newest -- deliberately conservative: a write applied after ANY
    # table's own last sync may not be reflected in the mirror yet, so
    # taking the newest would silently drop the overlay for tables that
    # happen to lag behind. Returns None if nothing has synced at all,
    # which correctly means "overlay everything applied so far."
    from core.mirror.iceberg_sync import IcebergMirrorSync
    from core.mirror.sync_targets import resolve_sync_targets

    sync = IcebergMirrorSync(data_dir / "mirror", {})
    timestamps = []
    for target in resolve_sync_targets({"object_types": config.schema}):
        synced_at = sync.last_synced_at(target.silo_name, target.table_name)
        if synced_at is None:
            # A table that has never synced -- nothing in the mirror to
            # be stale relative to, so no lower bound to impose.
            continue
        timestamps.append(synced_at.isoformat())
    return min(timestamps) if timestamps else None


def _build_read_adapters(config: DeploymentConfig, resolved_silo_configs: dict,
                          data_dir: Path) -> dict[str, ExternalReadAdapter]:
    # THE Phase 4 cutover, and deliberately the whole of it: which
    # adapters DataMediator holds, nothing else. Confirmed directly by
    # reading the real code before designing this -- every read in
    # DataMediator resolves its adapter through _adapter_for() or
    # _resolve_shared_storage(), so a MirrorReadAdapter satisfying the
    # same ExternalReadAdapter contract slots straight in. search_object(),
    # get_field(), MDO resolution and reverse links all work unchanged;
    # there is no branch threaded through any read path.
    #
    # WRITES ARE UNAFFECTED either way. load_deployment_bundle()'s own
    # write_adapters are always built live, against the customer's real
    # database -- a confirmed write must never land in a copy that the
    # next sync would simply overwrite. See ROADMAP.md's own Phase 4
    # section on why the mirror stays sync-written, sole writer.
    if not config.read_from_mirror:
        return cast(
            "dict[str, ExternalReadAdapter]",
            _build_adapters(resolved_silo_configs, _READ_ADAPTER_REGISTRY),
        )

    # One shared catalog across every silo -- they all read the same
    # mirror, and each silo maps to its own Iceberg namespace, matching
    # exactly what core/mirror/iceberg_sync.py writes.
    mirror_dir = data_dir / "mirror"
    catalog = SqlCatalog(
        "elysium_mirror",
        uri=f"sqlite:///{mirror_dir / 'catalog.db'}",
        warehouse=f"file://{mirror_dir / 'warehouse'}",
    )
    return {silo_name: MirrorReadAdapter(catalog, silo_name) for silo_name in resolved_silo_configs}


def _build_adapters(
    silo_configs: dict, registry: dict[str, type]
) -> dict[str, ExternalReadAdapter | ExternalWriteAdapter]:
    adapters = {}
    for silo_name, silo_config in silo_configs.items():
        adapter_key = silo_config["adapter"]
        adapter_class = registry.get(adapter_key)
        if adapter_class is None:
            raise ValueError(
                f"Unknown adapter type {adapter_key!r} for silo {silo_name!r} "
                f"-- registered adapters: {sorted(registry.keys())}"
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

    @property
    def secrets_dir(self) -> Path:
        """Where generated secrets live, under data rather than config.

        DERIVED, not a fourth environment variable. A secret is state
        the application produces, not configuration an operator
        supplies -- so it belongs with the databases, and giving it its
        own variable would invite pointing it somewhere world-readable.

        Nothing writes here yet. It exists because the generated
        first-run password needs a location with a documented mode
        before it needs a password, and adding the location afterwards
        means deciding permissions in a hurry.
        """
        return self.data_dir / "secrets"


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
    paths = RuntimePaths(config_dir, data_dir, log_dir)
    # 0700 on the secrets directory, set on creation AND on every
    # startup. Creating it correctly once is not enough: a restore from
    # backup, an unpacked archive or a careless chmod leaves it
    # readable, and the failure is silent.
    paths.secrets_dir.mkdir(parents=True, exist_ok=True)
    paths.secrets_dir.chmod(0o700)
    return paths


def load_deployment_bundle(
    config_dir: Path, data_dir: Path | None = None, log_dir: Path | None = None
) -> tuple[DeploymentConfig, DataMediator, dict[str, ExternalWriteAdapter]]:
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

    adapters = _build_read_adapters(config, resolved_silo_configs, data_dir)
    # A SECOND, genuinely independent set of adapter instances --
    # real, separate connection objects, not a second reference to the
    # same ones -- built specifically for a WriteMediator a caller may
    # go on to construct around the returned mediator. Phase 0 of the
    # read-only mirror initiative: a real, found prerequisite -- see
    # WriteMediator's own AI-notes and __init__ docstring for the full
    # story. Both sets are built from the exact same resolved_silo_
    # configs today (same credentials, same real permissions) --
    # deliberately unchanged behavior for this phase; a LATER phase
    # is what actually narrows `adapters` above to a genuinely
    # read-only credential, once DataMediator's own read path is ready
    # to move. A caller with no need for a WriteMediator at all (e.g.
    # scripts/serve_requests.py) is free to simply ignore this return
    # value -- building it unconditionally here, rather than lazily on
    # first use, keeps this function's own real behavior simple and
    # predictable regardless of what a given caller goes on to do with
    # it.
    write_adapters = cast(
        "dict[str, ExternalWriteAdapter]", _build_adapters(resolved_silo_configs, _WRITE_ADAPTER_REGISTRY)
    )
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
    # A real, explicit schema-creation step, run once, here, before
    # the WriteLogReader below is ever constructed -- necessary, not
    # defensive boilerplate: this store's schema used to be created
    # lazily by whichever half touched the database first, but a
    # genuinely read-only WriteLogReader structurally cannot run
    # CREATE TABLE (see its own _connection() docstring). Constructing
    # the WRITER first, and opening one real connection through it, is
    # what actually creates the schema -- the same explicit,
    # order-independent guarantee api/app.py's own equivalent step
    # already provides for credentials.db's own four internal stores.
    write_log_writer = WriteLogWriter(data_dir / "write_log.db")
    with write_log_writer._connection():
        pass
    write_log = WriteLogReader(data_dir / "write_log.db")
    # audit_log is genuinely OPTIONAL here, unlike write_log above --
    # log_dir defaults to None (not resolved against data_dir or
    # config_dir, since it's a genuinely third, independent location --
    # see resolve_runtime_paths()'s own docstring). When None,
    # DataMediator's own constructor supplies a real, working default
    # AuditLog itself (see its own docstring for why that default
    # exists and this store is never left without one) -- nothing
    # further to do here in that case.
    audit_log = (
        AuditLog(log_dir / "audit.log", generation=config.generation)
        if log_dir is not None else None
    )
    # The mirror's own last-sync time -- what bounds the read-your-writes
    # overlay (see DataMediator._read_field_with_log_check()). None for a
    # live deployment, which disables the overlay entirely.
    mirror_synced_at = _mirror_last_synced_at(config, data_dir) if config.read_from_mirror else None
    mediator = DataMediator(config.schema, adapters, silo_for_type, config.roles,
                             write_log=write_log, audit_log=audit_log,
                             mirror_synced_at=mirror_synced_at)
    return config, mediator, write_adapters


def load_example_queries(config_dir: Path) -> list[dict]:
    # example_queries.yaml is config-like (ships with the deployment,
    # human-authored), not real runtime data -- always resolved against
    # config_dir, never data_dir.
    raw = load_yaml(config_dir / "example_queries.yaml")
    return raw["examples"]
