"""
Tests for scripts/lint_deployment.py -- see that module's own
docstring for the full reasoning: wraps load_deployment() directly
(pure parsing and validation, zero real file-system side effects
beyond reading the YAML itself), deliberately NOT load_deployment_
bundle() (which opens real adapter connections and creates real
database files on disk).

Builds real, minimal YAML files on disk via tmp_path for each test --
this project has no existing dedicated test file for load_deployment()
itself to reuse fixtures from (it's only ever been exercised
implicitly, through real deployment fixtures elsewhere), so these
tests double as the first direct coverage of load_deployment()'s own
success/failure paths too, not just this script's thin wrapper around
them.
"""

import subprocess
import sys

import pytest

from scripts.lint_deployment import lint_deployment

VALID_CONFIG_YAML = """
llm:
  provider: ollama
  connection: {base_url: "http://localhost:11434"}
  step_model: llama3
  synthesis_model: llama3
agent:
  max_hops: 5
  max_consecutive_duplicates: 2
  max_consecutive_invalid_steps: 2
"""

VALID_DATA_SILOS_YAML = """
data_silos:
  primary_sql:
    adapter: sqlite
    connection: {path: primary.db}
"""

VALID_ONTOLOGY_YAML = """
object_types:
  Widget:
    storage: {silo: primary_sql, table: widgets, id_column: widget_id}
    id_field: widget_id
    security: {field: region}
    fields:
      region: {type: data}
      name: {type: data}
"""

VALID_POLICY_YAML = """
security_attribute: region
roles:
  viewer:
    allowed_actions:
      - read:Widget
      - read:Widget.widget_id
      - read:Widget.name
users:
  alice:
    region: us-west
    role: viewer
"""


def _write_deployment(tmp_path, config=VALID_CONFIG_YAML, ontology=VALID_ONTOLOGY_YAML, policy=VALID_POLICY_YAML,
                       data_silos=VALID_DATA_SILOS_YAML):
    (tmp_path / "config.yaml").write_text(config)
    (tmp_path / "ontology_schema.yaml").write_text(ontology)
    (tmp_path / "policy.yaml").write_text(policy)
    (tmp_path / "data_silos.yaml").write_text(data_silos)
    return tmp_path


def test_valid_deployment_returns_true_and_prints_a_summary(tmp_path, capsys):
    _write_deployment(tmp_path)

    result = lint_deployment(tmp_path)

    assert result is True
    out = capsys.readouterr().out
    assert "VALID" in out
    assert "1 object type(s)" in out
    assert "1 role(s)" in out


def test_missing_config_directory_returns_false(tmp_path, capsys):
    result = lint_deployment(tmp_path / "does_not_exist")

    assert result is False
    out = capsys.readouterr().out
    assert "INVALID" in out
    assert "Cannot read config" in out


def test_missing_data_silos_file_returns_false(tmp_path, capsys):
    # A genuinely NEW failure mode after data_silos.yaml was split out
    # of config.yaml into its own, fourth required file -- worth its
    # own direct coverage, not just assumed to be handled by the
    # existing generic OSError catch-all. The other three files are
    # all present and valid; only data_silos.yaml is missing.
    (tmp_path / "config.yaml").write_text(VALID_CONFIG_YAML)
    (tmp_path / "ontology_schema.yaml").write_text(VALID_ONTOLOGY_YAML)
    (tmp_path / "policy.yaml").write_text(VALID_POLICY_YAML)

    result = lint_deployment(tmp_path)

    assert result is False
    out = capsys.readouterr().out
    assert "INVALID" in out
    assert "Cannot read config" in out


def test_malformed_yaml_returns_false(tmp_path, capsys):
    _write_deployment(tmp_path, config="this: is: not: valid: yaml: [")

    result = lint_deployment(tmp_path)

    assert result is False
    out = capsys.readouterr().out
    assert "INVALID" in out
    assert "Malformed YAML" in out


