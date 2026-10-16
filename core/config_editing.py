"""Editing config.yaml from the UI, with the file staying the source of truth.

THE FILES ARE MOSTLY COMMENTS: 104 of config.yaml's 127 lines were, when
this was designed, and the explanation IS the file. PyYAML's dump keeps
none of them. ruamel.yaml's round-trip mode keeps all of them -- and,
measured again on 15 October against config, ontology, policy and silo
files, writes each back BYTE-IDENTICAL when nothing changed. So an edit
from the UI rewrites only the lines it changed: the diff an operator
reviews is the change, and version control stays useful.

NO SECOND COPY. The UI does not own the configuration or keep it in a
database (roles.db is the exception, and predates this). It edits the
file, and the loader, an operator's editor, an outside program and the
agent all keep reading the same thing.

AN ALLOWLIST, NOT A GENERAL EDITOR. Only the settings in EDITABLE can
be changed, each with its type. That is what makes "no secret is ever
written" structural rather than a promise: llm.connection, silo
connections and anything credential-shaped are not on the list, so no
request can reach them. Adding one is a line here and a review.

ABSENT IS ITS OWN STATE. Several keys mean something different when
missing than when set to their obvious value -- on_type_mismatch absent
is not "refuse", and ingest_undeclared_columns absent is not "false"
(the loader's comments say why). So a change can REMOVE a key, and the
form shows which ones are absent and what that means.

WHAT IS NOT EDITABLE YET, and each is buildable: the ontology's SHAPE
(types, fields, data types -- below, only its descriptions are), policy,
silos, and config.yaml's nested settings -- lists, the llm block. Roles already have their own editor and store. The
dependency and "should configuration be editable from the UI at all"
were BLOCKING's questions; both were answered yes on 14 October.

THE WRITE PATH IS THE ROUTE'S (api/routes.py): validate a candidate
directory with the loader, write atomically, reload, and put the old
file back if the reload fails -- the role-change route's "save, reload,
undo" with a validation in front.
"""

import difflib
import hashlib
from dataclasses import dataclass, field

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap


class ConfigEditError(ValueError):
    """The change is not one this editor will make."""


@dataclass(frozen=True)
class Setting:
    key: str  # dotted path in config.yaml
    label: str
    kind: str  # "int", "bool" or "choice"
    description: str
    # What the deployment does when the key is not in the file at all.
    when_absent: str
    choices: tuple[str, ...] = field(default_factory=tuple)
    minimum: int | None = None


EDITABLE: tuple[Setting, ...] = (
    Setting("agent.max_hops", "Most steps per question", "int",
            "How many steps the agent may take before it must answer.",
            "Required; the deployment does not load without it.", minimum=1),
    Setting("agent.max_consecutive_duplicates", "Repeated steps before stopping", "int",
            "How many times in a row the agent may repeat a step before it is stopped.",
            "Required; the deployment does not load without it.", minimum=1),
    Setting("agent.max_consecutive_invalid_steps", "Invalid steps before stopping", "int",
            "How many malformed steps in a row before the agent is stopped.",
            "Required; the deployment does not load without it.", minimum=1),
    Setting("agent.query_deadline_seconds", "Seconds to answer", "int",
            "How long gathering may run before the agent must answer with what it has.",
            "300 seconds.", minimum=1),
    Setting("agent.max_tokens_per_query", "Token budget per question", "int",
            "The most tokens one question may use across every model call.",
            "No budget.", minimum=1),
    Setting("agent.constrain_steps", "Constrain steps to the schema", "bool",
            "Have the model's output checked against the step schema as it is produced.",
            "Off."),
    Setting("agent.filter_operators", "Filter operators", "bool",
            "Let the agent filter by ranges, lists and text, not only exact values.",
            "Off."),
    Setting("agent.search_result_cap", "Ids shown per search", "int",
            "How many ids of a search the agent reads; the total stays exact.",
            "No cap.", minimum=1),
    Setting("agent.free_text_search", "Free-text search", "bool",
            "Let the agent search a type's text fields by words.",
            "Off."),
    Setting("agent.remember_from_query", "Remember from questions", "bool",
            "Let the agent save a sentence about an object when asked to remember it.",
            "Off."),
    Setting("check_triggers_every_minutes", "Check triggers every (minutes)", "int",
            "How often the server checks triggers between syncs; 0 checks only after a sync.",
            "15 minutes.", minimum=0),
    Setting("on_type_mismatch", "A value of the wrong type", "choice",
            "What a sync does with a source value that is not the declared type.",
            "The loader's default, which its own comment explains.",
            choices=("refuse", "quarantine")),
    Setting("ingest_undeclared_columns", "Ingest undeclared columns", "bool",
            "Whether a sync copies source columns the ontology does not declare.",
            "The loader's default, which its own comment explains."),
)

