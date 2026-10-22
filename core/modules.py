"""
modules.py  (which sub-apps this deployment loads, and what each offers)

BLOCKING.md item 3, step 1: every sub-app is a MODULE, and Elysium's
own are equals of any other. A module is a folder with a `module.json`
manifest, which states what it contributes -- pages, rail entries, old
addresses kept -- and, for Elysium, which permission a person needs to
be offered it. The shell (`shell/`, `@shell/core`) reads the feed this
builds; the shell itself knows nothing about Elysium.

WHICH MODULES: `modules.yaml` beside the other configuration files,

    home: /query
    modules:
      - ui/packages/app-browse
      - ui/packages/app-query
      ...

each a folder holding a `module.json`, relative to Elysium's own
directory or absolute. ABSENT, the five sub-apps Elysium ships are
loaded in their usual order -- so a deployment written before modules
existed is unchanged, and listing them is how one is dropped.

CHECKED AT LOAD, like every other configuration file: a manifest that
cannot be read, names a page twice, or declares a rail entry leading
nowhere is refused with the file named, at startup or reload, rather
than surfacing as a broken rail for whoever looks first.

THE FEED IS THE CONTRACT'S, not Elysium's: shell/README.md. What is
Elysium's own here is `permission` -- the grant that decides whether a
person is offered a module at all, which used to be api/apps.py's
hand-written `gating_permission`.

A MODULE WITH ITS OWN BUNDLE (step 1.2) names it in its manifest:

    "entry": "dist/index.js",
    "styles": ["dist/index.css"]

paths inside its folder, both in ONE directory -- the bundle's -- which
is all Elysium will serve of the folder (`bundle_file`, and the route
GET /api/modules/{id}/files/{path}). The feed turns them into those
addresses. A module without `entry` is built into the page, as every
sub-app was before modules.

A BUNDLE NOT YET BUILT IS NOT A LOAD ERROR. The manifest is checked at
startup, which in development and in the test suite comes before any
`npm run build`; the shell says the module could not be loaded when
someone opens its page, and the server stays up.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from core.config import load_yaml
from core.intermediate_layer.auth import UserRecord, authorize

#: The contract version the feed speaks (shell/core/src/contract.ts).
CONTRACT_VERSION = 1

#: Elysium's own directory, against which module paths resolve.
ELYSIUM_ROOT = Path(__file__).resolve().parent.parent

#: What a deployment with no modules.yaml loads, in rail order.
SHIPPED_MODULES = ("ui/packages/app-browse", "ui/packages/app-query",
                   "ui/packages/app-schema", "ui/src/inbox",
                   "ui/packages/app-admin")
SHIPPED_HOME = "/query"

_MANIFEST_KEYS = frozenset({"id", "name", "version", "permission", "contributes", "entry", "styles",
                            "activationEvents"})
#: When a module's code runs besides its pages opening (contract.ts,
#: ACTIVATION_EVENTS). REFUSED HERE when unknown, unlike in the shell: a
#: misspelt event in a module.json is a mistake to say at load, while a
#: shell meeting a newer backend's event ignores it.
_ACTIVATION_EVENTS = frozenset({"onPalette"})
_CONTRIBUTION_KEYS = frozenset({"pages", "nav", "redirects"})


class ModuleError(ValueError):
    """A module that cannot be loaded, said with its file."""


@dataclass(frozen=True)
class Module:
    id: str
    name: str
    version: str
    #: Who is offered it: None for every signed-in person.
    permission: "str | None"
    contributes: Mapping
    #: The bundle's path inside `folder`, or None when the page supplies
    #: the code.
    entry: "str | None"
    folder: Path
    #: Stylesheets inside the bundle's directory.
    styles: tuple[str, ...] = ()
    #: When its code runs besides its pages opening, e.g. onPalette.
    activation_events: tuple[str, ...] = ()

    @property
    def bundle_directory(self) -> "Path | None":
        """The one directory of the folder Elysium serves, or None."""
        return None if self.entry is None else (self.folder / self.entry).parent


@dataclass(frozen=True)
class Modules:
    home: str
    modules: tuple[Module, ...]


def load_modules(config_dir: Path) -> Modules:
    """The deployment's modules, checked; see the module docstring."""
    path = config_dir / "modules.yaml"
    if not path.exists():
        folders, home = list(SHIPPED_MODULES), SHIPPED_HOME
    else:
        raw = load_yaml(path) or {}
        if not isinstance(raw, Mapping):
            raise ModuleError(f"{path}: must be a mapping with `modules:`")
        unknown = sorted(set(raw) - {"home", "modules"})
        if unknown:
            raise ModuleError(f"{path}: does not understand {unknown}")
        folders, home = raw.get("modules") or [], raw.get("home", SHIPPED_HOME)
        if not isinstance(folders, list) or not all(isinstance(f, str) for f in folders):
            raise ModuleError(f"{path}: `modules` must be a list of folders")
        if not isinstance(home, str) or not home.startswith("/"):
            raise ModuleError(f"{path}: `home` must be a path such as /query")
    loaded: list[Module] = []
    for folder in folders:
        module = _load_manifest(_resolve(folder))
        if any(other.id == module.id for other in loaded):
            raise ModuleError(f"{module.folder}: a module called {module.id!r} is already loaded")
        loaded.append(module)
    # HOME MUST OPEN SOMETHING. Every address nothing claims is sent
    # there, so a home no module mounts -- a modules.yaml that dropped
    # Query and kept the default -- would send every stray link to an
    # address that opens nothing.
    mounted = {page["path"] for m in loaded for page in m.contributes.get("pages") or []}
    if loaded and home not in mounted:
        raise ModuleError(f"{path}: `home` is {home}, which no loaded module's page is at")
    return Modules(home=home, modules=tuple(loaded))


