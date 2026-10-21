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
"""

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

_MANIFEST_KEYS = frozenset({"id", "name", "version", "permission", "contributes", "entry"})
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
    #: A bundle's address, or None when the page supplies the code.
    entry: "str | None"
    folder: Path


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
    if entry is not None and not isinstance(entry, str):
        raise ModuleError(f"{path}: `entry` must be a bundle's path, or absent")
    return Module(id=raw["id"], name=raw["name"], version=raw["version"],
                  permission=permission, contributes=contributes, entry=entry, folder=folder)


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


def feed_for(modules: Modules, user: UserRecord, roles: dict) -> dict:
    """The module feed for one signed-in person: the contract's shape,
    holding only the modules they may be offered."""
    offered = [m for m in modules.modules
               if m.permission is None or authorize(user, roles, m.permission)]
    return {
        "contract": CONTRACT_VERSION,
        "home": modules.home,
        "modules": [{"id": m.id, "name": m.name, "version": m.version,
                     "contributes": _plain(m.contributes), "entry": m.entry} for m in offered],
    }


def _plain(value):
    """A frozen configuration value back as plain JSON data."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value
