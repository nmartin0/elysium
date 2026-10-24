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

OFF, BUT KNOWN (step 1.4c): `disabled:` marks which of the modules
`modules` lists are turned off. They are checked like the rest, loaded
nowhere, and KEEP THEIR PLACE on the rail, to come back to it when the
module manager turns them on again:

    home: /query
    modules:
      - ui/packages/app-browse
      - ui/packages/app-schema
      ...
    disabled:
      - ui/packages/app-schema

`disabled`, NOT `off`: YAML 1.1 reads a bare `off:` key as the boolean
false, so a hand edit would have said nothing anyone meant. Found by the
test of a written arrangement loading back.

The module manager writes this file (`render_modules_yaml`) through the
same validated, atomic, audited path as every configuration edit.

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

A MODULE WITH A SERVER OF ITS OWN (step 2) declares it under `server`;
Elysium starts it and forwards /api/addons/{id}/... to it. core/addons.py.

A BUNDLE NOT YET BUILT IS NOT A LOAD ERROR. The manifest is checked at
startup, which in development and in the test suite comes before any
`npm run build`; the shell says the module could not be loaded when
someone opens its page, and the server stays up.
"""

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType

from core.addons import AddonError, ServerSpec, parse_server
from core.config import load_yaml
from core.intermediate_layer.auth import UserRecord, authorize
from core.secret_references import expand_secrets

#: The contract version the feed speaks (shell/core/src/contract.ts).
CONTRACT_VERSION = 1

#: Elysium's own directory, against which module paths resolve.
ELYSIUM_ROOT = Path(__file__).resolve().parent.parent

#: What a deployment with no modules.yaml loads, in rail order.
SHIPPED_MODULES = ("ui/packages/app-browse", "ui/packages/app-query",
                   "ui/packages/app-schema", "ui/packages/app-inbox",
                   # The Inbox's queues (step 1.5b): no rail entry of their
                   # own, a tab each in the Inbox's slot, and each
                   # switchable alone in the module manager.
                   "ui/packages/app-approvals", "ui/packages/app-notifications",
                   "ui/packages/app-identity",
                   "ui/packages/app-admin")
SHIPPED_HOME = "/query"

logger = logging.getLogger(__name__)

#: SHIPPED MODULES THAT HAVE MOVED FOLDER, old to new. A modules.yaml
#: naming the old folder -- the module manager writes the folders it read
#: -- is read as naming the new one, with a warning saying which file to
#: change; the module manager writes the new one on its next save. The
#: owner's choice (23 October), over refusing the file: refusing would
#: stop Elysium starting over a move it made itself.
MOVED_MODULES = MappingProxyType({
    # BLOCKING.md item 3, step 3: the Inbox into a package of its own.
    "ui/src/inbox": "ui/packages/app-inbox",
})

#: THE SYSTEM SUB-APPS (BLOCKING.md item 3, step 1.4): always loaded,
#: after every module `modules.yaml` names, and PINNED -- the shell
#: loads them in safe mode and nothing in the interface turns them off,
#: because safe mode exists for when a module breaks the page, and a
#: module must not be able to take away the tool that fixes it. Not
#: listable in modules.yaml, for the same reason: an edit to that file,
#: the module manager's included, cannot drop them.
#:
#: The shell's own, today: the module manager. The server's (Elysium's
#: configuration, silos, the mirror) joins it when Admin splits.
SYSTEM_MODULES = ("ui/src/system",)

_MANIFEST_KEYS = frozenset({"id", "name", "version", "permission", "contributes", "entry", "styles",
                            "activationEvents", "server", "permissions", "api"})
#: When a module's code runs besides its pages opening (contract.ts,
#: ACTIVATION_EVENTS). REFUSED HERE when unknown, unlike in the shell: a
#: misspelt event in a module.json is a mistake to say at load, while a
#: shell meeting a newer backend's event ignores it.
_ACTIVATION_EVENTS = frozenset({"onPalette", "onStartup"})
#: The module API a module needs (step 4; shell/core/src/contract.ts,
#: MODULE_API_VERSION): "^1.0" and only that form. REFUSED HERE when
#: malformed, a mistake to say at load like a misspelt event. Whether the
#: page OFFERS what a module needs -- or one names none -- is the shell's
#: to decide, where the page's version is: it leaves the module out, and
#: its module manager says why, rather than Elysium refusing to start.
_API_RANGE = re.compile(r"\^(0|[1-9]\d*)\.(0|[1-9]\d*)")
_CONTRIBUTION_KEYS = frozenset({"pages", "nav", "redirects", "slots", "into"})


def _moved(path: Path, folder: str) -> str:
    """`folder` as modules.yaml names it, or where it has moved to
    (MOVED_MODULES), said in the log."""
    for old, new in MOVED_MODULES.items():
        if _resolve(folder) == _resolve(old):
            logger.warning(f"{path}: {folder} has moved to {new}; read as {new}. "
                           f"Change it in the file, or save the arrangement in System -> Modules, "
                           f"which writes the new folder")
            return new
    return folder


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
    #: A system sub-app: loaded in safe mode, never turned off.
    pinned: bool = False
    #: The folder as modules.yaml names it (or Elysium's default list),
    #: so the module manager can write it back as it was written.
    listed_as: str = ""
    #: Its own server (step 2, core/addons.py), or None: most have none.
    server: "ServerSpec | None" = None
    #: The permissions it declares, (name, description): each a grant
    #: `module:<id>:<name>` a role may hold (module_grant).
    permissions: tuple[tuple[str, str], ...] = ()
    #: The module API it needs, "^1.0", or None when it names none.
    api: "str | None" = None

    @property
    def bundle_directory(self) -> "Path | None":
        """The one directory of the folder Elysium serves, or None."""
        return None if self.entry is None else (self.folder / self.entry).parent


@dataclass(frozen=True)
class Modules:
    home: str
    modules: tuple[Module, ...]
    #: Known and turned off (`disabled:` in modules.yaml): loaded nowhere.
    off: tuple[Module, ...] = ()
    #: Every module modules.yaml lists, on and off, in its order: an off
    #: module keeps its place, to come back to it when turned on.
    order: tuple[str, ...] = ()
    #: `addons.yaml`: each add-on server's options, by module id, its
    #: ${VAR} references already filled from the environment.
    addon_options: Mapping = MappingProxyType({})


def load_modules(config_dir: Path) -> Modules:
    """The deployment's modules, checked; see the module docstring."""
    path = config_dir / "modules.yaml"
    off_folders: list[str] = []
    if not path.exists():
        folders, home = list(SHIPPED_MODULES), SHIPPED_HOME
    else:
        raw = load_yaml(path) or {}
        if not isinstance(raw, Mapping):
            raise ModuleError(f"{path}: must be a mapping with `modules:`")
        unknown = sorted(set(raw) - {"home", "modules", "disabled"}, key=str)
        if unknown:
            raise ModuleError(f"{path}: does not understand {unknown}")
        folders, home = raw.get("modules") or [], raw.get("home", SHIPPED_HOME)
        if not isinstance(folders, list) or not all(isinstance(f, str) for f in folders):
            raise ModuleError(f"{path}: `modules` must be a list of folders")
        off_folders = raw.get("disabled") or []
        if not isinstance(off_folders, list) or not all(isinstance(f, str) for f in off_folders):
            raise ModuleError(f"{path}: `disabled` must be a list of folders")
        if not isinstance(home, str) or not home.startswith("/"):
            raise ModuleError(f"{path}: `home` must be a path such as /query")
        folders = [_moved(path, folder) for folder in folders]
        off_folders = [_moved(path, folder) for folder in off_folders]
    system = {_resolve(f) for f in SYSTEM_MODULES}
    disabled = {_resolve(f) for f in off_folders}
    listed = {_resolve(f) for f in folders}
    strays = sorted(f for f in off_folders if _resolve(f) not in listed)
    if strays:
        raise ModuleError(f"{path}: `disabled` names {strays}, which `modules` does not list; "
                          f"list it there, in its place on the rail, and here to turn it off")
    loaded: list[Module] = []
    off: list[Module] = []
    order: list[str] = []
    for folder in folders:
        if _resolve(folder) in system:
            raise ModuleError(f"{path}: {folder} is a system sub-app, always loaded and pinned; "
                              f"leave it out of `modules`")
        module = replace(_load_manifest(_resolve(folder)), listed_as=folder)
        if module.id in order:
            raise ModuleError(f"{module.folder}: a module called {module.id!r} is already listed")
        order.append(module.id)
        (off if _resolve(folder) in disabled else loaded).append(module)
    for folder in SYSTEM_MODULES:
        module = replace(_load_manifest(_resolve(folder)), pinned=True, listed_as=folder)
        if module.id in order:
            raise ModuleError(f"{module.folder}: a module called {module.id!r} is already loaded, "
                              f"and that id is a system sub-app's")
        loaded.append(module)
    _check_slots(path, loaded + off)
    _check_module_permissions(path, loaded + off)
    # HOME MUST OPEN SOMETHING. Every address nothing claims is sent
    # there, so a home no module mounts -- a modules.yaml that dropped
    # Query and kept the default -- would send every stray link to an
    # address that opens nothing.
    mounted = {page["path"] for m in loaded for page in m.contributes.get("pages") or []}
    if loaded and home not in mounted:
        raise ModuleError(f"{path}: `home` is {home}, which no loaded module's page is at")
    options = load_addon_options(config_dir, loaded + off)
    return Modules(home=home, modules=tuple(loaded), off=tuple(off), order=tuple(order),
                   addon_options=options)