def test_missing_required_key_returns_false(tmp_path, capsys):
    # load_deployment()'s own required-key try/except -- a genuinely
    # different failure mode from an action_type-specific or role-
    # specific validation error, and worth its own direct coverage.
    # `provider`, not `step_model`: the llm model keys now have their
    # own dedicated validation with a more specific message (see
    # _resolve_models()), so they no longer reach the generic
    # required-key handler this test exists to cover.
    broken_config = VALID_CONFIG_YAML.replace("provider: ollama", "")
    _write_deployment(tmp_path, config=broken_config)

    result = lint_deployment(tmp_path)

    assert result is False
    out = capsys.readouterr().out
    assert "INVALID" in out
    assert "Missing expected key" in out


def test_action_type_missing_sub_writes_returns_false(tmp_path, capsys):
    # Directly proves this script catches the exact real gap that
    # motivated it in the first place -- see core/ontology/
    # action_types.py's own AI-notes for the full history: an
    # action_type missing "sub_writes" used to pass load-time
    # validation and crash confusingly on first real use.
    broken_ontology = VALID_ONTOLOGY_YAML + """
action_types:
  BrokenAction:
    object_type: Widget
    operation: update
"""
    _write_deployment(tmp_path, ontology=broken_ontology)

    result = lint_deployment(tmp_path)

    assert result is False
    out = capsys.readouterr().out
    assert "INVALID" in out
    assert "missing required key 'sub_writes'" in out


def test_role_grant_referencing_unknown_type_returns_false(tmp_path, capsys):
    broken_policy = VALID_POLICY_YAML.replace("read:Widget", "read:Wigdet")
    _write_deployment(tmp_path, policy=broken_policy)

    result = lint_deployment(tmp_path)

    assert result is False
    out = capsys.readouterr().out
    assert "INVALID" in out
    assert "unknown type" in out


# --- line-number enrichment: every collected action_type/role error is
# tagged with the exact file and line it came from, via yaml.compose()'s own
# real source positions (see this script's own module docstring). Each test
# below hand-counts the exact expected line in its own deliberately
# constructed YAML, rather than just asserting "a line number appears
# somewhere" -- the whole point is that the NUMBER itself must be correct,
# not merely present. -------------------------------------------------------

def test_action_type_error_is_tagged_with_its_exact_line(tmp_path, capsys):
    ontology = (
        "object_types:\n"
        "  Widget:\n"
        "    storage: {silo: primary_sql, table: widgets, id_column: widget_id}\n"
        "    id_field: widget_id\n"
        "    security: {field: region}\n"
        "    fields:\n"
        "      region: {type: data}\n"
        "action_types:\n"
        "  BrokenAction:\n"  # line 9
        "    object_type: Widget\n"
        "    operation: update\n"
    )
    _write_deployment(tmp_path, ontology=ontology)

    result = lint_deployment(tmp_path)

    assert result is False
    out = capsys.readouterr().out
    assert "(ontology_schema.yaml, line 9)" in out


def test_role_grant_error_is_tagged_with_its_exact_line(tmp_path, capsys):
    policy = (
        "security_attribute: region\n"
        "roles:\n"
        "  viewer:\n"
        "    allowed_actions:\n"
        "      - read:Widget\n"
        "      - read:Wigdet\n"  # line 6 -- the bad one
        "users:\n"
        "  alice: {region: us-west, role: viewer}\n"
    )
    _write_deployment(tmp_path, policy=policy)

    result = lint_deployment(tmp_path)

    assert result is False
    out = capsys.readouterr().out
    assert "(policy.yaml, line 6)" in out


def test_two_bad_grants_in_the_same_role_get_their_own_distinct_lines(tmp_path, capsys):
    policy = (
        "security_attribute: region\n"
        "roles:\n"
        "  viewer:\n"
        "    allowed_actions:\n"
        "      - read:Widget\n"
        "      - read:Wigdet\n"        # line 6
        "      - execute:NotReal\n"    # line 7
        "users:\n"
        "  alice: {region: us-west, role: viewer}\n"
    )
    _write_deployment(tmp_path, policy=policy)

    result = lint_deployment(tmp_path)

    assert result is False
    out = capsys.readouterr().out
    assert "(policy.yaml, line 6)" in out
    assert "(policy.yaml, line 7)" in out


