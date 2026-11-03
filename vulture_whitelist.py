"""
vulture_whitelist.py  (tells Vulture these names are genuinely used,
even though it can't see how)

Vulture does whole-program analysis by NAME, not by call graph -- it's
what makes it able to catch a function nothing calls anywhere in the
project (something pyflakes/Ruff's local-scope F401/F841 genuinely
cannot do). But that same by-name approach means it has no way to see
three real, common patterns where a name IS used, just not by a direct
Python call Vulture can trace:
  - a framework invoking something via decorator registration (FastAPI
    routes, dispatched by the router at request time, not by any
    Python code calling the function's name directly)
  - a name accessed dynamically through a mock/library object rather
    than declared and read locally (unittest.mock's return_value/
    side_effect, sqlite3.Connection's row_factory)
  - a name declared as part of an interface/contract that not every
    consumer needs yet (this project's own DataSiloAdapter/MemoryEntry
    fields)

Every entry below was verified directly against this codebase before
being added here -- confirmed either genuinely used elsewhere (just
not in a way Vulture can trace) or a deliberate, documented "declared
but not yet consumed" field, never added just to silence a warning
without checking first.

Run `vulture` (config: pyproject.toml's [tool.vulture]) to check.
"""

# --- Reflection-read names left after route handlers moved out. FastAPI
# route handlers need no entry: pyproject.toml's `ignore_decorators`
# ("@router.*", "@app.*") covers every decorator-registered handler.
# What remains is read by pydantic or a library, never called by name.
# Frozen sets (formerly planning-file item 17, saved selections): routes FastAPI calls and response fields
# pydantic reads by reflection, the same reason as above.
publication_retained
not_shown
# Editing config.yaml from the UI: routes reached by HTTP, and ruamel's
# own setting, which ruamel reads.
preserve_quotes
# WIRED-3: a response field pydantic reads by reflection.
high_confidence
group_hidden  # R58: MergeProposalResponse, set through **_group_fields
preselected_by  # R57: MergeProposalResponse, set through **_preselection
# AL-11: urllib3 reads ConnectionCls and pool_classes_by_scheme; the
# test server's do_POST is called by http.server.
ConnectionCls
pool_classes_by_scheme
do_POST
# BULK-1: a response field pydantic reads by reflection.
max_objects
# R12: pydantic calls the validator by reflection.
_one_label_is_a_list
left_only
right_only
# The response model's fields: pydantic reads them by reflection, so
# every one of them looks unreferenced from here.
bronze_snapshot_id

# --- unittest.mock attribute assignment -- `some_mock.return_value = x`
# / `some_mock.side_effect = fn` are how tests configure a MagicMock;
# the mock framework reads them internally at call time, not this
# project's own code, so Vulture can never see the "usage."
_.return_value
_.side_effect

# --- pytest's own special module-level variable -- marks every test
# in a file with the listed markers; read by pytest's collection
# machinery, not by any of this project's own code.
pytestmark

# --- stdlib sqlite3.Connection's own attribute -- `conn.row_factory =
# sqlite3.Row` configures how sqlite3 itself constructs result rows;
# consumed inside the sqlite3 C extension, not Python code Vulture can
# trace.
_.row_factory

# --- DataSiloAdapter interface fields (core/ontology/interface.py) --
# declared, deliberate contract fields, verified directly before being
# whitelisted (not assumed): neither is actually read by any runtime
# logic anywhere in this codebase today -- both are genuine, forward-
# looking scaffolding, declared ahead of the capability that will
# consume them (a read-concurrency limiter, and a real conditional-
# write dispatch that branches on this flag) rather than leftovers
# from something removed. Re-verify with a real grep before assuming
# this reasoning still holds if either is ever actually wired up.
max_concurrent_reads
supports_atomic_conditional_write

