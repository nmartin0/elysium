"""
lint_deployment.py  (check a deployment's config is valid -- WITHOUT
starting the service)

Wraps load_deployment() and its own constituent validation pieces
directly -- deliberately NOT load_deployment_bundle(). See that
function's own docstring: load_deployment() itself is pure parsing
and validation only (reads the YAML files, runs core/config.py's own
duplicate-key-rejecting loader, core/deployment_loader.py's own
validate_identifier_types(), core/ontology/action_types.py's
validate_action_types(), and core/intermediate_layer/policy_
validation.py's validate_roles()) -- zero file-system side effects
beyond reading the YAML itself. load_deployment_bundle() is the one
that actually opens real adapter connections and creates real write_
log.db/credentials.db files on disk. This script exists specifically
because that separation already existed -- an admin checking whether
a new or edited config.yaml/ontology_schema.yaml/policy.yaml/data_
silos.yaml is valid shouldn't need to touch any real database, or risk
creating stray database files in the wrong place, just to find out.

COLLECTS EVERY action_type's own error and EVERY role's own error,
not just the first one found -- load_deployment() itself stays
FAIL-FAST by design (matching its own use for a real deployment
starting up: it either starts cleanly or it doesn't, and there's no
benefit to a running service knowing about every OTHER, unrelated
problem in a config it's already refusing to load). This script is
different: an admin iterating on a config with several genuinely
independent mistakes (a few typo'd action types, a few typo'd role
grants) benefits from seeing all of them in one pass, not
fixing-and-rereading one at a time. Structural/prerequisite problems
(malformed YAML, a missing required key, a non-string identifier) stay
fail-fast even here -- there's typically only ever one such problem at
a time, and action_type/role validation cannot meaningfully run at all
until it's fixed.

EVERY collected action_type/role error is enriched with the exact
FILE and LINE it came from, e.g. "(ontology_schema.yaml, line 47)" --
via yaml.compose(), which returns PyYAML's own raw Node tree (real
source positions attached to every node) rather than the fully
CONSTRUCTED Python objects load_deployment() itself works with, which
lose that information entirely once built. _find_yaml_position()
walks this node tree by a KEY PATH (e.g. ["roles", "viewer",
"allowed_actions", 3]) built from exactly the same action_type_name/
role_name/grant-index this script already knows at the point each
error is caught -- prototyped and verified directly against a real,
nested, multi-line YAML file (including the specific list-index case)
before being wired in, not assumed to work. Deliberately scoped to
the two cases that cover the overwhelming majority of real,
iteratively-discovered mistakes (a broken action_type, a bad grant
within a role) -- NOT extended to the structural/identifier-type
errors above, where the position of a coerced, no-longer-string key
is a genuinely harder problem; see this file's own AI-notes for why.

NEVER crashes with a raw, unhandled traceback -- every realistic
failure mode was found and tested directly, not just reasoned about:
an empty (0-byte) YAML file (yaml.safe_load() returns None, not {});
config_dir pointing at a file instead of a directory
(NotADirectoryError, a SIBLING of FileNotFoundError under OSError, not
a subclass -- catching only FileNotFoundError specifically misses it);
an unreadable directory (PermissionError, same OSError family). Caught
via a broad `except OSError`, covering the whole family at once, plus
a final, generic `except Exception` fallback so that even a genuinely
unanticipated failure mode still produces a clean "INVALID" message
instead of a scary traceback -- see this file's own AI-notes for why
that fallback is deliberately NOT considered a substitute for finding
and specifically handling every REAL failure mode directly.

Exit code 0 if valid, 1 if not -- usable directly in a pre-deploy CI
step or a pre-commit hook, not just interactively.

Run from the project root, against the real deployment (using the
same ELYSIUM_CONFIG_DIR resolution run_deployment.py itself uses):
    python3 -m scripts.lint_deployment

Or against ANY other directory -- e.g. to check a new config before
ever copying it into deployment/etc/ at all:
    python3 -m scripts.lint_deployment /path/to/candidate/config
"""