def test_find_yaml_position_returns_none_for_a_path_that_does_not_exist():
    from scripts.lint_deployment import _find_yaml_position
    assert _find_yaml_position("a:\n  b: 1\n", ["a", "does_not_exist"]) is None


# --- edge cases found by direct, empirical testing against real YAML/config-
# validator failure modes, not just reasoned about -- see this script's own
# AI-notes for the full history of each one. ---------------------------------

def test_empty_yaml_file_returns_false_not_a_crash(tmp_path, capsys):
    # yaml.safe_load() on a 0-byte file returns None, not {} -- used
    # to crash with a raw, unhandled AttributeError instead of a
    # clean INVALID message.
    (tmp_path / "config.yaml").write_text("")
    (tmp_path / "ontology_schema.yaml").write_text(VALID_ONTOLOGY_YAML)
    (tmp_path / "policy.yaml").write_text(VALID_POLICY_YAML)

    result = lint_deployment(tmp_path)

    assert result is False
    out = capsys.readouterr().out
    assert "INVALID" in out


def test_config_dir_pointing_at_a_file_returns_false_not_a_crash(tmp_path, capsys):
    # NotADirectoryError is a SIBLING of FileNotFoundError under
    # OSError, not a subclass -- catching only FileNotFoundError
    # silently missed this entirely.
    a_file = tmp_path / "not_a_directory"
    a_file.write_text("")

    result = lint_deployment(a_file)

    assert result is False
    out = capsys.readouterr().out
    assert "INVALID" in out
    assert "Cannot read config" in out


def test_duplicate_object_type_key_is_rejected(tmp_path, capsys):
    # PyYAML's own long-standing, still-open bug (github.com/yaml/
    # pyyaml/issues/165): silently keeps only the LAST occurrence of a
    # repeated mapping key, zero warning. Fixed at the source in
    # core/config.py; this proves the fix reaches all the way through
    # to this script's own output, not just core/config.py in
    # isolation.
    duplicated_ontology = VALID_ONTOLOGY_YAML + """
  Widget:
    storage: {silo: primary_sql, table: OTHER_TABLE, id_column: widget_id}
    id_field: widget_id
    security: {field: region}
    fields:
      region: {type: data}
"""
    _write_deployment(tmp_path, ontology=duplicated_ontology)

    result = lint_deployment(tmp_path)

    assert result is False
    out = capsys.readouterr().out
    assert "INVALID" in out
    assert "duplicate key" in out


def test_role_name_that_looks_like_a_yaml_boolean_is_rejected(tmp_path, capsys):
    # The "Norway problem" -- an unquoted role name "no" resolves to
    # the Python boolean False, not the string "no". Confirmed
    # directly (not assumed) that BOTH the role's own definition and a
    # user's "role: no" reference coerce IDENTICALLY, so they still
    # match each other and this would otherwise say VALID for a
    # genuinely broken config -- a real, database-backed user with the
    # TRUE string role "no" would silently fail every authorize()
    # check, forever, with no error anywhere.
    broken_policy = VALID_POLICY_YAML.replace("viewer", "no")
    _write_deployment(tmp_path, policy=broken_policy)

    result = lint_deployment(tmp_path)

    assert result is False
    out = capsys.readouterr().out
    assert "INVALID" in out
    assert "not a string" in out


def test_multiple_independent_action_type_problems_are_all_reported(tmp_path, capsys):
    # load_deployment() itself stays fail-fast (correct for a real
    # deployment starting up) -- this script specifically collects
    # every genuinely independent problem instead, so an admin sees
    # all of them in one pass, not one fix-and-rerun cycle at a time.
    broken_ontology = VALID_ONTOLOGY_YAML + """
action_types:
  BrokenActionOne:
    object_type: Widget
    operation: update
  BrokenActionTwo:
    object_type: Widget
    operation: update
"""
    _write_deployment(tmp_path, ontology=broken_ontology)

    result = lint_deployment(tmp_path)

    assert result is False
    out = capsys.readouterr().out
    assert "BrokenActionOne" in out
    assert "BrokenActionTwo" in out


