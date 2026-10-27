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

# --- FastAPI route handlers -- invoked by the router via @router.post/
# get/delete decorators at request time, never called directly by name
# anywhere in this project's own Python code (even test_api.py goes
# through a TestClient issuing real HTTP requests, not a direct call).
login
logout
logout_all
request_trace_route
# Live updates (api/live_updates.py): a route FastAPI calls.
change_events_route
published_history_route
object_provenance_route
# Beside them because it answers the other half of the same question:
# "where did this ROW come from" versus "why does this FIELD say this".
object_conflicts_route
# Frozen sets (formerly BLOCKING 17, saved selections): routes FastAPI calls and response fields
# pydantic reads by reflection, the same reason everything above is here.
freeze_set_route
list_frozen_sets_route
frozen_set_route
delete_frozen_set_route
publication_retained
not_shown
# Comparing two sets: routes and response fields, the same reason.
compare_sets_route
# The Inbox badge (DEV_UI 15.3): a route, reached by HTTP.
my_inbox_counts_route
# Changes waiting, shown on the object and the set (DEV_UI 15.3).
pending_for_objects_route
unusual_on_objects_route
unusual_review_route
decide_unusual_route
# The ontology canvas's layout (DEV_UI 14): routes, reached by HTTP.
my_ontology_canvas_route
save_my_ontology_canvas_route
# Editing config.yaml from the UI: routes reached by HTTP, and ruamel's
# own setting, which ruamel reads.
config_settings_route
preview_config_settings_route
apply_config_settings_route
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
# R31: routes FastAPI calls.
rule_suggestions_route
scan_rule_suggestions_route
decide_rule_suggestion_route
# BULK-1: a response field pydantic reads by reflection.
max_objects
# E-14, agent memory: routes FastAPI calls.
list_memories_route
create_memory_route
forget_memory_route
# R12: pydantic calls the validator by reflection.
_one_label_is_a_list
combine_sets_route
left_only
right_only
losing_source
chosen_source
recorded_at
# The response model's fields: pydantic reads them by reflection, so
# every one of them looks unreferenced from here, the same way every
# route above looks uncalled.
bronze_snapshot_id
list_notes_route
create_note_route
silos_route
deployment_config_route
reload_route
config_history_route
config_diff_route
awaiting_writes_route
write_detail_route
list_users_route
create_user_route
visible_schema_route
logout_all_for_user
disable_user_route
enable_user_route
delete_user_route
confirm_write_route
search_objects_route
my_profile_route
shell_session_route
shell_modules_route
module_file_route
module_arrangement_route
save_module_arrangement_route
addon_servers_route
addon_server_log_route
restart_addon_server_route
addon_proxy_route
my_visible_apps_route
my_visible_schema_route
get_object_detail_route
my_visible_action_types_route
propose_action_route
acquire_lock_route
refresh_lock_route
release_lock_route
force_release_lock_route
lock_status_route
data_freshness_route
count_objects_route
aggregate_objects_route
search_around_route
object_history_route
health_route

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

# Registered via @app.middleware("http") -- called by FastAPI's own
# internal dispatch mechanism, the same reason every route handler in
# this file already needs a whitelist entry (see the block above):
# never referenced by name anywhere in the Python source itself.
add_security_headers


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
data_type
cardinality
default_to_current_object
disabled
source
# DeploymentConfigResponse (api/routes.py): read by FastAPI's
# serialiser from the returned dict, never by our own code -- the same
# reason every other response-model field below is here.
is_identifier
object_type
column
table
fields
rbac_allowed
mac_allowed
timestamp
author
object_types
# SiloStatusResponse.primary_for -- of the types a silo backs, the ones
# it IS. R6: without it "one field of Customer stopped refreshing" and
# "all of Customer did" arrive as the same word.
primary_for
reachable
failure
silo_names
object_type_count
action_type_count
role_names
total_matches
display_name
plural_display_name
total
next_page_token
entries
batch_id
created_at
operation
color
icon
visibility
checks
link_type

# pydantic reads model_config off the class itself -- a name the
# library looks up, never one this project's own code calls. See
# core/ontology/submission_criteria.py's Criterion.
model_config

# pydantic calls @model_validator methods itself; nothing in this
# project references the name. See Criterion in core/ontology/
# submission_criteria.py.
_user_field_must_be_a_real_user_attribute

# DeploymentGeneration.mirror_snapshots -- read through the frozen
# dataclass in api/routes.py's /config response, which vulture does not
# follow. See core/deployment_loader.py.
mirror_snapshots

# ReloadResponse.changed (api/routes.py) -- read by FastAPI's serialiser
# from the returned dict, never by our own code, the same as every
# other response-model field above.
changed

# tests/unit/test_reload.py's autouse fixture -- pytest calls it by
# registration, never by name.
_restore_sighup