def load_addon_options(config_dir: Path, known: "list[Module]") -> Mapping:
    """ADDONS.YAML: what a deployment tells an add-on's server at start
    (step 2.2). An add-on's MANIFEST says how to start it and travels with
    its code; what differs between deployments -- which world, which
    account, a password -- is the deployment's, beside its other files:

        simulator:
          options:
            world: /srv/sim/world
            token: ${SIM_TOKEN}

    Home Assistant's split: an add-on declares its options, the person
    installing it fills them in, and the add-on reads them at start.

    ${VAR} IS FILLED FROM ELYSIUM'S ENVIRONMENT HERE, AT LOAD
    (core/secret_references.py) -- a missing variable stops the load
    with its name -- and A LITERAL PASSWORD IS REFUSED, as in every
    other file. It is the one way a secret reaches an add-on: its
    server is started with a bare environment, not Elysium's, which
    holds every silo's credentials.

    Absent, every add-on starts with no options. Naming a module that is
    not listed, or has no server, is refused: it is a typo or a leftover.
    """
    path = config_dir / "addons.yaml"
    if not path.exists():
        return MappingProxyType({})
    raw = load_yaml(path) or {}
    if not isinstance(raw, Mapping):
        raise ModuleError(f"{path}: must be a mapping of module ids to {{options: ...}}")
    servers = {m.id for m in known if m.server is not None}
    options: dict[str, Mapping] = {}
    for module_id, block in raw.items():
        if module_id not in servers:
            raise ModuleError(f"{path}: {module_id!r} is not a listed module with a server of its own"
                              + (f"; those are {sorted(servers)}" if servers else ""))
        if not isinstance(block, Mapping) or set(block) - {"options"}:
            raise ModuleError(f"{path}: {module_id} takes only `options:`, a mapping")
        given = block.get("options") or {}
        if not isinstance(given, Mapping):
            raise ModuleError(f"{path}: {module_id}.options must be a mapping")
        try:
            options[module_id] = MappingProxyType(expand_secrets(dict(given), where=f"addons.yaml {module_id}.options"))
        except ValueError as error:
            raise ModuleError(f"{path}: {error}") from None
    return MappingProxyType(options)


