"""
module_api_report.py  (the public API a module may rely on, written down)

BLOCKING.md item 3, step 4, agreed with the owner 24 October: "the sub-app
API written down and versioned from what (1)-(3) used". The public surface
is WHAT MODULES USE TODAY -- every name a module imports from the kit
(@elysium/shell-api) or the shell (@shell/core), and every declaration
those names lead to -- and this writes it down as a REPORT, checked in:

    python -m scripts.module_api_report           write ui/module-api.report.md
    python -m scripts.module_api_report --check   exit 1 if it is stale

THE PRECEDENT is Microsoft's API Extractor, which Backstage runs on every
package: an API report is "a large block of pseudocode that concisely
summarizes the API signatures", tracked in git "so that changes to the
public API show up as diffs", and a build whose report is stale fails.
tests/unit/test_the_module_api_report_is_current.py is that build step.

NOT API EXTRACTOR ITSELF, for two reasons measured on 24 October: it
bundles TypeScript 5.9 and this project is on TypeScript 7, the native
compiler, which has no JavaScript compiler API for tools to drive; and it
reports a package's whole entry points, where the owner chose the names
modules USE -- 194 of them, from 37 entry points, when the kit's client
alone exports 201. So: TypeScript 7 emits the declaration files (`tsc
--emitDeclarationOnly`, about 2 seconds), and this reads them.

WHAT COUNTS AS A MODULE: every package under ui/packages/ named app-*,
and the simulator's panel (sim/panel/web) -- an add-on, built apart, the
first module outside this repository's ui/. Its tests do not count:
a name only a test imports is not something a module depends on.

FOLLOWED, NOT ONLY LISTED: a public function taking `SearchOptions` makes
`SearchOptions` public, though no module names it, because a module must
be able to build one -- API Extractor's "forgotten export". Declarations
reached that way are followed into the files they are imported from, as
long as those are the kit's or the shell's own.

ALWAYS PUBLIC, whether or not a module imports it: the manifest's shape
and what `activate` returns (@shell/core/contract's ModuleEntry,
@shell/core/moduleLoader's ModuleActivation and ModuleContext). A module
never imports the type of its own module.json, and it is the first thing
it depends on.

THE REPORT CARRIES SIGNATURES, NOT PROSE: comments are dropped, so
rewording a docstring is not an API change. Its order is fixed -- entry
points, then names, alphabetically -- so a diff is the change and only
the change.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui"
REPORT = UI / "module-api.report.md"

#: Where module code lives, for what it imports.
MODULE_SOURCES = (*sorted((UI / "packages").glob("app-*/src")), ROOT / "sim" / "panel" / "web" / "src")

#: Public whatever modules import: the module's own contract.
ALWAYS_PUBLIC = {
    "@shell/core/contract": ("ModuleEntry",),
    "@shell/core/moduleLoader": ("ModuleActivation", "ModuleContext"),
}

_IMPORT = re.compile(
    r"import\s+(?:type\s+)?(?P<what>[\w$]+\s*,\s*\{[^}]*\}|\{[^}]*\}|[\w$]+)\s+from\s+"
    r"'(?P<path>(?:@elysium/shell-api|@shell/core)/[^']+)'")
_DECLARATION = re.compile(
    r"^export\s+(?:declare\s+)?(?:abstract\s+)?(?:function|const|let|var|class|interface|type|enum|namespace)\s+"
    r"(?P<name>[\w$]+)|"
    r"^(?:declare\s+)?(?:abstract\s+)?(?:function|const|let|var|class|interface|type|enum|namespace)\s+(?P<local>[\w$]+)|"
    r"^export\s+default\s+(?:function|class)\b")
_DEFAULT_ALIAS = re.compile(r"^export\s+default\s+([\w$]+)\s*;")
_RE_EXPORT = re.compile(r"^export\s+(?:type\s+)?\{(?P<names>[^}]*)\}\s*(?:from\s+'(?P<path>[^']+)')?")
_D_IMPORT = re.compile(
    r"^import\s+(?:type\s+)?(?P<what>[\w$]+\s*,\s*\{[^}]*\}|\{[^}]*\}|[\w$]+)\s+from\s+'(?P<path>[^']+)'")
_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")


# ---------------------------------------------------------------------------
# What modules import
# ---------------------------------------------------------------------------

def _names(what: str) -> list[str]:
    """`Default, { a, type b, c as d }` -> ['default', 'a', 'b', 'c']."""
    names: list[str] = []
    default, _, braces = what.partition("{")
    if default.strip().rstrip(","):
        names.append("default")
    for item in braces.rstrip("}").split(","):
        item = item.strip().removeprefix("type ").strip()
        if item:
            names.append(item.split(" as ")[0].strip())
    return names


def used_by_modules(sources: Iterable[Path] = MODULE_SOURCES) -> dict[str, set[str]]:
    used: dict[str, set[str]] = {}
    for folder in sources:
        for path in sorted(folder.rglob("*.ts*")):
            if ".test." in path.name or path.suffix not in (".ts", ".tsx"):
                continue
            for match in _IMPORT.finditer(path.read_text()):
                used.setdefault(match["path"], set()).update(_names(match["what"]))
    for entry, names in ALWAYS_PUBLIC.items():
        used.setdefault(entry, set()).update(names)
    return used


# ---------------------------------------------------------------------------
# Declaration files
# ---------------------------------------------------------------------------

def emit_declarations(out: Path) -> None:
    """TypeScript 7's own declarations for the kit, the shell and modules."""
    result = subprocess.run(
        ["npx", "tsc", "-p", "tsconfig.json", "--noEmit", "false", "--declaration", "--emitDeclarationOnly",
         "--rootDir", "..", "--outDir", str(out)],
        cwd=UI, capture_output=True, text=True, check=False)
    if not any(out.rglob("*.d.ts")):
        raise SystemExit(f"tsc emitted no declarations:\n{result.stdout}{result.stderr}")