import sys
from pathlib import Path

import yaml

from core.deployment_loader import (
    load_deployment,
    resolve_runtime_paths,
    validate_identifier_types,
)
from core.intermediate_layer.policy_validation import validate_roles
from core.ontology.action_types import validate_action_types


def _report_invalid(config_dir: Path, errors: list[str]) -> bool:
    print(f"INVALID -- {config_dir}")
    for error in errors:
        print(f"  - {error}")
    return False


def _find_yaml_position(raw_text: str, key_path: list) -> tuple[int, int] | None:
    # Walks PyYAML's own raw Node tree (yaml.compose(), NOT yaml.load())
    # by a path of keys/list-indices, returning the 1-indexed (line,
    # column) where that path's own key (or list item) is DEFINED, or
    # None if the path can't be resolved (e.g. it genuinely doesn't
    # exist, or something upstream of it isn't even a mapping/sequence
    # -- never raises for a not-found path, since this is purely an
    # error-message ENRICHMENT, and a missing position must never be
    # what breaks reporting the real error itself). Nodes retain real
    # source positions; the fully CONSTRUCTED Python objects load_
    # deployment() itself uses do not, once built -- see this file's
    # own module docstring for why this needs yaml.compose() at all,
    # not just the raw_text this script already has in hand.
    node = yaml.compose(raw_text, Loader=yaml.SafeLoader)
    position_node = node
    for key in key_path:
        if isinstance(node, yaml.MappingNode):
            found = None
            for key_node, value_node in node.value:
                if key_node.value == str(key):
                    found = (key_node, value_node)
                    break
            if found is None:
                return None
            key_node, node = found
            position_node = key_node
        elif isinstance(node, yaml.SequenceNode):
            if not isinstance(key, int) or key >= len(node.value):
                return None
            node = node.value[key]
            position_node = node
        else:
            return None
    return (position_node.start_mark.line + 1, position_node.start_mark.column + 1)


def _describe_position(raw_text: str, filename: str, key_path: list) -> str:
    position = _find_yaml_position(raw_text, key_path)
    if position is None:
        return ""
    line, _column = position
    return f" ({filename}, line {line})"


def _collect_action_type_and_role_errors(schema_raw: dict, policy_raw: dict, enabled_tools: list[str],
                                          schema_text: str, policy_text: str) -> list[str]:
    # Called ONLY once the more fundamental prerequisites (YAML
    # parses, every required key is present, every identifier is a
    # genuine string) are already confirmed sane -- validate_action_
    # types()/validate_roles() both assume that already holds. Calls
    # each PER-ENTRY (a single-item dict), not on the whole action_
    # types/roles dict at once -- both functions' own internal checks
    # are already entirely self-contained per action_type/per role
    # (verified directly: neither compares across different entries),
    # so this produces IDENTICAL individual results to calling them on
    # the whole dict, just with one entry's own failure never stopping
    # the next entry from still being checked.
    #
    # Roles go FURTHER, per-GRANT, not just per-role -- verified
    # directly that a single role with multiple genuinely independent
    # bad grants (e.g. a typo'd read: AND a typo'd execute: in the
    # SAME role) would otherwise still only ever surface its own
    # first bad grant, since validate_roles()'s own internal loop over
    # one role's allowed_actions is itself eager-fail. A role's own
    # grant list is often the largest, most error-prone thing in a
    # real deployment (a dozen-plus entries is completely ordinary),
    # so this is where the fuller picture matters most -- and where
    # per-GRANT position lookup (not just per-role) matters most too.
    object_types = schema_raw.get("object_types", {})
    action_types = schema_raw.get("action_types", {})
    roles = policy_raw.get("roles", {})

    errors = []
    for action_type_name, action_def in action_types.items():
        try:
            validate_action_types({action_type_name: action_def}, object_types)
        except ValueError as e:
            position = _describe_position(schema_text, "ontology_schema.yaml", ["action_types", action_type_name])
            errors.append(f"{e}{position}")
    for role_name, role_def in roles.items():
        grants = role_def.get("allowed_actions") or []
        for grant_index, grant in enumerate(grants):
            single_grant_role = {role_name: {**role_def, "allowed_actions": [grant]}}
            try:
                validate_roles(single_grant_role, object_types, action_types, enabled_tools)
            except ValueError as e:
                position = _describe_position(
                    policy_text, "policy.yaml", ["roles", role_name, "allowed_actions", grant_index]
                )
                errors.append(f"{e}{position}")
    return errors


