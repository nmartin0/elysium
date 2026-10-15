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

WHAT IS NOT EDITABLE YET, and each is buildable: the other files
(ontology, policy, silos) and config.yaml's nested settings -- lists,
the llm block. Roles already have their own editor and store. The
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
    """One setting, changed by editing ITS LINE and nothing else.

    LINES, NOT THE DATA MODEL, and a browser-free measurement is why.
    Editing through ruamel's model kept every comment when nothing
    changed -- and, on the first real edit, removing on_type_mismatch
    deleted three comment blocks with it (ruamel stores the comments
    after a key AS PART OF that key), while adding agent.filter_operators
    put it below the comment introducing `tools:`. Every editable setting
    is a one-line scalar, so ruamel only FINDS the line; the edit is a
    line replaced, commented out or inserted, and apply_changes checks
    the result means exactly what was asked.
    """
    setting = _BY_KEY[key]
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    document = _yaml().load(text) or CommentedMap()
    *parents, leaf = key.split(".")
    parent, parent_line, parent_indent = document, None, -2
    for part in parents:
        if not isinstance(parent, CommentedMap) or part not in parent or not isinstance(parent[part], CommentedMap):
            if value is None:
                return text
            raise ConfigEditError(f"{key} needs a `{part}:` block, which config.yaml does not have.")
        parent_line = parent.lc.key(part)[0]
        parent_indent = _indent_of(lines[parent_line])
        parent = parent[part]

    if leaf in parent:
        at = parent.lc.key(leaf)[0]
        line = lines[at]
        indent = " " * _indent_of(line)
        if value is None:
            lines[at] = f"{indent}# {line.strip()}  {REMOVED_MARK}\n"
        else:
            rendered = _render(_checked(setting, value))
            head, _, tail = line.rstrip("\n").partition(":")
            comment = ""
            if "#" in tail:
                comment = "  #" + tail.split("#", 1)[1]
            lines[at] = f"{head}: {rendered}{comment}\n"
        return "".join(lines)

    if value is None:
        return text
    rendered = _render(_checked(setting, value))

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
            last_content = index
            if child_indent is None and parent_line is not None:
                child_indent = _indent_of(line)
    indent = " " * (0 if parent_line is None else (child_indent if child_indent is not None else parent_indent + 2))

    removed = f"{indent}# {leaf}:"
    for index in range(start, end):
        if lines[index].startswith(removed) and lines[index].rstrip().endswith(REMOVED_MARK):
            lines[index] = f"{indent}{leaf}: {rendered}\n"
            return "".join(lines)

    new_line = f"{indent}{leaf}: {rendered}\n"
    if parent_line is None:
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