# --- core/ontology/write_mediator.py's own _ReadWriteAdapter -- a
# real, genuinely used TYPE_CHECKING-only intersection type, referenced
# only via STRING-quoted annotations (adapter: "_ReadWriteAdapter") so
# it never needs importing at real runtime. Vulture's own by-name
# analysis can't trace a string-quoted forward reference the same way
# it can't trace the other dynamic-attribute patterns documented above
# -- confirmed directly (a real grep shows three real, live uses) that
# this is a genuine false positive, not actual dead code.
_ReadWriteAdapter

# --- Pydantic response_model fields (api/routes.py) -- declared as real
# model attributes and consumed entirely by Pydantic itself during
# response serialization, never read by this project's own Python code,
# so Vulture's by-name analysis cannot see the usage. Same real pattern
# as the mock/row_factory entries above. Verified directly before
# whitelisting: each one appears in a genuine response captured from a
# running server, and REMOVING any of them would silently strip that
# field from what callers receive -- which is precisely the filtering
# behavior these models exist to provide.
default_to_current_object
# DeploymentConfigResponse (api/routes.py): read by FastAPI's
# serialiser from the returned dict, never by our own code -- the same
# reason every other response-model field below is here.
is_identifier
# SiloStatusResponse.primary_for -- of the types a silo backs, the ones
# it IS. R6: without it "one field of Customer stopped refreshing" and
# "all of Customer did" arrive as the same word.
primary_for
object_type_count
action_type_count
role_names
total_matches
display_name
plural_display_name
next_page_token
color

# pydantic reads model_config off the class itself -- a name the
# library looks up, never one this project's own code calls. See
# core/ontology/submission_criteria.py's Criterion.
model_config

# pydantic calls @model_validator methods itself; nothing in this
# project references the name. See Criterion in core/ontology/
# submission_criteria.py.
_user_field_must_be_a_real_user_attribute

# tests/unit/test_reload.py's autouse fixture -- pytest calls it by
# registration, never by name.
_restore_sighup

# ConfigHistoryResponse / ConfigDiffResponse fields (api/routes.py) --
# read by FastAPI's serialiser from the returned dict, as with every
# other response model above.
current_generation
changed_files

# AwaitingWriteResponse fields (api/routes.py) -- read by FastAPI's
# serialiser from the returned dicts, as with every response model.
object_count

# AwaitingWriteResponse's own flags (api/routes.py) -- serialised by
# FastAPI from the returned dict, like every other response field.
awaiting_your_review
proposed_by_you

# WriteDetailResponse / FieldChangeResponse / ObjectChangeResponse
# fields (api/routes.py) -- serialised by FastAPI from the returned
# dicts, as with every other response model.
proposed_value
has_redacted_fields

# AwaitingWriteResponse.undeclared_fields (api/routes.py) -- serialised
# by FastAPI from the returned dict, like every other response field.
undeclared_fields

# AwaitingWriteResponse.duplicate_count (api/routes.py) -- serialised by
# FastAPI from the returned dict, like every other response field.
duplicate_count

# SchemaFieldResponse.decimal_places (api/routes.py) -- serialised by
# FastAPI from the returned dict, like every other response field.
decimal_places

# MetricsResponse / SlowRouteResponse fields (api/routes.py) --
# serialised by FastAPI from the returned dict, like every other
# response model here.
p99_ms
p50_ms
rate_per_second
error_ratio

# AwaitingWriteResponse's task counts (api/routes.py) -- serialised by
# FastAPI from the returned dict, like every other response field here.
tasks_total
tasks_you_may_decide
tasks_approved

# MirrorStateResponse / admin_mirror_route (api/routes.py) -- a FastAPI
# route and its response model, reached by decorator and serialised by
# field name, like every other endpoint in that file.
reading_from_mirror

# MirrorTableState's attempt fields (api/routes.py) -- serialised by
# FastAPI from the returned dict, like every other response field.
last_attempt_at
last_attempt_outcome
last_attempt_detail

# notifications_route / mark_notification_seen_route and their response
# models (api/routes.py) -- FastAPI routes, reached by decorator.
unseen