def test_multiple_bad_grants_within_the_same_role_are_all_reported(tmp_path, capsys):
    # Goes a level DEEPER than per-action-type/per-role collection --
    # verified directly that a SINGLE role with two genuinely
    # independent bad grants would otherwise only ever surface its own
    # first one, since validate_roles()'s internal loop over one
    # role's allowed_actions is itself eager-fail. A role's own grant
    # list is often the largest, most error-prone thing in a real
    # deployment.
    #
    # Directly constructed, not built via VALID_POLICY_YAML.replace()
    # -- "read:Widget" is also a PREFIX of "read:Widget.widget_id"/
    # "read:Widget.name", both also present in VALID_POLICY_YAML, so a
    # naive .replace() there matches all three, not just the one
    # intended (found directly, by running this test and seeing THREE
    # roles' worth of errors instead of one).
    broken_policy = (
        "security_attribute: region\n"
        "roles:\n"
        "  viewer:\n"
        "    allowed_actions:\n"
        "      - read:Wigdet\n"
        "      - execute:TotallyFakeAction\n"
        "users:\n"
        "  alice: {region: us-west, role: viewer}\n"
    )
    _write_deployment(tmp_path, policy=broken_policy)

    result = lint_deployment(tmp_path)

    assert result is False
    out = capsys.readouterr().out
    assert "unknown type 'Wigdet'" in out
    assert "unknown action type 'TotallyFakeAction'" in out


def test_no_argument_resolves_config_dir_from_environment(tmp_path, capsys, monkeypatch):
    # The default-path behavior -- matches scripts/run_deployment.py's
    # own established ELYSIUM_CONFIG_DIR convention (see resolve_
    # runtime_paths()), resolved lazily inside lint_deployment() when
    # no explicit config_dir is given, not baked in at import time.
    _write_deployment(tmp_path)
    monkeypatch.setenv("ELYSIUM_CONFIG_DIR", str(tmp_path))

    result = lint_deployment()

    assert result is True
    out = capsys.readouterr().out
    assert str(tmp_path) in out


@pytest.mark.parametrize("cli_exit_expectation", [True, False])
def test_main_exits_with_the_right_code(tmp_path, cli_exit_expectation):
    # __main__'s own sys.exit(0 if ok else 1) -- run as a real
    # subprocess to prove the exit code actually propagates, not just
    # that lint_deployment() itself returns the right bool (already
    # covered by every test above).
    if cli_exit_expectation:
        _write_deployment(tmp_path)
    # else: leave tmp_path empty -- config.yaml missing, guaranteed invalid.

    result = subprocess.run(
        [sys.executable, "-m", "scripts.lint_deployment", str(tmp_path)],
        capture_output=True, text=True, cwd=".",
    )

    assert (result.returncode == 0) == cli_exit_expectation


# --- submission_criteria are validated at load, not at proposal time ---
#
# These two exist because validate_action_type_criteria() is a SEPARATE
# call from validate_action_types() -- core/ontology/action_types.py may
# not import core/ontology/submission_criteria.py, they are siblings in
# core.ontology's layering. A separate call can be forgotten, so this is
# the test that fails if it ever is.

_ONTOLOGY_WITH_CRITERION = """
object_types:
  Widget:
    storage: {silo: primary_sql, table: widgets, id_column: widget_id}
    id_field: widget_id
    security: {field: region}
    fields:
      region: {type: data}
      name: {type: data}
      status: {type: data}
action_types:
  RenameWidget:
    affected_object_types: [Widget]
    parameters:
      widget_id: {type: object_reference, object_type: Widget, required: true}
      new_name: {type: string, required: true}
    sub_writes:
      - object_type: Widget
        object_id: parameter.widget_id
        operation: update
        submission_criteria:
          - description: Widget must be active to rename it
            check: %s
            field: status
            operator: equals
            value: active
        mutations:
          - set: {property: name, value: parameter.new_name}
"""


def test_lint_accepts_a_well_formed_submission_criterion(tmp_path, capsys):
    # The control: without this, the rejection test below could pass
    # because the ontology is malformed for some unrelated reason.
    _write_deployment(tmp_path, ontology=_ONTOLOGY_WITH_CRITERION % "current_state")

    assert lint_deployment(tmp_path) is True