def lint_deployment(config_dir: Path | None = None) -> bool:
    # config_dir is OPTIONAL, resolved lazily here when not given --
    # matches run_deployment.py's own established reasoning for why
    # (see its own docstring): a module-level global resolved once at
    # import time would mean a caller passing an explicit config_dir
    # (the whole point of the second usage shown in this file's own
    # docstring) could never actually override it.
    if config_dir is None:
        config_dir = resolve_runtime_paths().config_dir

    try:
        config_obj = load_deployment(config_dir)
    except OSError as e:
        # Covers FileNotFoundError, NotADirectoryError, PermissionError,
        # IsADirectoryError -- the whole family, not just the one this
        # script's own first version only caught (a real, confirmed
        # gap -- see this file's own AI-notes).
        return _report_invalid(config_dir, [f"Cannot read config: {e}"])
    except yaml.YAMLError as e:
        # A duplicate mapping key (core/config.py's own _StrictSafeLoader)
        # surfaces here too -- ConstructorError is a real yaml.YAMLError
        # subclass (verified directly, not assumed).
        return _report_invalid(config_dir, [f"Malformed YAML: {e}"])
    except ValueError as e:
        # load_deployment() itself already ran, in order: the required-
        # key check, validate_identifier_types(), validate_action_
        # types() (whole dict, fail-fast), validate_roles() (whole
        # dict, fail-fast). If IT raised, one of the first two -- a
        # genuine structural/prerequisite problem -- means action_
        # type/role validation cannot be trusted to run meaningfully at
        # all; re-attempting it here would either find nothing (schema_
        # raw/policy_raw parsed fine, e.g. a missing config.yaml key)
        # or risk a SECOND, confusing crash on the same bad data. Only
        # attempt the fuller, collect-everything pass when the error
        # ACTUALLY came from action_type or role validation specifically
        # -- detected structurally, not by string-matching the message:
        # re-parse the raw YAML directly (cheap, and load_deployment()
        # itself never exposes its own partially-built intermediate
        # state for reuse here) and check whether validate_identifier_
        # types() alone still passes cleanly on it. If it does, the
        # ORIGINAL failure must have come from further down the chain.
        try:
            schema_text = (config_dir / "ontology_schema.yaml").read_text()
            policy_text = (config_dir / "policy.yaml").read_text()
            config = yaml.safe_load((config_dir / "config.yaml").read_text())
            schema_raw = yaml.safe_load(schema_text)
            policy_raw = yaml.safe_load(policy_text)
            validate_identifier_types(schema_raw, policy_raw)
        except (OSError, yaml.YAMLError, ValueError):
            return _report_invalid(config_dir, [str(e)])

        enabled_tools = config.get("tools", {}).get("enabled", [])
        collected = _collect_action_type_and_role_errors(
            schema_raw, policy_raw, enabled_tools, schema_text, policy_text
        )
        # collected re-derives the SAME underlying validate_action_
        # types()/validate_roles() calls load_deployment() itself just
        # made (whole-dict, fail-fast) -- by construction, it already
        # contains an enriched version of whatever `e` represents. The
        # empty-list case is a defensive fallback only, not expected in
        # practice: show the original, unenriched error rather than
        # nothing.
        return _report_invalid(config_dir, collected or [str(e)])
    except Exception as e:
        # See this file's own AI-notes for why this exists and what it
        # is NOT a substitute for: every REAL failure mode found so far
        # (empty file, file-not-directory, unreadable directory) is
        # already handled specifically, above -- this is a deliberate
        # last resort so a genuinely unanticipated one still produces a
        # clean message instead of a scary traceback, not a replacement
        # for finding and handling the next one specifically once it's
        # actually found.
        return _report_invalid(config_dir, [f"Unexpected {type(e).__name__}: {e}"])

    print(f"VALID -- {config_dir}")
    print(
        f"  {len(config_obj.schema)} object type(s), {len(config_obj.action_types)} action type(s), "
        f"{len(config_obj.roles)} role(s), {len(config_obj.users)} user(s)"
    )
    return True