_BY_KEY = {setting.key: setting for setting in EDITABLE}
_ABSENT = object()


def _yaml() -> YAML:
    # THE MEASURED SETTINGS: with these, every shipped file round-trips
    # byte-identical. Changing them reformats files nobody edited.
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    return yaml


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lookup(document, key: str):
    node = document
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return _ABSENT
        node = node[part]
    return node


def current_settings(text: str) -> list[dict]:
    """Every editable setting, its value in this file or that it is absent."""
    document = _yaml().load(text) or {}
    settings = []
    for setting in EDITABLE:
        value = _lookup(document, setting.key)
        settings.append({
            "key": setting.key, "label": setting.label, "kind": setting.kind,
            "description": setting.description, "when_absent": setting.when_absent,
            "choices": list(setting.choices), "minimum": setting.minimum,
            "present": value is not _ABSENT,
            "value": None if value is _ABSENT else value,
        })
    return settings


def _checked(setting: Setting, value):
    if setting.kind == "bool":
        if not isinstance(value, bool):
            raise ConfigEditError(f"{setting.key} is true or false.")
        return value
    if setting.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigEditError(f"{setting.key} is a whole number.")
        if setting.minimum is not None and value < setting.minimum:
            raise ConfigEditError(f"{setting.key} is at least {setting.minimum}.")
        return value
    if setting.kind == "choice":
        if value not in setting.choices:
            raise ConfigEditError(f"{setting.key} is one of {', '.join(setting.choices)}.")
        return value
    raise ConfigEditError(f"{setting.key} cannot be edited here.")  # pragma: no cover


#: How a removed setting is left in the file: commented out, with this
#: mark, so the line and its old value stay readable and the comments
#: around it -- which describe it -- are untouched. Re-adding the setting
#: restores this line rather than writing a second one.
REMOVED_MARK = "# absent: removed in Elysium"