def _resolve(folder: str) -> Path:
    path = Path(folder)
    return path if path.is_absolute() else ELYSIUM_ROOT / path


def _load_manifest(folder: Path) -> Module:
    path = folder / "module.json"
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        raise ModuleError(f"{folder}: has no module.json") from None
    except ValueError as e:
        raise ModuleError(f"{path}: is not JSON ({e})") from e
    if not isinstance(raw, Mapping):
        raise ModuleError(f"{path}: must be an object")
    unknown = sorted(set(raw) - _MANIFEST_KEYS)
    if unknown:
        raise ModuleError(f"{path}: does not understand {unknown}")
    for key in ("id", "name", "version"):
        if not isinstance(raw.get(key), str) or not raw[key]:
            raise ModuleError(f"{path}: needs `{key}`, a string")
    contributes = raw.get("contributes") or {}
    _check_contributions(path, contributes)
    permission = raw.get("permission")
    if permission is not None and not isinstance(permission, str):
        raise ModuleError(f"{path}: `permission` must be a grant such as manage:users, or absent")
    entry = raw.get("entry")
    if entry is not None and not _is_inside(entry):
        raise ModuleError(f"{path}: `entry` must be a path inside the module's folder, such as "
                          f"dist/index.js, or absent")
    styles = raw.get("styles") or []
    if not isinstance(styles, list) or not all(isinstance(s, str) and _is_inside(s) for s in styles):
        raise ModuleError(f"{path}: `styles` must be a list of paths inside the module's folder")
    if styles and entry is None:
        raise ModuleError(f"{path}: `styles` belong to a bundle, and this module names no `entry`")
    if entry is not None and any(Path(s).parent != Path(entry).parent for s in styles):
        raise ModuleError(f"{path}: `styles` must sit beside `entry`, in {Path(entry).parent}/ -- "
                          f"the one directory Elysium serves")
    events = raw.get("activationEvents") or []
    if not isinstance(events, list) or not all(isinstance(e, str) for e in events):
        raise ModuleError(f"{path}: `activationEvents` must be a list of event names")
    unknown_events = sorted(set(events) - _ACTIVATION_EVENTS)
    if unknown_events:
        raise ModuleError(f"{path}: knows no activation event called {unknown_events}; "
                          f"there are {sorted(_ACTIVATION_EVENTS)}")
    return Module(id=raw["id"], name=raw["name"], version=raw["version"],
                  permission=permission, contributes=contributes, entry=entry, folder=folder,
                  styles=tuple(styles), activation_events=tuple(events))