def source_of(entry: str) -> Path:
    """The source file an entry point names."""
    if entry.startswith("@shell/core/"):
        base = ROOT / "shell" / "core" / "src" / entry.removeprefix("@shell/core/")
        for suffix in (".ts", ".tsx"):
            if base.with_suffix(suffix).is_file():
                return base.with_suffix(suffix)
        raise SystemExit(f"{entry}: no such file in shell/core/src")
    exports = json.loads((UI / "packages" / "shell-api" / "package.json").read_text())["exports"]
    target = exports.get("./" + entry.removeprefix("@elysium/shell-api/"))
    if target is None:
        raise SystemExit(f"{entry}: not in @elysium/shell-api's exports")
    return (UI / "packages" / "shell-api" / target).resolve()


def declaration_file(source: Path, out: Path) -> Path:
    return out / source.relative_to(ROOT).with_suffix(".d.ts")


def _without_comments(text: str) -> str:
    """Comments out, strings and template literals kept as written."""
    out: list[str] = []
    i, quote = 0, None
    while i < len(text):
        c = text[i]
        if quote:
            out.append(c)
            if c == "\\":
                out.append(text[i + 1])
                i += 1
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
            out.append(c)
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end == -1 else end + 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end == -1 else end - 1
        else:
            out.append(c)
        i += 1
    return "".join(out)


def statements(text: str) -> list[str]:
    """Top-level statements of a declaration file, each on its lines, comments gone."""
    text = _without_comments(text)
    found: list[str] = []
    current: list[str] = []
    depth, quote, i = 0, None, 0
    while i < len(text):
        c = text[i]
        current.append(c)
        if quote:
            if c == "\\":
                current.append(text[i + 1])
                i += 1
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif c in "{([":
            depth += 1
        elif c in "})]":
            depth -= 1
            if depth == 0 and c == "}":
                head = "".join(current).lstrip()
                if re.match(r"(export\s+)?(declare\s+)?(abstract\s+)?(interface|class|enum|namespace)\b", head) \
                        or re.match(r"export\s+(default\s+)?(declare\s+)?function\b", head) and "=" not in head:
                    rest = text[i + 1:].lstrip()
                    if not rest.startswith((";", "|", "&", "[", ".")):
                        found.append(head.strip())
                        current = []
        elif c == ";" and depth == 0:
            found.append("".join(current).strip().rstrip(";").strip() + ";")
            current = []
        i += 1
    tail = "".join(current).strip()
    if tail:
        found.append(tail)
    return [_tidy(s) for s in found if s.strip(" ;")]