# A pydantic field read only as a dict key, like `created_at` and
# `presentation` above it. WIRED-1: the FIELD NAMES a caller can no
# longer filter on, named rather than dropped silently.
disabled_conditions

# reminder routes and their models (api/routes.py, 17 October) --
# FastAPI routes, and response fields read by the Reminders tab.
repeats
late_after_minutes

# VisibleActionTypeResponse.automatable (api/routes.py) -- a response
# field, read by the Watch dialog rather than by Python.
automatable

# __getattr__ (api/app.py) -- a module-level __getattr__ (PEP 562), called
# by Python for `elysium.api.app.app`; uvicorn reaches it by name.
__getattr__

# should_exit (tests/integration/test_graceful_shutdown.py) -- read by
# uvicorn.Server itself; setting it is what its SIGTERM handler does.
should_exit

# claude_on_path (tests/unit/test_model_deadline_and_usage.py) -- a fixture
# named in @pytest.mark.usefixtures, which vulture cannot see.
claude_on_path

# Test doubles for the LLM client protocol (B1 findings). model_name()
# is part of the interface every adapter implements and the code under
# test may call, so the fakes provide it even though these particular
# tests do not reach it.
model_name

# MirrorTableState fields (the invisible-quarantine risk). Pydantic response-model
# attributes, set by name in the route's dict and read by the UI --
# vulture sees neither side.
quarantined_rows
quarantine_reason
# The per-rule breakdown beside them, added when docs/ui/development.md 16.4's
# DISTRIBUTION pillar needed a divisible row count. Same reason
# vulture cannot see them: set by name in the route's dict, read in
# TypeScript.
quarantine_rules
quarantine_last_detected_at
# The rules that WARNED rather than held, from the last run. Same
# reason vulture cannot see them: set by name in the route's dict,
# read in TypeScript.
expectation_warnings
# TypeFreshnessResponse's window (docs/ui/development.md 16.6). Same reason: set by
# name in the route's dict, read in TypeScript.
warn_after_hours
fail_after_hours
# DeploymentConfigResponse's declared cadence -- the number every
# freshness window derives from. Set by name in the config route's
# dict, read in TypeScript.
sync_interval_hours

# tests/unit/test_snapshot_expiry.py -- an autouse fixture, called by
# pytest rather than by name.
_no_margin

# tests/unit/test_a_bronze_failure_never_serves_stale_data.py -- a
# fixture named in test signatures, which vulture reads as unused.
_bronze_fails

# ---------------------------------------------------------------
# FROM THE SIMULATOR (sim/), moved here when it adopted Elysium's
# toolchain. Unchanged, reasons and all.
# ---------------------------------------------------------------

# do_GET for a GET request and log_message for every log line, neither
# through a reference Vulture can see, so both read as dead. The
# `format` parameter is part of log_message's signature in the base
# class and is deliberately ignored: the override exists precisely to
# silence http.server's default stderr logging, which would otherwise
# bury a test run's real output.
do_GET
log_message
# R15: config-response fields pydantic reads by reflection.
lineage_service
lineage_namespace
# R2: a config-response field pydantic reads by reflection.
incremental_tables
# Forecasts of totals (R68): a route reached by HTTP.
target_label
# DEV_UI 13.3, who can see a type: a route reached by HTTP, and a
# response field pydantic reads by reflection.
no_access
# DEV_UI 13.5, a role change in access terms: a route reached by HTTP,
# and response fields pydantic reads by reflection.
from_
removes_role
actions_gained
actions_lost
other_gained
other_lost
# DEV_UI 13.7, access labels and the approval queue: routes reached by HTTP.
needs_approval  # LabelPreviewResponse.needs_approval, read by pydantic
# The ontology's shape, adding a field: routes reached by HTTP.
source_has_column  # NewFieldConsequence, read by the browser
source_has_table  # NewTypePreviewResponse, read by the browser
columns_missing  # NewTypePreviewResponse, read by the browser
columns_checked  # NewTypePreviewResponse, read by the browser
not_listed  # UsedByResponse, read by the browser
deprecation  # SchemaFieldResponse / VisibleObjectTypeResponse, read by the browser
status_inherited_from  # SchemaFieldResponse, read by the browser
can_remove  # RemovalPreviewResponse, read by the browser
hidden_blockers  # RemovalPreviewResponse, read by the browser
to_type  # RetypePreviewResponse, read by the browser
hidden_places  # RetypePreviewResponse, read by the browser
# DEV_UI 13.7, putting an earlier version back: routes reached by HTTP.
roles_in_store  # RestorePreviewResponse.roles_in_store, read by pydantic
extracts  # EnrichmentRecipeResponse.extracts, read by pydantic
# R45, search by meaning: routes reached by HTTP.
searchable_by_meaning  # VisibleObjectTypeResponse.searchable_by_meaning, read by pydantic
# R51: a stored flag's time, read by the review queue.
found_at

