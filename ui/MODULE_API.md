# The module API

For someone writing a module for Elysium: what it may rely on, and what
Elysium promises about each part. **Version 1.0.**

There are two halves. The **names** a module may import, with their
signatures, are in [`module-api.report.md`](module-api.report.md): a
generated file, held current by a test. Everything else is here, in
prose: the manifest, what `activate()` returns, the host values, styles,
the shared libraries, building and testing, and the add-on server's
contract. `tests/unit/test_the_module_api_guide_matches_the_code.py`
holds this page's lists to the code.

## The version

The page offers **module API 1.0** (`MODULE_API_VERSION` in
`shell/core/src/contract.ts`). A module says what it needs in its
`module.json`:

```json
"api": "^1.0"
```

That means 1.0 or any later 1.x, as VS Code's `engines.vscode` does.

- An **addition** raises the minor number (1.1). A module built for 1.0
  still loads.
- A **change or a removal** raises the major number (2.0). A module
  built for 1.x stops loading until it is rebuilt.

A module that needs a version the page does not offer, or that names
none, is not loaded. The page leaves it out of the routes, the rail and
the palette. **System → Modules** still lists it, with the reason, such
as "Not loaded: it needs the module API ^2.0, and this page offers
1.0". Elysium itself still starts. Only a version written in a form it
does not understand (`"1.0"`, `">=1.0"`) is refused when the server
loads.

What raises which number is a judgement made in review. The report's
diff is what shows it: a declaration added is an addition, one changed
or gone is a change.

## The manifest: `module.json`

A module is a folder with a `module.json`, listed in the deployment's
`modules.yaml`. The server checks it when Elysium starts or reloads,
and refuses one it cannot read with the file named.

| key                | what it is                                                                                                                                                         |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `id`               | Required. Unique among the deployment's modules. It names the module in addresses (`/api/modules/{id}/...`) and in grants (`module:{id}:...`).                     |
| `name`             | Required. What a person reads in the module manager.                                                                                                               |
| `version`          | Required. The module's own version, shown in the module manager. It is not the API version.                                                                        |
| `api`              | The module API version it needs, `"^1.0"`. A module without it is not loaded.                                                                                      |
| `contributes`      | What it adds to the frame, read without running its code. See below.                                                                                               |
| `entry`            | Its bundle, a path inside its folder such as `dist/index.js`. Without it, the module's code must be built into Elysium's page, which only the System sub-app's is. |
| `styles`           | Stylesheets beside `entry`, in the same directory, such as `dist/index.css`. The shell adds them when the module loads and removes them when it unloads.           |
| `activationEvents` | When the shell asks for its code besides its pages opening. See below.                                                                                             |
| `permission`       | A grant a person needs to be offered the module at all, such as `manage:users`. Absent: everyone signed in is offered it.                                          |
| `permissions`      | Permissions it declares, `[{"id": "operate", "description": "..."}]`, granted to roles as `module:{id}:operate` in the role editor.                                |
| `server`           | A server of its own, which Elysium starts and proxies. See the add-on server below.                                                                                |

Any other key is refused, so a misspelt one is found when Elysium starts
rather than ignored.

Only the bundle's directory is served (`GET
/api/modules/{id}/files/{path}`), never the rest of the folder. Each
address carries a fingerprint of the file's contents, so a rebuilt
bundle comes at a new address.

### `contributes`

| key         | what it is                                                                                                                                                                                      |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pages`     | `[{"id": "search", "path": "/browse"}]`. Each page is a route the shell mounts, its `path` a react-router path. `activate()` gives the component for each `id`.                                 |
| `nav`       | `[{"title": "Browse", "path": "/browse", "subject": "Objects"}]`. Rail entries, each leading to one of the module's own pages. `subject` groups the rail by what a person is working on.        |
| `redirects` | `[{"from": "/approvals", "to": "/inbox?tab=approvals"}]`. Old addresses that still lead somewhere.                                                                                              |
| `slots`     | `[{"id": "inbox.tabs", "order": ["approvals", "notifications"]}]`. A place in one of its own pages that other modules may fill. The owner draws it with `useSlot(id)` from `@shell/core/slots`. |
| `into`      | `[{"slot": "inbox.tabs", "id": "identity", "title": "Identity", "icon": "people"}]`. Contributions to another module's slot. `activate()` gives the component for each `id`.                    |

A page declared twice, a rail entry leading nowhere, a slot declared by
two modules, or a contribution to a slot nobody declares is refused when
Elysium loads.

### `activationEvents`

| event       | when                                                                                                                        |
| ----------- | --------------------------------------------------------------------------------------------------------------------------- |
| `onPalette` | The first time the command palette opens, on any screen. The shell reads `usePalette`.                                      |
| `onStartup` | As soon as the frame is drawn. The shell reads `useBadges`, for a badge on the module's rail entry that is on every screen. |

Without either, a module's code is fetched when one of its pages, or one
of its contributions, is first shown.

## The bundle: `activate()`

A bundle is an ES module that exports:

```ts
export function activate(context: ModuleContext): ModuleActivation | Promise<ModuleActivation>
export function deactivate(): void // optional
```

`context` holds the module's `id` and `version`. `activate` runs once,
the first time the shell needs the module's code. `deactivate` runs when
the module is unloaded: turned off in the module manager, or replaced by
a rebuilt bundle. The browser keeps imported code until the page
reloads.

What `activate()` returns:

| key             | what it is                                                                                                                                                                                                                                                                     |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `pages`         | Required. A component for each page `id` the manifest declares. A page may be `lazy(() => import('./Page'))`: the shell draws it inside a Suspense boundary, and the chunk is fetched when the page first opens. Browse does this, so the palette fetches only its 3 KB entry. |
| `contributions` | A component for each `into` id the manifest declares. Each is drawn with the props its slot's owner documents. The Inbox's `inbox.tabs` gives `onSessionExpired`.                                                                                                              |
| `usePalette`    | A hook, `({ open }) => { before?, after?, suggest? }`, giving commands for the palette. Read for a module naming `onPalette`.                                                                                                                                                  |
| `useBadges`     | A hook giving `{ [railPath]: { count, label } }` for the module's own rail entries. Read for a module naming `onStartup`. A badge for another module's entry is ignored.                                                                                                       |

A page owns everything inside the content area. It touches the frame
only through what it declares and through these hooks.

## What the page gives a module: host values

Read with `useHostValues()` from `@elysium/shell-api/host`. They update
in place, and a page re-renders when they change.

| value              | what it is                                                                                                                                                                                           |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `visibleSchema`    | The object types and fields this person may see; `null` until fetched.                                                                                                                               |
| `username`         | Who is signed in; `''` until known.                                                                                                                                                                  |
| `onSessionExpired` | Call it when a request finds the session expired (`handleIfSessionExpired` in `@elysium/shell-api/api` does it for you). The sign-in form comes back. Every page must; the conformance suite checks. |

## Shared libraries

These are the page's own copies, shared with every module as one
instance. A module's bundle leaves them as bare imports, and the build
refuses a deep import that would bundle a second copy of part of one.

- `react`, `react/jsx-runtime`, `react/jsx-dev-runtime`
- `react-dom`, `react-dom/client`
- `react-router-dom`, `react-router`
- `@blueprintjs/core`
- `echarts/core`, `echarts/charts`, `echarts/components`, `echarts/renderers`
- `@shell/core` and `@elysium/shell-api`: only the names in the report
  are public.

A module may bundle any other library it needs. Its copy is its own.

## Styles

- **Tokens.** Colour, type, spacing, radii and elevation come from the
  design tokens (`--surface-*`, `--text-*`, `--space-*` and the rest, in
  `ui/packages/shell-api/src/tokens.css`), defined for light and dark.
  A module uses the tokens, not raw colours. Elysium's own stylesheets
  are held to that by `tokens.test.ts`.
- **The `components` layer.** Every rule a module authors sits inside
  `@layer components { ... }`. A rule outside every layer beats every
  layer, Blueprint's included. The conformance suite checks.
- **Its own stylesheet.** A module imports its CSS from its entry
  (`import './browse.css'`). The build writes it beside the bundle as
  `dist/index.css`, which the manifest's `styles` names. It is added
  when the module loads and removed when it unloads.

## Building and testing

A module built in this repository has, beside its `module.json`:

- `vite.config.ts`, building with `moduleConfig` from
  `@shell/build/moduleBuild`. `npm run build` builds it with the page,
  and `npm run dev` rebuilds it on save.
- `vitest.config.ts`, using `moduleTestConfig` from
  `@shell/build/testPreset`, so it runs as a test project of its own:
  `npx vitest run --project app-query`.
- `src/conformance.test.tsx`, calling `describeModule` from
  `@elysium/testing/conformance`, with the module's `activate`. It
  checks:
  - the manifest, including that the page would load it;
  - that every rule is layered;
  - for each page and contribution: that it renders, says it is
    loading, announces an error, hands over an expired session, and
    leaves nothing running when unmounted.

  A module whose pages need data the default host lacks passes
  `hostValues`. An exception goes in `module.conformance.json` with its
  reason, as `todo`, `off`, or `replaced` by a named test of its own.

The simulator's panel (`sim/panel/`) is the example of a module built
outside `ui/packages/`, with its build config in
`ui/addons/simulator.vite.config.ts`.

## The add-on server

A module may bring a server of its own:

```json
"server": {"command": ["{python}", "server.py"], "health": "/health", "stopSeconds": 10}
```

Elysium starts it in the module's folder and forwards
`/api/addons/{id}/...` to it, as its proxy. The contract, in full, is
the docstring of `sdk/python/elysium_addon.py`, the file an add-on
copies:

- **Starting.** `PORT` to listen on, on `127.0.0.1` only, and
  `ELYSIUM_ADDON_START`, a JSON file holding its options from
  `addons.yaml`, its data directory, its outbox and the identity secret.
  The start file's own format is `"contract": 1`, checked by the SDK.
- **Health.** `GET` on `health` answers 200. Three failures in a row
  once running, and Elysium restarts it, backing off from 1 second to 60.
- **Stopping.** SIGTERM, then SIGKILL after `stopSeconds`. Its standard
  input closes when Elysium goes, even when Elysium is killed:
  `exit_when_elysium_does()` watches it.
- **Who is asking.** Every request carries `X-Elysium-Identity`, an
  HS256 token with `sub` and the module's own `permissions`. Verify it
  with `identity()`. Trust nothing else: cookies and `Authorization`
  never reach it.
- **The Inbox.** `post()` drops a notice in its outbox, and Elysium
  delivers it to the people named, or to everyone offered the module.
  If Elysium is down, it delivers it when it is back.

An add-on tests its server against the same contract with
`sdk/python/elysium_addon_checks.py`, a test class to subclass.