# ConfigHistoryResponse / ConfigDiffResponse fields (api/routes.py) --
# read by FastAPI's serialiser from the returned dict, as with every
# other response model above.
current_generation
generations
changed_files
unchanged
recorded_at

# AwaitingWriteResponse fields (api/routes.py) -- read by FastAPI's
# serialiser from the returned dicts, as with every response model.
proposed_by
object_count

# AwaitingWriteResponse's own flags (api/routes.py) -- serialised by
# FastAPI from the returned dict, like every other response field.
awaiting_your_review
proposed_by_you

# WriteDetailResponse / FieldChangeResponse / ObjectChangeResponse
# fields (api/routes.py) -- serialised by FastAPI from the returned
# dicts, as with every other response model.
readable
current_value
proposed_value
has_redacted_fields

# AwaitingWriteResponse.undeclared_fields (api/routes.py) -- serialised
# by FastAPI from the returned dict, like every other response field.
undeclared_fields

# AwaitingWriteResponse.duplicate_count (api/routes.py) -- serialised by
# FastAPI from the returned dict, like every other response field.
duplicate_count

# LinkCountsResponse.links (api/routes.py) -- serialised by FastAPI
# from the returned dict, like every other response field.
links

# link_counts_route (api/routes.py) -- registered by its @router.get
# decorator, which Vulture cannot see. Every route in this file is
# reached the same way.
link_counts_route
matching_ids_route
export_objects_route

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
slowest_routes
window_seconds
admin_metrics_route
forget_older_than

# TaskApproval.decided_at (core/pending_write_store.py) -- recorded
# now, read by the approvals inbox in step 4. An approval record
# without a timestamp is not an approval record: "who approved this
# and when" is one question, and adding the field later would mean
# every decision taken before then has no answer.
decided_at

# AwaitingWriteResponse's task counts (api/routes.py) -- serialised by
# FastAPI from the returned dict, like every other response field here.
tasks_total
tasks_you_may_decide
tasks_approved

# MirrorStateResponse / admin_mirror_route (api/routes.py) -- a FastAPI
# route and its response model, reached by decorator and serialised by
# field name, like every other endpoint in that file.
reading_from_mirror
admin_mirror_route

# MirrorTableState's attempt fields (api/routes.py) -- serialised by
# FastAPI from the returned dict, like every other response field.
last_attempt_at
last_attempt_outcome
last_attempt_detail

# SearchResponse / ObjectDetailResponse request_id (api/routes.py) --
# serialised by FastAPI, read by whoever wants the access trace.
request_id

# admin_mirror_sync_route / SyncStartedResponse (api/routes.py) -- a
# FastAPI route and its response model, reached by decorator.
admin_mirror_sync_route
started

# notifications_route / mark_notification_seen_route and their response
# models (api/routes.py) -- FastAPI routes, reached by decorator.
notifications_route
mark_notification_seen_route
notifications
unseen

# saved-view routes and their models (api/routes.py) -- FastAPI
# routes, reached by decorator.
saved_views_route
save_view_route
delete_saved_view_route
views
view_id
object_type
query_text
conditions

# trigger routes and their models (api/routes.py) -- FastAPI routes.
triggers_route
create_trigger_route
set_trigger_enabled_route
delete_trigger_route
triggers
trigger_id
above
gained
fell
enabled
# A pydantic field read only as a dict key, like `created_at` and
# `presentation` above it. WIRED-1: the FIELD NAMES a caller can no
# longer filter on, named rather than dropped silently.
disabled_conditions
presentation
action_parameter
action_values
recipient_roles

# reminder routes and their models (api/routes.py, 17 October) --
# FastAPI routes, and response fields read by the Reminders tab.
list_reminders_route
create_reminder_route
cancel_reminder_route
reminders
repeats
late_after_minutes

# VisibleActionTypeResponse.automatable (api/routes.py) -- a response
# field, read by the Watch dialog rather than by Python.
automatable

# GET /roles and its model (api/routes.py) -- a FastAPI route.
roles_route
source
grantable

# Role-change routes and models (api/routes.py) -- FastAPI routes.
propose_role_change_route
role_changes_route
approve_role_change_route
reject_role_change_route
changes
change_id
before
after
proposed_by
proposed_at
grants

# follow_reload (api/app.py) -- registered by @app.middleware, called by Starlette.
follow_reload

# Password routes and models (api/routes.py) -- FastAPI routes.
change_own_password_route
reset_password_route
current_password
new_password

# merge_proposals_route / decide_merge_route (api/routes.py) -- FastAPI
# route handlers, called by the framework through the decorator rather
# than by name. Every other route in the file is reached the same way;
# vulture sees a function nobody calls.
merge_proposals_route
decide_merge_route
example_questions_route