def _check_module_permissions(path: Path, known: "list[Module]") -> None:
    """A module offered to holders of a DECLARED permission must name one
    that is declared: a misspelt `module:` grant there would offer the
    module to nobody, and say nothing."""
    declared = {module_grant(m.id, name) for m in known for name, _ in m.permissions}
    for module in known:
        if module.permission is not None and module.permission.startswith(MODULE_GRANT_PREFIX) \
                and module.permission not in declared:
            raise ModuleError(f"{module.folder}: is offered to {module.permission}, which no listed "
                              f"module declares under `permissions`")


def _check_slots(path: Path, known: "list[Module]") -> None:
    """SLOTS (step 1.5) across the deployment's modules, on and off: each
    slot declared once, and every contribution aimed at a slot some
    module declares -- a typo in `into` is said at load, not as a tab
    that silently never appears. A slot whose owner is turned off is
    still known: its contributions wait, unshown, for it to come back."""
    owners: dict[str, str] = {}
    for module in known:
        for slot in module.contributes.get("slots") or []:
            if slot["id"] in owners:
                raise ModuleError(f"{path}: the slot {slot['id']} is declared by both "
                                  f"{owners[slot['id']]} and {module.id}")
            owners[slot["id"]] = module.id
    for module in known:
        for item in module.contributes.get("into") or []:
            if item["slot"] not in owners:
                raise ModuleError(f"{module.folder}: contributes {item['id']} to the slot "
                                  f"{item['slot']}, which no module declares")


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
    api = raw.get("api")
    if api is not None and not (isinstance(api, str) and _API_RANGE.fullmatch(api)):
        raise ModuleError(f"{path}: `api` must be the module API version it needs, such as \"^1.0\"; "
                          f"it is {api!r}")
    permissions = _load_permissions(path, raw.get("permissions"))
    try:
        server = parse_server(path, raw.get("server"))
    except AddonError as error:
        raise ModuleError(str(error)) from None
    return Module(id=raw["id"], name=raw["name"], version=raw["version"],
                  permission=permission, contributes=contributes, entry=entry, folder=folder,
                  styles=tuple(styles), activation_events=tuple(events), server=server,
                  permissions=permissions, api=api)