def _is_inside(relative: object) -> bool:
    """A relative path that stays inside the folder it is relative to."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        return False
    candidate = Path(relative)
    return not candidate.is_absolute() and ".." not in candidate.parts


def _check_contributions(path: Path, contributes) -> None:
    if not isinstance(contributes, Mapping):
        raise ModuleError(f"{path}: `contributes` must be an object")
    unknown = sorted(set(contributes) - _CONTRIBUTION_KEYS)
    if unknown:
        raise ModuleError(f"{path}: contributes nothing called {unknown}")
    pages = contributes.get("pages") or []
    ids, paths = set(), set()
    for page in pages:
        if not isinstance(page, Mapping) or not isinstance(page.get("id"), str) \
                or not isinstance(page.get("path"), str) or not page["path"].startswith("/"):
            raise ModuleError(f"{path}: each page needs an `id` and a `path` starting with /")
        if page["id"] in ids or page["path"] in paths:
            raise ModuleError(f"{path}: the page {page['id']} at {page['path']} is declared twice")
        ids.add(page["id"])
        paths.add(page["path"])
    for entry in contributes.get("nav") or []:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("title"), str) \
                or entry.get("path") not in paths:
            raise ModuleError(f"{path}: each rail entry needs a `title` and the `path` of one of "
                              f"the module's own pages")
    for redirect in contributes.get("redirects") or []:
        if not isinstance(redirect, Mapping) or not isinstance(redirect.get("from"), str) \
                or not isinstance(redirect.get("to"), str):
            raise ModuleError(f"{path}: each redirect needs `from` and `to`")


def offered_to(modules: Modules, user: UserRecord, roles: dict) -> list[Module]:
    """The modules one signed-in person may be offered."""
    return [m for m in modules.modules
            if m.permission is None or authorize(user, roles, m.permission)]


#: Where a module's bundle files are served, under the API's prefix.
FILES_ROUTE = "/api/modules/{id}/files/{path}"


def _address(module: Module, relative: str) -> str:
    """A bundle file's address, carrying a FINGERPRINT of its contents.

    THE BROWSER IMPORTS A URL ONCE PER PAGE: a module at the same address
    is the same module until the page reloads, whatever the server now
    holds. A rebuilt bundle -- every save, in development -- must
    therefore come at a NEW address, or the loader would `activate` the
    old code after `deactivate` had torn it down. The fingerprint is the
    file's own hash, so it changes exactly when the file does; the route
    ignores the query.
    """
    address = FILES_ROUTE.format(id=module.id, path=relative)
    fingerprint = _fingerprint(module.folder / relative)
    return address if fingerprint is None else f"{address}?v={fingerprint}"


#: Fingerprints by (path, mtime, size), so a feed request hashes a bundle
#: only when it has changed.
_fingerprints: dict[tuple[str, float, int], str] = {}


def _fingerprint(path: Path) -> "str | None":
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_mtime, stat.st_size)
    if key not in _fingerprints:
        _fingerprints[key] = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return _fingerprints[key]


def feed_for(modules: Modules, user: UserRecord, roles: dict) -> dict:
    """The module feed for one signed-in person: the contract's shape,
    holding only the modules they may be offered."""
    return {
        "contract": CONTRACT_VERSION,
        "home": modules.home,
        "modules": [{"id": m.id, "name": m.name, "version": m.version,
                     "contributes": _plain(m.contributes),
                     "entry": None if m.entry is None else _address(m, m.entry),
                     "styles": [_address(m, s) for s in m.styles],
                     "activationEvents": list(m.activation_events)}
                    for m in offered_to(modules, user, roles)],
    }


def bundle_file(module: Module, relative: str) -> "Path | None":
    """The file `relative` names in the module's bundle directory, or None
    -- for a module with no bundle, a path leaving that directory, or no
    such file. The only files of a module Elysium serves."""
    directory = module.bundle_directory
    if directory is None or not _is_inside(relative):
        return None
    try:
        candidate = (module.folder / relative).resolve()
        if not candidate.is_relative_to(directory.resolve()) or not candidate.is_file():
            return None
    except (OSError, ValueError):
        # A NAME NO FILE CAN HAVE -- an embedded NUL raises ValueError from
        # the filesystem call -- is absent like any other, not a 500.
        return None
    return candidate


def _plain(value):
    """A frozen configuration value back as plain JSON data."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value