# security_cache_per_request (api/app.py) -- registered by @app.middleware.
security_cache_per_request

# __getattr__ (api/app.py) -- a module-level __getattr__ (PEP 562), called
# by Python for `api.app.app`; uvicorn reaches it by name.
__getattr__

# validation_errors_without_values (api/app.py) -- registered by
# @app.exception_handler.
validation_errors_without_values
# model_unavailable (api/app.py), registered the same way: the 503 an
# unreachable model becomes.
model_unavailable

# should_exit (tests/integration/test_graceful_shutdown.py) -- read by
# uvicorn.Server itself; setting it is what its SIGTERM handler does.
should_exit

# TokenUsage.unreported (core/llm/interface.py) -- read by the tests now,
# and by the query wiring of E-11's second commit.
unreported

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
# The per-rule breakdown beside them, added when DEV_UI.md 16.4's
# DISTRIBUTION pillar needed a divisible row count. Same reason
# vulture cannot see them: set by name in the route's dict, read in
# TypeScript.
quarantine_rules
quarantine_last_detected_at
# The rules that WARNED rather than held, from the last run. Same
# reason vulture cannot see them: set by name in the route's dict,
# read in TypeScript.
expectation_warnings
# TypeFreshnessResponse's window (DEV_UI.md 16.6). Same reason: set by
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
format
# R15: config-response fields pydantic reads by reflection.
lineage_service
lineage_namespace
# R16: a route FastAPI calls.
data_contract_route
# R38: a response field pydantic reads by reflection.
field_sources
# The help assistant: a route FastAPI calls and its request model.
help_route
# R2: a config-response field pydantic reads by reflection.
incremental_tables
# R41/R38: a response field pydantic fills from visible_schema by name.
inferred
# Enrichment review (R41): routes, reached by HTTP.
enrichment_recipes_route
decide_enrichment_recipe_route
# Prediction review (R48): routes reached by HTTP, and a response field
# pydantic reads by reflection.
prediction_proposals_route
decide_prediction_proposal_route
# Forecasts of totals (R68): a route reached by HTTP.
forecast_route
target_label
# DEV_UI 13.3, who can see a type: a route reached by HTTP, and a
# response field pydantic reads by reflection.
who_can_see_route
no_access
# DEV_UI 13.5, a role change in access terms: a route reached by HTTP,
# and response fields pydantic reads by reflection.
preview_role_change_route
from_
to  # TypeAccessChange.to, read by pydantic
removes_role
actions_gained
actions_lost
other_gained
other_lost
# DEV_UI 14.5, counts on the ontology canvas: a route reached by HTTP.
my_type_counts_route
# DEV_UI 13.7, describing the ontology: routes reached by HTTP.
ontology_descriptions_route
preview_ontology_descriptions_route
apply_ontology_descriptions_route
# DEV_UI 13.7, access labels and the approval queue: routes reached by HTTP.
preview_labels_route
apply_labels_route
config_proposals_route
approve_config_proposal_route
reject_config_proposal_route
needs_approval  # LabelPreviewResponse.needs_approval, read by pydantic
# The ontology's shape, adding a field: routes reached by HTTP.
preview_new_fields_route
apply_new_fields_route
source_has_column  # NewFieldConsequence, read by the browser
new_type_sources_route
source_tables_route
source_columns_route
preview_new_type_route
apply_new_type_route
source_has_table  # NewTypePreviewResponse, read by the browser
columns_missing  # NewTypePreviewResponse, read by the browser
columns_checked  # NewTypePreviewResponse, read by the browser
used_by_route
referrers  # UsedByResponse, read by the browser
not_listed  # UsedByResponse, read by the browser
linkable_types_route
linkable_type_columns_route
preview_new_link_route
apply_new_link_route
problems  # NewLinkPreviewResponse, read by the browser
checked  # NewLinkPreviewResponse, read by the browser
# DEV_UI 13.7, putting an earlier version back: routes reached by HTTP.
preview_restore_route
restore_route
roles_in_store  # RestorePreviewResponse.roles_in_store, read by pydantic
extracts  # EnrichmentRecipeResponse.extracts, read by pydantic
# R45, search by meaning: routes reached by HTTP.
related_in_meaning_route
similar_objects_route
offered  # MeaningResponse.offered, read by pydantic
text_fields  # MeaningResponse.text_fields, read by pydantic
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
# GET /roles/names (24 October): a FastAPI route, called through its
# decorator -- the role names an account administrator needs, which
# /config gave until it became the server's.
role_names_route

# PUT/DELETE /admin/ontology-canvas-default (27 October): FastAPI routes,
# called through their decorators -- where everybody's canvas starts. The
# two response fields are read by the UI, not by Python.
save_shared_ontology_canvas_route
clear_shared_ontology_canvas_route
shared_positions
can_set_shared