#: A permission's name within its module: lower case, as grants are.
_PERMISSION_NAME = re.compile(r"[a-z][a-z0-9_-]{0,47}")
#: A module's declared permissions are granted as module:<id>:<name>.
MODULE_GRANT_PREFIX = "module:"


def module_grant(module_id: str, name: str) -> str:
    """The grant a role holds for one of a module's declared permissions."""
    return f"{MODULE_GRANT_PREFIX}{module_id}:{name}"


def _load_permissions(path: Path, raw) -> "tuple[tuple[str, str], ...]":
    """DECLARED PERMISSIONS (BLOCKING.md item 3, step 2.3): what a module
    lets a role do, each named and described for the role editor,

        "permissions": [{"id": "operate",
                         "description": "Start, stop, pause and break the world"}]

    and granted as `module:<module id>:<id>`. Grafana's plugins do the
    same: a plugin may "insert a `roles` section into your `plugin.json`
    file", its actions named after the plugin
    (`grafana-appwithrbac-app.patents:read`), and a page carrying an
    `action` "will only appear for users with the ... permission"."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ModuleError(f"{path}: `permissions` must be a list of {{id, description}}")
    found: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"id", "description"}:
            raise ModuleError(f"{path}: each permission needs an `id` and a `description`, and nothing else")
        name, description = item["id"], item["description"]
        if not isinstance(name, str) or not _PERMISSION_NAME.fullmatch(name):
            raise ModuleError(f"{path}: permission id {name!r} must be lower case letters, digits, "
                              f"_ and -, starting with a letter, such as operate")
        if not isinstance(description, str) or not description.strip():
            raise ModuleError(f"{path}: permission {name} needs a description, said to whoever "
                              f"grants it")
        if name in (n for n, _ in found):
            raise ModuleError(f"{path}: declares the permission {name} twice")
        found.append((name, description.strip()))
    return tuple(found)


def declared_permissions(modules: "Modules | None") -> "list[dict]":
    """THE MODULES' PART OF THE PERMISSIONS REGISTRY: every permission the
    listed modules declare, on and off, as the role editor offers them.
    Worked out from the manifests at each load, the owner's choice (22
    October), so it cannot disagree with what is installed; Elysium's own
    grants are worked out from the ontology the same way
    (policy_validation.grantable)."""
    if modules is None:
        return []
    return [{"grant": module_grant(m.id, name), "module": m.id, "module_name": m.name,
             "description": description}
            for m in [*modules.modules, *modules.off] for name, description in m.permissions]


def permissions_by_module(modules: "Modules | None") -> "dict[str, frozenset[str]]":
    """Each listed module's declared permission names, by module id: what
    validates a role's `module:` grants (policy_validation)."""
    if modules is None:
        return {}
    return {m.id: frozenset(name for name, _ in m.permissions) for m in [*modules.modules, *modules.off]}


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
    for slot in contributes.get("slots") or []:
        if not isinstance(slot, Mapping) or not isinstance(slot.get("id"), str) or not slot["id"] \
                or not all(isinstance(o, str) for o in slot.get("order") or []):
            raise ModuleError(f"{path}: each slot needs an `id`, and `order`, if given, a list of "
                              f"contribution ids")
    seen = set()
    for item in contributes.get("into") or []:
        if not isinstance(item, Mapping) or not all(isinstance(item.get(k), str) and item[k]
                                                    for k in ("slot", "id", "title")):
            raise ModuleError(f"{path}: each contribution in `into` needs a `slot`, an `id` and a `title`")
        if item["id"] in seen:
            raise ModuleError(f"{path}: the contribution {item['id']} is declared twice")
        seen.add(item["id"])


