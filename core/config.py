"""
config.py  (generic YAML loading -- org-agnostic)

The ONLY thing this file knows how to do is read a YAML file into a
plain Python dict. It has no idea what the contents mean -- no concept
of "users", "schema", or "model names". That interpretation happens
wherever this is called from.

SECURITY: _StrictSafeLoader is a direct SUBCLASS of yaml.SafeLoader,
not yaml.Loader/yaml.UnsafeLoader -- it registers no additional
constructors of its own, only OVERRIDES construct_mapping() (see
below). This preserves SafeLoader's own safety property exactly:
still only ever produces plain data structures, still cannot execute
arbitrary Python via YAML tags, even though the loading call below is
now yaml.load(f, Loader=_StrictSafeLoader) rather than the bare
yaml.safe_load(f) this file used to call directly.

DUPLICATE KEYS ARE REJECTED, not silently accepted -- this is NOT
yaml.safe_load()'s own default behavior, and the gap this closes is
real, not theoretical: PyYAML has a long-standing, still-open issue
(github.com/yaml/pyyaml/issues/165) confirming it does NOT reject
duplicate mapping keys, even though the YAML 1.2 spec itself requires
mapping keys to be unique. The observed, DEFAULT behavior is silent
data loss -- the LAST occurrence of a repeated key silently wins, with
zero warning anywhere, exactly the kind of "large files, easy to
accidentally duplicate a key while copy-pasting a block" mistake this
project's own deployment YAML files are genuinely vulnerable to (two
object_types blocks both named "Widget," a role pasted twice and only
the second one edited) -- caught directly, empirically, not assumed:
see core/deployment_loader.py's own AI-notes for the real test that
found this. _StrictSafeLoader's own construct_mapping() override runs
for EVERY mapping node PyYAML encounters, at every level of nesting,
not just the top level -- a duplicate key anywhere in the whole YAML
tree is caught, not only ones at the file's own root.

No error handling here on purpose -- a missing file, malformed YAML,
OR a duplicate key should all surface as Python's own clear
FileNotFoundError/yaml.YAMLError (ConstructorError is a YAMLError
subclass), not get wrapped in a vaguer catch-and-reraise that adds
nothing.

Called by: core/deployment_loader.py (the one place config gets read
           and turned into explicit values for core/ functions)
"""

from pathlib import Path

import yaml


class _StrictSafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        seen_keys = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen_keys:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            seen_keys.add(key)
        return super().construct_mapping(node, deep)


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.load(f, Loader=_StrictSafeLoader)


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# RESOLVED (kept for history):
# - The duplicate-key ConstructorError message itself was trimmed to
#   one line ("found duplicate key {key!r}", no explanatory clause),
#   per the user's own explicit request for compiler-style brevity --
#   ConstructorError already appends real file/line context of its
#   own automatically (node.start_mark/key_node.start_mark), so the
#   longer, since-removed explanation was pure redundant prose on top
#   of information the exception already carries.
#
# RESOLVED (was an OPEN QUESTION, now settled -- kept for history):
# _StrictSafeLoader living HERE -- affecting every real load_
# deployment() caller, not just scripts/lint_deployment.py -- was
# flagged back to the user as a genuine architectural fork: keep
# validation RULES shared with the real load_deployment() path
# (this file's own CONTEXT paragraph above), or duplicate/isolate them
# so ONLY the linter enforces them. The user's own answer, given
# directly: "the linter just calls into the existing functionality in
# some spots... this is passable and fine" -- confirming the CURRENT
# design (shared correctness rules in core/, with scripts/lint_
# deployment.py itself staying a genuine leaf module that adds only
# its own linter-specific ergonomics on top) is the intended one, not
# an accidental entanglement. No code change resulted from this --
# only this note, recording that the question was asked and answered.
#
# CONTEXT: _StrictSafeLoader was added during a deliberate, requested
# audit of scripts/lint_deployment.py against REAL, established YAML/
# config-validator failure modes (both researched directly and tested
# empirically against this actual code, not just reasoned about in the
# abstract) -- see that script's own AI-notes for the other three
# fixes from the same pass (broadened exception handling, identifier-
# type checking, collect-all-issues instead of fail-fast-on-first).
# This specific fix -- duplicate-key rejection -- was deliberately
# NOT scoped to just the linter: a real deployment starting up with a
# genuinely duplicated YAML key would silently lose data too, not
# only when linted, so this lives here, in the one place ALL YAML
# loading in the whole project goes through, not as a linter-only
# workaround.
#
# DEFERRED (known, intentional, not yet built):
# - Other real, documented YAML gotchas researched during the same
#   audit were deliberately NOT addressed here, at the generic-loader
#   level, because they're narrower and better caught closer to where
#   they'd actually matter: octal-interpreted leading-zero numerals
#   (010 -> 8), float-ambiguous scientific notation (1e2 -> 100.0),
#   and implicit date parsing (2024-01-01 -> a real datetime.date) can
#   all still silently coerce a VALUE (not an identifier/key -- those
#   are covered by core/deployment_loader.py's own validate_
#   identifier_types(), a separate, deliberate fix from the same
#   audit) an admin intended as a plain string. Most likely to bite on
#   a literal mutation value in ontology_schema.yaml's own action_
#   types (e.g. {"set": {"property": "status", "value": 2024-01-01}}
#   unquoted). Not fixed here because it would mean either rejecting
#   EVERY genuinely-numeric-or-date-shaped scalar value in the whole
#   YAML tree (including ones that are supposed to be numbers, like
#   max_hops), or building a much narrower, schema-aware check (only
#   flag this specific shape when it appears somewhere a mutation
#   VALUE, not a numeric config field, is expected) -- the latter is
#   real, additional scope genuinely worth a future, separate pass if
#   this class of mistake ever actually surfaces in practice, not
#   something to bolt onto this already-generic, schema-agnostic
#   loader (see this file's own module docstring for why staying
#   schema-agnostic is a deliberate property of this file specifically).