def test_lint_rejects_a_misspelled_check_kind(tmp_path, capsys):
    # Before this validation existed, `currentstate` linted clean,
    # started clean, and failed on the first real user's write.
    _write_deployment(tmp_path, ontology=_ONTOLOGY_WITH_CRITERION % "currentstate")

    result = lint_deployment(tmp_path)

    assert result is False
    assert "currentstate" in capsys.readouterr().out


def test_a_bad_criterion_is_reported_with_its_position_in_the_file(tmp_path, capsys):
    # THE CALL SITE THIS PROTECTS, and it is not the one it looks like.
    # load_deployment() raises first, so the message alone appears
    # whether or not _collect_action_type_and_role_errors() also
    # validates criteria -- confirmed by dropping that call and
    # watching every other test still pass.
    #
    # What only the collecting pass produces is the POSITION suffix.
    # That pass exists to turn load_deployment()'s bare ValueError into
    # an error naming a file and a line, and to report EVERY bad entry
    # rather than the first. Asserting on the position is therefore the
    # assertion that fails if the collecting pass stops validating
    # criteria.
    _write_deployment(tmp_path, ontology=_ONTOLOGY_WITH_CRITERION % "currentstate")

    lint_deployment(tmp_path)

    out = capsys.readouterr().out
    assert "ontology_schema.yaml" in out
    assert "line" in out


def test_every_bad_criterion_is_reported_not_just_the_first(tmp_path, capsys):
    # The whole reason the collecting pass exists: load_deployment() is
    # fail-fast, so relying on it alone would fix one criterion, re-run,
    # and find the next -- one round trip per mistake.
    two_bad = _ONTOLOGY_WITH_CRITERION % "currentstate" + """
  RetireWidget:
    affected_object_types: [Widget]
    parameters:
      widget_id: {type: object_reference, object_type: Widget, required: true}
    sub_writes:
      - object_type: Widget
        object_id: parameter.widget_id
        operation: update
        submission_criteria:
          - description: Widget must be active to retire it
            check: current_state
            field: status
            operator: equalz
            value: active
        mutations:
          - set: {property: status, value: retired}
"""
    _write_deployment(tmp_path, ontology=two_bad)

    lint_deployment(tmp_path)

    out = capsys.readouterr().out
    assert "currentstate" in out, "first bad criterion missing"
    assert "equalz" in out, "second bad criterion missing -- only the first was reported"


# --- the two model forms ---
#
# A deployment names EITHER `model` (one model for every call) or both
# `step_model` and `synthesis_model`. The single form exists because
# two models mean Ollama loading and evicting between them, measured
# at 12-47 seconds per load on CPU-only hardware.

_ONE_MODEL_CONFIG = VALID_CONFIG_YAML.replace(
    "  step_model: llama3\n  synthesis_model: llama3\n", "  model: llama3\n")


def test_a_deployment_may_name_one_model_for_every_call(tmp_path, capsys):
    _write_deployment(tmp_path, config=_ONE_MODEL_CONFIG)

    assert lint_deployment(tmp_path) is True


def test_naming_both_forms_is_rejected_rather_than_resolved(tmp_path, capsys):
    # Not resolved by precedence: a deployment setting both has two
    # plausible intentions and no way to signal which, and silently
    # preferring one means the next debugging session starts from a
    # false belief about which model actually ran.
    both = VALID_CONFIG_YAML.replace("  step_model: llama3\n", "  model: mistral\n  step_model: llama3\n")
    _write_deployment(tmp_path, config=both)

    assert lint_deployment(tmp_path) is False
    assert "never both forms" in capsys.readouterr().out


def test_naming_only_half_the_split_form_is_rejected(tmp_path, capsys):
    half = VALID_CONFIG_YAML.replace("  synthesis_model: llama3\n", "")
    _write_deployment(tmp_path, config=half)

    assert lint_deployment(tmp_path) is False
    out = capsys.readouterr().out
    assert "synthesis_model" in out
    assert "step_model" not in out.split("missing")[1][:40], "should name only the absent key"