if __name__ == "__main__":
    given_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    ok = lint_deployment(given_dir)
    sys.exit(0 if ok else 1)


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# RESOLVED (kept for history):
# - Every raised error string throughout the whole validation chain
#   (this file's own three wrapper messages, plus every raise
#   ValueError(...) in core/ontology/action_types.py, core/
#   intermediate_layer/policy_validation.py, and core/deployment_
#   loader.py) was rewritten to ONE LINE each, per the user's own
#   explicit request: "succinct... just like common error messages --
#   not writing a whole book on every facet." The detailed reasoning
#   those messages used to carry inline did NOT disappear -- it moved
#   to the comment immediately above each check in each file, which is
#   where a future maintainer needs it; a paragraph in the raised
#   string itself was actively working against what an admin actually
#   needs while fixing a real typo. See each file's own AI-notes for
#   its own share of this pass.
# - The user separately asked whether this whole mechanism is
#   genuinely modular -- "the linter shouldn't affect other
#   subsystems." Verified directly: THIS file is a clean leaf module
#   (nothing outside its own test imports from it; it could be deleted
#   without breaking anything else). But the underlying validation
#   RULES it calls (core/config.py's duplicate-key rejection, core/
#   deployment_loader.py's validate_identifier_types(), core/ontology/
#   action_types.py's stricter sub_writes requirement, core/
#   intermediate_layer/policy_validation.py) are SHARED with, and
#   affect, load_deployment() itself -- every real entry point (api/,
#   scripts/run_deployment.py, scripts/serve_requests.py) gets this
#   same, stricter validation too, not just this script. This was
#   ALWAYS a deliberate choice (see core/config.py's own AI-notes,
#   written when duplicate-key rejection was first added: "a real
#   deployment starting up with a genuinely duplicated YAML key would
#   silently lose data too, not only when linted"), not something that
#   crept in unnoticed -- flagged back to the user as a genuine
#   architectural fork, and CONFIRMED by them as the intended design:
#   "the linter just calls into the existing functionality in some
#   spots... this is passable and fine" (see core/config.py's own
#   AI-notes for the fuller record of this resolution). What IS
#   cleanly isolated to this file alone, never touching load_
#   deployment()'s own behavior: collecting every issue instead of
#   failing on the first one, the line-number lookups via yaml.
#   compose(), and this file's own concise reporting format.
#
# - The first version of this script only caught FileNotFoundError,
#   yaml.YAMLError, and ValueError -- and only ever showed the FIRST
#   problem found, even when a config had several genuinely independent
#   mistakes. The user explicitly asked for a real audit against
#   established YAML/config-validator failure modes, not just a
#   conceptual review -- every gap below was found by DIRECTLY testing
#   the real script against a real, deliberately broken file, not
#   reasoned about in the abstract:
#   - An empty (0-byte) YAML file: yaml.safe_load() returns None, not
#     {}, and config.get(...) on None crashed with a raw AttributeError.
#   - config_dir pointing at a FILE: NotADirectoryError, a SIBLING of
#     FileNotFoundError under OSError (not a subclass) -- silently
#     escaped the original except clause entirely.
#   - Two YAML mappings genuinely defining the SAME key twice (e.g. two
#     "Widget:" object_type blocks with different content): PyYAML's
#     OWN long-standing, still-open bug (github.com/yaml/pyyaml/
#     issues/165) -- silently keeps only the LAST one, zero warning.
#     Fixed at the source, in core/config.py, not just worked around
#     here -- a real deployment starting up would have silently lost
#     data too, not just this script.
#   - A role (or object_type, or field, or grant string) that LOOKS
#     like a string but isn't, once YAML's own implicit typing runs:
#     a role literally named "no" resolved to the Python boolean
#     False, not the string "no" -- confirmed directly (python3 -c
#     checking the parsed dict's own real key type). Both the role's
#     own definition AND a user's "role: no" reference coerced
#     IDENTICALLY, so they still matched each other and this script
#     said VALID for a genuinely broken config -- a real, database-
#     backed user with the true STRING role "no" would have silently
#     failed authorize() forever, with no error anywhere. Fixed via
#     core/deployment_loader.py's new validate_identifier_types().
#   - The FIRST version of the "collect all issues" fix only collected
#     per action_type and per role -- but a SINGLE role with two
#     genuinely independent bad grants (a typo'd read: AND a typo'd
#     execute: in the SAME role's own allowed_actions list) still only
#     ever surfaced its own first bad grant, since validate_roles()'s
#     internal loop over one role's grants is itself eager-fail.
#     Confirmed directly (not assumed) by constructing exactly that
#     case and observing the second problem simply never appeared in
#     the output. Fixed by going one level deeper: _collect_action_
#     type_and_role_errors() now calls validate_roles() once PER
#     GRANT within each role, not once per role -- a role's own grant
#     list is often the largest, most error-prone thing in a real
#     deployment (a dozen-plus entries is completely ordinary), so
#     this is where the fuller picture matters most.
#
# DEFERRED (known, intentional, not yet built):
# - Line-number enrichment (_find_yaml_position(), added on request
#   specifically to make correction easier for admins) is scoped to
#   the two cases it cleanly applies to: an action_type's own error,
#   and a role's own per-grant error -- exactly the two categories
#   _collect_action_type_and_role_errors() already visits per-entity.
#   It's deliberately NOT extended to the structural/identifier-type
#   errors caught by the inner try/except right before that collection
#   even runs (a non-string object_type/role/field name, a missing
#   required top-level key, malformed YAML itself) -- YAML syntax
#   errors already carry PyYAML's own real line numbers for free; the
#   identifier-type case is genuinely harder, since the whole problem
#   IS that the key isn't a usable string to look up by key_path in
#   the first place (e.g. a role coerced to the boolean False has no
#   "False" text anywhere in the real YAML to search for). A position
#   lookup for that specific case would need a different strategy
#   (e.g. enumerating a section's own keys in file order and matching
#   by POSITION rather than by value) -- real, additional scope, not
#   attempted here since the two cases actually built already cover
#   the overwhelming majority of real, iteratively-discovered mistakes.
# - No "--quiet"/machine-readable output mode -- print() output is
#   currently the only interface (plus the exit code and, now, a real
#   list of every collected error). Fine for a human running this
#   interactively or a simple CI step checking the exit code alone,
#   but a caller wanting to parse WHAT specifically was invalid, in a
#   structured way, would need to scrape stdout today.
# - Only checks the FOUR YAML files load_deployment() itself reads
#   (config.yaml, ontology_schema.yaml, policy.yaml, data_silos.yaml --
#   see core/deployment_loader.py's own AI-notes for the fourth, added
#   when data_silos.yaml was split out of config.yaml) -- doesn't
#   attempt to verify anything about the REAL infrastructure a
#   deployment also depends on (does a silo's own "path" actually
#   resolve to a real, readable SQLite file once combined with a real
#   data_dir; is the configured LLM endpoint actually reachable). That
#   would require load_deployment_bundle() instead, which is exactly
#   the real-connections, real-file-creation step this script exists
#   specifically to avoid needing.
# - This audit was scoped to what a careful review PLUS direct,
#   empirical testing against real YAML/config-validator failure modes
#   could reasonably surface in one pass -- not a formal proof of
#   completeness. If this script is ever revisited and something else
#   slips through (a new YAML gotcha, a new OSError subtype), that's
#   real, new information, not evidence the original pass was careless
#   -- worth adding directly, the same way each item above was.