def arrangement(modules: Modules) -> dict:
    """What the module manager shows (step 1.4c): EVERY module the
    deployment knows -- on, in rail order, then off -- with whether each
    is on and pinned, and the pages each holds, for choosing home.

    NAMES, NEVER CONTENTS: no folder, no permission -- the same rule as
    the feed. A holder of manage:deployment could read modules.yaml, but
    an interface that never carries a path cannot leak one in a
    screenshot."""
    off = {m.id for m in modules.off}
    return arranged(modules, modules.home, [(i, i not in off) for i in modules.order])


def arranged(modules: Modules, home: str, order: "list[tuple[str, bool]]") -> dict:
    """The arrangement `order` describes, in `arrangement`'s shape, from
    the modules the deployment knows: what a save answers with, built
    from what it wrote rather than read back from the configuration
    now running -- which a route must not reach past its pinned
    generation to see (tests/unit/test_generation_pin.py)."""
    def row(module: Module, enabled: bool) -> dict:
        return {"id": module.id, "name": module.name, "version": module.version,
                "enabled": enabled, "pinned": module.pinned,
                "pages": [page["path"] for page in module.contributes.get("pages") or []]}
    known = {m.id: m for m in modules.modules + modules.off}
    return {"home": home,
            "modules": [row(known[i], enabled) for i, enabled in order]
            + [row(m, True) for m in modules.modules if m.pinned]}


def render_modules_yaml(modules: Modules, home: str, order: "list[tuple[str, bool]]") -> str:
    """modules.yaml for a new arrangement: `order` is every module the
    deployment knows, by id, each on or off, in the rail order wanted.

    REFUSES rather than guesses: an id it does not know, one left out,
    one twice, or a pinned one -- a system sub-app is always loaded and
    always last, so it is neither listed nor switchable. Whether the
    result LOADS (home opening something, manifests sound) is the
    loader's to say, run on the candidate before anything is written."""
    known = {m.id: m for m in modules.modules + modules.off if not m.pinned}
    ids = [module_id for module_id, _ in order]
    pinned = sorted({m.id for m in modules.modules if m.pinned} & set(ids))
    if pinned:
        raise ModuleError(f"{pinned} are system sub-apps: always on, always last, not arranged")
    unknown = sorted(set(ids) - set(known))
    if unknown:
        raise ModuleError(f"no module called {unknown} is known here")
    if len(set(ids)) != len(ids):
        raise ModuleError("a module is listed twice")
    missing = sorted(set(known) - set(ids))
    if missing:
        raise ModuleError(f"the arrangement leaves out {missing}; list every module, on or off")
    listed = [known[i].listed_as for i, _ in order]
    off = [known[i].listed_as for i, enabled in order if not enabled]
    lines = ["# Which sub-apps this deployment loads, in rail order (core/modules.py).",
             "# Written by the module manager; editing by hand is fine too.",
             f"home: {json.dumps(home)}"]
    lines += ["modules:"] + [f"  - {json.dumps(folder)}" for folder in listed] if listed else ["modules: []"]
    if off:
        lines += ["disabled:"] + [f"  - {json.dumps(folder)}" for folder in off]
    return "\n".join(lines) + "\n"


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
                     "activationEvents": list(m.activation_events),
                     **({} if m.api is None else {"api": m.api}),
                     "pinned": m.pinned}
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