def _tidy(statement: str) -> str:
    lines = [line.rstrip() for line in statement.split("\n") if line.strip()]
    return "\n".join(lines)


class DeclarationFile:
    """One declaration file: what it declares, exports and imports."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.declared: dict[str, list[str]] = {}
        self.exported: dict[str, str] = {}
        #: Exported names that are another file's: name -> (relative path, its name).
        self.re_exported: dict[str, tuple[str, str]] = {}
        self.imported: dict[str, tuple[str, str]] = {}
        for statement in statements(path.read_text()) if path.is_file() else []:
            self._take(statement)

    def _take(self, statement: str) -> None:
        if (match := _D_IMPORT.match(statement)) is not None:
            default, _, braces = match["what"].partition("{")
            if default.strip().rstrip(","):
                self.imported[default.strip().rstrip(",").strip()] = (match["path"], "default")
            for item in braces.rstrip("}").split(","):
                item = item.strip().removeprefix("type ").strip()
                if item:
                    original, _, local = item.partition(" as ")
                    self.imported[(local or original).strip()] = (match["path"], original.strip())
            return
        if (match := _RE_EXPORT.match(statement)) is not None:
            for item in match["names"].split(","):
                item = item.strip().removeprefix("type ").strip()
                if not item:
                    continue
                original, _, exposed = item.partition(" as ")
                original, exposed = original.strip(), (exposed or original).strip()
                if match["path"]:
                    self.re_exported[exposed] = (match["path"], original)
                else:
                    self.exported[exposed] = original
            return
        if (match := _DEFAULT_ALIAS.match(statement)) is not None:
            self.exported["default"] = match[1]
            return
        match = _DECLARATION.match(statement)
        if match is None:
            return
        if match["name"]:
            self.declared.setdefault(match["name"], []).append(statement)
            self.exported[match["name"]] = match["name"]
        elif match["local"]:
            self.declared.setdefault(match["local"], []).append(statement)
        else:
            self.declared.setdefault("default", []).append(statement)
            self.exported["default"] = "default"


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

class Surface:
    """The public declarations, followed from what modules use."""

    def __init__(self, out: Path) -> None:
        self.out = out
        self.files: dict[Path, DeclarationFile] = {}
        #: Declaration file -> local names public in it.
        self.public: dict[Path, set[str]] = {}
        self.problems: list[str] = []

    def file(self, path: Path) -> DeclarationFile:
        if path not in self.files:
            self.files[path] = DeclarationFile(path)
        return self.files[path]

    def _relative(self, origin: Path, spec: str) -> Path | None:
        """A relative import in a declaration file, as the declaration file it names."""
        if not spec.startswith("."):
            return None
        base = (origin.parent / spec).resolve()
        for candidate in (base.with_suffix(".d.ts"), base / "index.d.ts", Path(str(base) + ".d.ts")):
            if candidate.is_file():
                return candidate
        return None

    def _aliased(self, origin: Path, spec: str) -> Path | None:
        """`@elysium/shell-api/x` or `@shell/core/x`, inside a declaration file."""
        if spec.startswith(("@elysium/shell-api/", "@shell/core/")):
            try:
                return declaration_file(source_of(spec), self.out)
            except SystemExit:
                return None
        return self._relative(origin, spec)

    def make_public(self, path: Path, exported_name: str, context: str) -> None:
        file = self.file(path)
        if exported_name in file.re_exported:
            spec, original = file.re_exported[exported_name]
            target = self._aliased(path, spec)
            if target is None:
                self.problems.append(f"{context}: {exported_name} is re-exported from {spec}, which is not found")
                return
            self.make_public(target, original, context)
            return
        local = file.exported.get(exported_name)
        if local is None:
            self.problems.append(f"{context}: imports {exported_name}, which it does not export")
            return
        self._follow(path, local)

    def _follow(self, path: Path, local: str) -> None:
        file = self.file(path)
        public = self.public.setdefault(path, set())
        if local in public:
            return
        if local not in file.declared:
            if local in file.imported:
                spec, original = file.imported[local]
                target = self._aliased(path, spec)
                if target is not None:
                    self.make_public(target, original, str(path))
            return
        public.add(local)
        for statement in file.declared[local]:
            for name in set(_IDENTIFIER.findall(_strings_out(statement))) - {local}:
                if name in file.declared:
                    self._follow(path, name)
                elif name in file.imported:
                    spec, original = file.imported[name]
                    target = self._aliased(path, spec)
                    if target is not None:
                        self.make_public(target, original, str(path))


def _strings_out(statement: str) -> str:
    return re.sub(r"'[^']*'|\"[^\"]*\"", "''", statement)


def _entry_name(path: Path, out: Path) -> str:
    """A declaration file as the entry point modules would write."""
    source = path.relative_to(out).with_suffix("").with_suffix("")
    parts = source.parts
    if parts[:3] == ("shell", "core", "src"):
        return "@shell/core/" + "/".join(parts[3:])
    if parts[:4] == ("ui", "packages", "shell-api", "src"):
        exports = json.loads((UI / "packages" / "shell-api" / "package.json").read_text())["exports"]
        inside = "./src/" + "/".join(parts[4:])
        for key, target in exports.items():
            if target.rsplit(".", 1)[0] == inside:
                return "@elysium/shell-api/" + key.removeprefix("./")
        return f"@elysium/shell-api (inside: src/{'/'.join(parts[4:])})"
    return "/".join(parts)


def render(surface: Surface, used: dict[str, set[str]]) -> str:
    lines = [
        "# The module API, as used",
        "",
        "<!-- GENERATED by `python -m scripts.module_api_report`; do not edit by hand.",
        "     A change here is a change to what modules may rely on: review it as one",
        "     (BLOCKING.md item 3, step 4). -->",
        "",
        "Every name below is one a module imports from the kit",
        "(`@elysium/shell-api`) or the shell (`@shell/core`), or a declaration one of",
        "those leads to. Anything else either exports is internal, and may change",
        "without notice.",
        "",
        f"{sum(len(names) for names in used.values())} names imported, from {len(used)} entry points,"
        f" by {len(MODULE_SOURCES)} modules;",
        f"{sum(len(names) for names in surface.public.values())} declarations public in all.",
        "",
    ]
    by_entry: dict[str, list[str]] = {}
    for path, names in surface.public.items():
        file = surface.file(path)
        exported_locals = set(file.exported.values())
        for name in names:
            body = "\n".join(file.declared[name])
            if name not in exported_locals:
                body = "// not exported: reached from a public declaration\n" + body
            by_entry.setdefault(_entry_name(path, surface.out), []).append(body)
    for entry in sorted(by_entry):
        lines += [f"## `{entry}`", "", "```ts"]
        lines.append("\n\n".join(sorted(by_entry[entry], key=_sort_key)))
        lines += ["```", ""]
    return "\n".join(lines).rstrip() + "\n"


def _sort_key(declaration: str) -> tuple[str, str, str]:
    """Alphabetical, and TOTAL: `CreateReminder` (a type) and
    `createReminder` (a function) are one name lower-cased, and left
    there their order came from Python's hash order, which changes from
    run to run -- a report that differed with nothing changed, seen the
    second time it was made."""
    body = declaration.split("\n", 1)[1] if declaration.startswith("// not exported") else declaration
    match = _DECLARATION.match(body)
    name = (match["name"] or match["local"]) if match and (match["name"] or match["local"]) else "default"
    return name.lower(), name, declaration


def build() -> tuple[str, list[str]]:
    used = used_by_modules()
    with tempfile.TemporaryDirectory(prefix="module-api-") as temp:
        out = Path(temp)
        emit_declarations(out)
        surface = Surface(out)
        for entry, names in sorted(used.items()):
            path = declaration_file(source_of(entry), out)
            for name in sorted(names):
                surface.make_public(path, name, entry)
        return render(surface, used), surface.problems


def main(argv: list[str]) -> int:
    report, problems = build()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    if "--check" in argv:
        current = REPORT.read_text() if REPORT.is_file() else ""
        if current != report:
            print(f"{REPORT.relative_to(ROOT)} is stale: the public module API changed.\n"
                  f"Run `python -m scripts.module_api_report` and commit the result, "
                  f"reviewing its diff as an API change.", file=sys.stderr)
            return 1
        return 0
    REPORT.write_text(report)
    print(f"wrote {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