# THE EXAMPLE ADD-ON'S SERVER (tests/addons/echo/server.py):
# http.server calls do_<METHOD> by name, reads protocol_version and
# close_connection off the handler.
do_PUT
do_PATCH
do_DELETE
do_HEAD
protocol_version
close_connection

# ADD-ON SERVERS' STATUS (api/routes.py AddonServerRow and
# AddonServersResponse): response-model fields, read by FastAPI to
# serialise and by the System page, never by Python.
next_start_at
addons
# An autouse fixture (tests/integration/test_addon_lifecycle.py): pytest
# applies it to every test in the file by itself, so nothing names it.
quick_back_off

# THE ROLE EDITOR'S REGISTRY (api/routes.py ModulePermission and
# RolesResponse): response-model fields FastAPI serialises and the
# editor reads (roleGrants.ts), never Python.
module_name
module_permissions
unlisted

# THE ADD-ON CONTRACT CHECKS (sdk/python/elysium_addon_checks.py and the
# simulator's copy): test methods of a mixin, collected by pytest from
# each subclass an add-on writes, and an `addon` fixture pytest passes.
test_health_answers_200_once_started
test_a_protected_path_refuses_who_it_cannot_verify_and_takes_who_it_can
test_it_listens_on_loopback_only
test_sigterm_ends_it_within_its_deadline_cleanly
test_it_leaves_when_elysium_does

# PUT/DELETE /admin/ontology-canvas-default (27 October): FastAPI routes,
# called through their decorators -- where everybody's canvas starts. The
# two response fields are read by the UI, not by Python.
shared_positions
can_set_shared

# Retype R1 review fixes (2 November).
rebuild_unknown  # RetypeResponse.rebuild_unknown, read by the browser
rebuild_owed  # MirrorStateResponse / MirrorTableState / MirrorObjectState fields (R2), read by the Mirror panel
rebuild_owed_unknown  # MirrorStateResponse.rebuild_owed_unknown (R2), read by the Mirror panel
broken_catalog  # a pytest fixture taken as a parameter for its effect (tests/integration/test_retype_from_the_ui.py)

# Configuration key models (core/config_schema.py), 3 November. A model
# field exists to NAME a key the loader reads; pydantic walks them by
# model_fields, so no code mentions them by name. Only the ones whose
# name appears nowhere else are listed.
additional_storage  # object type key
allowed_actions  # role key
dependencies  # object type key
on_violation  # field key
outliers  # field key
owner_may_approve_automation  # action type key
semantic_search  # object type key
source_locale  # config.yaml key
submission_criteria  # action and sub_write key
survivorship  # object type and field key
value_type  # field key
via_target_column  # bindings key
zero_dates_as_null  # silo key
two_storages  # pytest fixtures taken as parameters for their effect (tests/integration/test_object_sets_hidden_links.py)
open_transactions  # same file