def _render(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_content(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def _apply_one(text: str, key: str, value) -> str:
    """One config.yaml setting, changed by editing ITS LINE (_edit_line)."""
    rendered = None if value is None else _render(_checked(_BY_KEY[key], value))
    return _edit_line(text, key.split("."), rendered, "config.yaml")


def _inline_comment(tail: str, old) -> str:
    """The comment after a value on its line, or "".

    NOT EVERY "#" STARTS ONE: a description may say "Item #3", quoted.
    A candidate split counts only when what is left of it still reads
    as the value the file holds now."""
    import yaml as plain_yaml

    at = tail.find(" #")
    while at != -1:
        try:
            if plain_yaml.safe_load("k:" + tail[:at]) == {"k": old}:
                return "  " + tail[at:].lstrip()
        except plain_yaml.YAMLError:
            pass
        at = tail.find(" #", at + 1)
    return ""


def _edit_line(text: str, path: list[str], rendered: "str | None", filename: str,
               after: "tuple[str, ...] | None" = None) -> str:
    """One scalar at `path`, changed by editing ITS LINE and nothing else.
    `rendered` is the value as YAML text; None removes the key. `after`,
    when given, says where a NEW key goes: after the last of those keys
    present, or first in its block.

    LINES, NOT THE DATA MODEL, and a browser-free measurement is why.
    Editing through ruamel's model kept every comment when nothing
    changed -- and, on the first real edit, removing on_type_mismatch
    deleted three comment blocks with it (ruamel stores the comments
    after a key AS PART OF that key), while adding agent.filter_operators
    put it below the comment introducing `tools:`. Every editable value
    is a scalar, so ruamel only FINDS the line; the edit is a line
    replaced, commented out or inserted, and the caller checks the
    result means exactly what was asked.

    A VALUE MAY RUN ONTO LINES BELOW IT -- a folded description, `>`
    and the sentences under it. Those lines are its own, deeper than
    its key, and go with it: replaced, the new value is one line;
    removed, they are commented out with it.
    """
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    document = _yaml().load(text) or CommentedMap()
    *parents, leaf = path
    parent, parent_line, parent_indent = document, None, -2
    for part in parents:
        if not isinstance(parent, CommentedMap) or part not in parent or not isinstance(parent[part], CommentedMap):
            if rendered is None:
                return text
            raise ConfigEditError(f"{'.'.join(path)} needs a `{part}:` block, which {filename} does not have.")
        parent_line = parent.lc.key(part)[0]
        parent_indent = _indent_of(lines[parent_line])
        parent = parent[part]

    if leaf in parent:
        at = parent.lc.key(leaf)[0]
        line = lines[at]
        key_indent = _indent_of(line)
        indent = " " * key_indent
        # ITS OWN CONTINUATION: content lines deeper than the key, up to
        # the next line at the key's depth. Comments and blanks between
        # are left alone -- they may introduce what follows.
        last = at
        for index in range(at + 1, len(lines)):
            if _is_content(lines[index]):
                if _indent_of(lines[index]) <= key_indent:
                    break
                last = index
        if rendered is None:
            lines[at] = f"{indent}# {line.strip()}  {REMOVED_MARK}\n"
            for index in range(at + 1, last + 1):
                if _is_content(lines[index]):
                    lines[index] = f"{indent}#   {lines[index].strip()}\n"
        else:
            head, _, tail = line.rstrip("\n").partition(":")
            comment = _inline_comment(tail, parent[leaf]) if last == at else ""
            lines[at] = f"{head}: {rendered}{comment}\n"
            del lines[at + 1:last + 1]
        return "".join(lines)

    if rendered is None:
        return text

    # THE BLOCK'S EXTENT: from the parent's line to the next line of
    # content at its own indent or less. Comments and blanks inside it
    # may belong to what follows, so they never mark its end.
    start = 0 if parent_line is None else parent_line + 1
    end, last_content = len(lines), (parent_line if parent_line is not None else -1)
    child_indent = None
    for index in range(start, len(lines)):
        line = lines[index]
        if _is_content(line):
            if parent_line is not None and _indent_of(line) <= parent_indent:
                end = index
                break
            if child_indent is None and parent_line is not None:
                child_indent = _indent_of(line)
            last_content = index
    indent = " " * (0 if parent_line is None else (child_indent if child_indent is not None else parent_indent + 2))

    removed = f"{indent}# {leaf}:"
    for index in range(start, end):
        if lines[index].startswith(removed) and lines[index].rstrip().endswith(REMOVED_MARK):
            lines[index] = f"{indent}{leaf}: {rendered}\n"
            return "".join(lines)

    new_line = f"{indent}{leaf}: {rendered}\n"
    if after is not None and parent_line is not None:
        # BESIDE ITS KIND, NOT AT THE END: a new description belongs with
        # the type's display_name, not under its last field forty lines
        # down. After the last of `after` present, else first in the block.
        present = [parent.lc.key(k)[0] for k in after if k in parent]
        anchor = max(present) if present else parent_line
        if present:
            for index in range(anchor + 1, end):
                if _is_content(lines[index]):
                    if _indent_of(lines[index]) <= _indent_of(lines[max(present)]):
                        break
                    anchor = index
        lines.insert(anchor + 1, new_line)
    elif parent_line is None:
        lines.append(new_line)
    else:
        lines.insert(last_content + 1, new_line)
    return "".join(lines)


def apply_changes(text: str, changes: dict) -> str:
    """The file with these settings changed. A value of None REMOVES the
    key -- commented out with REMOVED_MARK -- which is how "absent" is
    chosen. Refuses a key not on the list, and refuses ANY result that
    does not mean exactly the old file with these changes: a line edit
    that went wrong is caught here, never written."""
    if not isinstance(changes, dict) or not changes:
        raise ConfigEditError("Nothing to change.")
    for key in changes:
        if key not in _BY_KEY:
            # THE SAME ANSWER for a key that exists and one that does not:
            # this editor does not say what else is in the file.
            raise ConfigEditError(f"{key} cannot be edited here.")
    edited = text
    for key, value in changes.items():
        edited = _apply_one(edited, key, value)

    import yaml as plain_yaml

    expected = plain_yaml.safe_load(text) or {}
    for key, value in changes.items():
        *parents, leaf = key.split(".")
        node = expected
        for part in parents:
            node = node.setdefault(part, {})
        if value is None:
            node.pop(leaf, None)
        else:
            node[leaf] = value
    if plain_yaml.safe_load(edited) != expected:
        raise ConfigEditError("That change could not be made without disturbing the rest of config.yaml.")
    return edited


def diff(before: str, after: str, filename: str = "config.yaml") -> list[str]:
    """The change as a unified diff -- only the lines that moved, because
    the round trip leaves every other byte where it was."""
    return [line.rstrip("\n") for line in difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"{filename} (now)", tofile=f"{filename} (after)", n=1)]


# ---------------------------------------------------------------------------
# DESCRIBING THE ONTOLOGY (DEV_UI 13.7): what a type and its fields are
# CALLED and what they MEAN to a reader, edited in ontology_schema.yaml.
#
# PRESENTATION, NOT SHAPE. A display name, a description, a group and a
# title field change what people read; they move no data, open no
# access, and need no change to a binding or the mirror. That is why
# they apply at once (decided 16 October), where a classification label
# -- which changes who sees what -- would wait for a second person.
# title_field is the nearest to the line: which field heads an object.
# It opens nothing, because a title is served only to someone who may
# read that field (mediator.visible_schema), so it stays here.
#
# THE SAME ALLOWLIST LAW as the settings above, and it is what keeps
# storage, security and every field's type out of reach: a change names
# one of these keys or it is refused, so no request can touch a type's
# `security:` block however it is phrased. Structural changes -- a new
# type or field, a data type -- are the next design, not this one.
# ---------------------------------------------------------------------------

#: Per key, at which level it may be described and its longest value.
#: The lengths are a reader's, not the loader's: a 1,000-character
#: description is already a page in a preview panel.
TYPE_KEYS: dict[str, int] = {
    "display_name": 80, "plural_display_name": 80, "description": 1000,
    "group": 60, "title_field": 100,
}
FIELD_KEYS: dict[str, int] = {"display_name": 80, "description": 1000}
#: More than this in one save is not describing, it is a migration.
MAX_DESCRIPTION_CHANGES = 100
ONTOLOGY_FILE = "ontology_schema.yaml"


def current_descriptions(text: str) -> dict:
    """Per type, its describable keys as the file has them (None when
    absent), and per field the same, with whether it is a data field --
    the only kind a title may be."""
    document = _yaml().load(text) or {}
    described = {}
    for name, type_def in (document.get("object_types") or {}).items():
        if not isinstance(type_def, dict):
            continue
        fields = {}
        for field_name, declared in (type_def.get("fields") or {}).items():
            declared = declared if isinstance(declared, dict) else {}
            fields[field_name] = {
                **{key: _as_text(declared.get(key)) for key in FIELD_KEYS},
                "kind": str(declared.get("type") or "data"),
                "labels": _labels_of(declared),
            }
        described[name] = {**{key: _as_text(type_def.get(key)) for key in TYPE_KEYS},
                           "fields": fields}
    return described


def _as_text(value) -> "str | None":
    return value if isinstance(value, str) else None


def _checked_text(where: str, key: str, value, longest: int) -> "str | None":
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigEditError(f"{where}'s {key} is text.")
    value = value.strip()
    if not value:
        # EMPTY IS NOT ABSENT: object_type_validation refuses an empty
        # display_name because it renders as a blank. Removing is null.
        raise ConfigEditError(f"{where}'s {key} is empty; to remove it, remove it.")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ConfigEditError(f"{where}'s {key} is one line, without control characters.")
    if len(value) > longest:
        raise ConfigEditError(f"{where}'s {key} is at most {longest} characters.")
    return value


def _render_text(value: str) -> str:
    """Plain when YAML reads it back as exactly this string, quoted
    otherwise -- "yes", "12", "null", a leading "*" and "Item #3" would
    each come back as something else, or as less."""
    import json

    import yaml as plain_yaml

    try:
        if plain_yaml.safe_load(f"k: {value}") == {"k": value}:
            return value
    except plain_yaml.YAMLError:
        pass
    # A JSON string is a YAML double-quoted scalar.
    return json.dumps(value, ensure_ascii=False)


def _meaning_checked(edited: str, expected) -> str:
    """`edited`, if it means exactly `expected`; refused otherwise. The
    net under every line edit: one that went wrong is caught here, never
    written."""
    import yaml as plain_yaml

    try:
        means = plain_yaml.safe_load(edited)
    except plain_yaml.YAMLError:
        means = None
    if means != expected:
        raise ConfigEditError(f"That change could not be made without disturbing the rest of {ONTOLOGY_FILE}.")
    return edited


def apply_descriptions(text: str, changes: list) -> str:
    """ontology_schema.yaml with these descriptions changed. Each change
    is {object_type, field (or None for the type), key, value}; a value
    of None removes the key. Refuses anything off the allowlist, and any
    result that does not mean exactly the old file with these changes."""
    import yaml as plain_yaml

    if not isinstance(changes, list) or not changes:
        raise ConfigEditError("Nothing to change.")
    if len(changes) > MAX_DESCRIPTION_CHANGES:
        raise ConfigEditError(f"At most {MAX_DESCRIPTION_CHANGES} changes at once.")
    expected = plain_yaml.safe_load(text) or {}
    types = expected.get("object_types") if isinstance(expected, dict) else None
    if not isinstance(types, dict):
        raise ConfigEditError(f"{ONTOLOGY_FILE} declares no object_types.")

    edited, seen = text, set()
    for change in changes:
        object_type, field_name, key = change.get("object_type"), change.get("field"), change.get("key")
        type_def = types.get(object_type) if isinstance(object_type, str) else None
        if not isinstance(type_def, dict):
            raise ConfigEditError(f"There is no object type {object_type!r}.")
        if field_name is None:
            allowed, where, node = TYPE_KEYS, object_type, type_def
            path = ["object_types", object_type, key]
            after = tuple(TYPE_KEYS)
        else:
            declared = (type_def.get("fields") or {}).get(field_name) if isinstance(field_name, str) else None
            if not isinstance(declared, dict):
                raise ConfigEditError(f"{object_type} has no field {field_name!r}.")
            allowed, where, node = FIELD_KEYS, f"{object_type}.{field_name}", declared
            path = ["object_types", object_type, "fields", field_name, key]
            # A field's description goes after its `type:`, which is
            # where a reader of the file looks for what it is.
            after = ("type", "data_type", *FIELD_KEYS)
        if key not in allowed:
            raise ConfigEditError(f"{where}'s {key} cannot be edited here.")
        if (object_type, field_name, key) in seen:
            raise ConfigEditError(f"{where}'s {key} is changed twice.")
        seen.add((object_type, field_name, key))

        value = _checked_text(where, key, change.get("value"), allowed[key])
        edited = _edit_line(edited, path, None if value is None else _render_text(value),
                            ONTOLOGY_FILE, after=after)
        if value is None:
            node.pop(key, None)
        else:
            node[key] = value

    return _meaning_checked(edited, expected)


# ---------------------------------------------------------------------------
# ACCESS LABELS (DEV_UI 13.7, decided 16 October): a field's
# `classification:`, what its values ARE -- pii, financial. Edited with
# the same line editor, and ONLY the edit lives here. Whether the change
# applies at once or waits for a second person is the route's question,
# answered by asking the permission code (core/role_impact.
# config_access_impact) whether anyone could read more afterwards.
# ---------------------------------------------------------------------------

MAX_LABELS_PER_FIELD = 10


def _labels_of(field: dict) -> list[str]:
    declared = field.get("classification")
    if isinstance(declared, str):
        return [declared]
    if isinstance(declared, list):
        return [label for label in declared if isinstance(label, str)]
    return []


def _render_labels(labels: list[str]) -> str:
    # One label as a word, several as a flow list on ONE line -- the
    # shape every classification in the shipped files already has, and
    # the only shape the line editor writes.
    return labels[0] if len(labels) == 1 else "[" + ", ".join(labels) + "]"


def apply_labels(text: str, changes: list) -> str:
    """ontology_schema.yaml with these fields' labels set. Each change is
    {object_type, field, labels}; an empty list removes the key. The
    label's SHAPE is checked here as the loader checks it -- lowercase,
    identifier-like -- and the loader judges the rest (a grant naming a
    label no field carries any more is refused at load)."""
    import re

    import yaml as plain_yaml

    if not isinstance(changes, list) or not changes:
        raise ConfigEditError("Nothing to change.")
    if len(changes) > MAX_DESCRIPTION_CHANGES:
        raise ConfigEditError(f"At most {MAX_DESCRIPTION_CHANGES} changes at once.")
    expected = plain_yaml.safe_load(text) or {}
    types = expected.get("object_types") if isinstance(expected, dict) else None
    if not isinstance(types, dict):
        raise ConfigEditError(f"{ONTOLOGY_FILE} declares no object_types.")
    shape = re.compile(r"^[a-z][a-z0-9_]*$")

    edited, seen = text, set()
    for change in changes:
        object_type, field_name, labels = change.get("object_type"), change.get("field"), change.get("labels")
        type_def = types.get(object_type) if isinstance(object_type, str) else None
        if not isinstance(type_def, dict):
            raise ConfigEditError(f"There is no object type {object_type!r}.")
        declared = (type_def.get("fields") or {}).get(field_name) if isinstance(field_name, str) else None
        if not isinstance(declared, dict):
            raise ConfigEditError(f"{object_type} has no field {field_name!r}.")
        where = f"{object_type}.{field_name}"
        if (object_type, field_name) in seen:
            raise ConfigEditError(f"{where}'s labels are changed twice.")
        seen.add((object_type, field_name))
        if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
            raise ConfigEditError(f"{where}'s labels are a list of words.")
        labels = list(dict.fromkeys(label.strip() for label in labels))
        if len(labels) > MAX_LABELS_PER_FIELD:
            raise ConfigEditError(f"{where} carries at most {MAX_LABELS_PER_FIELD} labels.")
        for label in labels:
            if not shape.match(label):
                raise ConfigEditError(
                    f"{label!r} is not a label: lowercase letters, digits and underscores, "
                    f"starting with a letter -- 'pii', not 'PII' -- so one label cannot be "
                    f"spelled three ways.")
        path = ["object_types", object_type, "fields", field_name, "classification"]
        edited = _edit_line(edited, path, _render_labels(labels) if labels else None,
                            ONTOLOGY_FILE, after=("type", "data_type", *FIELD_KEYS))
        if labels:
            declared["classification"] = labels[0] if len(labels) == 1 else labels
        else:
            declared.pop("classification", None)

    return _meaning_checked(edited, expected)


# ---------------------------------------------------------------------------
# WHICH FILES' LINES THE INTERFACE SHOWS. A change to any configuration
# file can reach the screen now -- an earlier version put back touches
# them all -- and the rule for what may is older than this editor:
# /admin/config-history names the files that changed and never their
# contents, "without returning silo hosts and credential references over
# HTTP". So only the ontology's lines are shown, which every manager of
# the deployment already reads on the schema screens; the others are
# named, with why, and their effect on access is shown in access terms.
# ---------------------------------------------------------------------------

_NOT_SHOWN = {
    "config.yaml": "it holds the model's connection and other settings this screen does not carry",
    "data_silos.yaml": "it holds where each source is and how to reach it",
    "source_bindings.yaml": "it holds which source tables back each type",
    "policy.yaml": "it holds the people and their compartments; what it changes for each role is shown above",
}


def shown_diff(filename: str, before: str, after: str) -> list[str]:
    """The change to one file as the interface may show it: its lines for
    the ontology, and for any other file a line naming it and why its
    contents stay off the screen."""
    if filename == ONTOLOGY_FILE:
        return diff(before, after, filename)
    why = _NOT_SHOWN.get(filename, "its contents are not shown here")
    return [f"{filename} changes too. Its lines are not shown here: {why}."]
