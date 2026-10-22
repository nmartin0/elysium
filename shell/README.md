# shell

A generic web shell for sub-apps: the frame they are mounted in, and the
contract any backend speaks to offer them. It knows nothing about
Elysium; Elysium is one backend that implements the contract
(`core/modules.py`, `api/routes.py`). BLOCKING.md item 3 records the
design and the order it is being built in.

```
shell/
  core/            @shell/core: the contract, the registry, the routes
    src/contract.ts      the feed's types, and checkFeed
    src/registry.ts      a feed -> pages, rail and redirects (pure)
    src/ModuleRoutes.tsx a registry -> react-router routes
    src/moduleLoader.tsx a module's bundle, stylesheets and lifecycle
    src/Frame.tsx        the frame: rail, header and command palette
    src/CommandPalette.tsx, src/commands.ts  the palette and its matching
    src/activation.ts    activating modules on their manifests' events
    src/palette.tsx      modules' palette commands
    src/badges.tsx       badges on modules' rail entries
    src/ModulesPage.tsx  the shell's system sub-app: every module, and its state
    src/safeMode.ts      safe mode: this tab, pinned modules only, until left
    src/ModuleArrangementEditor.tsx  the module manager: the arrangement for everyone
  build/           @shell/build: build-time tooling
    src/sharedLibraries.ts  the shared-library registry, shims and import map
    src/moduleBuild.ts      a module's bundle; building modules with the page
    src/testPreset.ts       the test configuration every module inherits
```

Its own npm project, with its own tests:

```
cd shell && npm install && npx vitest run && npx tsc --noEmit
```

A host depends on it by path (`"@shell/core": "file:../shell/core"`) and
must give the bundle one React and one Blueprint: Elysium's
`ui/vite.config.ts` dedupes `react`, `react-dom`, `react-router-dom` and
`@blueprintjs/core`, because a second React would give the shell's routes
a router context the page does not have, and a second Blueprint would
give the frame's dialogs an overlay stack of their own.

## The frame

The shell owns the frame -- the rail, the header and the command palette
-- and a sub-app owns everything inside the content area. `<Frame>` is a
react-router layout route; pages mount in its outlet.

```tsx
<Frame
  nav={feedNav}                 // rail entries: title, path, subject
  brand="Product"               // the name in the header
  actions={<UserMenu />}        // the header's actions, the host's own
  overlays={<HelpDialog />}     // dialogs kept beside the frame
  iconFor={(path) => icon}      // each rail entry's icon
  commands={{ before, after }}  // the host's commands, around navigation
  suggest={(query) => [...]}    // commands made from what was typed
  modules={{ feed, activate }}  // modules whose code adds commands, badges
  onPaletteOpen={load}          // told on each opening
  fallback={<Spinner />}        // while a page's code loads
  storageKey="product.rail"     // where the collapsed state is remembered
/>
```

MODULES ADD TO THE FRAME FROM THEIR CODE: palette commands, and badges
on their own rail entries. Pass `modules={{ feed: feed.modules, activate }}`,
where `activate(module)` returns the module's code (or a promise of it)
-- its bundle's activation, or the host's own code for a module built
into the page. The frame activates each module on the events its
manifest names (`@shell/core/activation`):

- `onPalette`, the first time the palette opens: the frame reads
  `usePalette`;
- `onStartup`, as soon as the frame is drawn: it reads `useBadges`.

Each is a React hook, mounted in a component of its own:

```ts
export function usePalette({ open }: { open: boolean }): PaletteContribution {
  // hooks as usual: where the person is, data fetched when `open`...
  return { before: [...], after: [...], suggest: (query) => [...] }
}
export function useBadges(): Record<string, Badge | undefined> {
  return { '/inbox': { count: 3, label: '3 waiting' } }   // its own entries only
}
```

Palette `before` lists sit ahead of the frame's navigation commands,
`after` behind them, each in feed order; suggestions follow every match.
A badge shows on the entry's icon (so a collapsed rail shows it too),
is announced after the entry's name, draws nothing for zero and "99+"
above 99; a badge for another module's entry is ignored. A module whose
code fails to activate adds nothing and is asked again the next time
its event comes round; one the feed stops offering drops out.

What the frame does itself: groups the rail by subject; collapses it
(the toggle, Ctrl/Cmd+B, remembered per browser; closed below 1100px
without storing that, and the stored choice restored above it; closed on
navigating while narrow); opens the palette on Ctrl/Cmd+K, even from a
text field; offers every rail entry as a navigation command.

STYLED BY THE HOST, for now. It draws Blueprint widgets (a peer
dependency) inside stable class names -- `app-frame`,
`app-frame--sidebar-collapsed`, `app__header`, `app__header-title`,
`app__header-actions`, `app__sidebar`, `app__sidebar-toggle`,
`app__nav`, `app__nav-subject`, `app__nav-label`, `app__nav-icon`,
`app__nav-badge`, `app__content`, `shell__safe-mode`,
`shell__safe-mode-leave`,
`command-palette*` -- which the host's stylesheet draws. A baseline look
every sub-app inherits is a later step.

## The contract, version 1

Plain HTTP and JSON under a base the host chooses (Elysium's is `/api`).

### `GET {base}/session`

Who is signed in, and how to sign in. Answers without a session --
nobody is an answer, not an error.

```json
{
  "user": { "id": "alice", "name": "alice" },
  "sign_in": { "kind": "form", "submit": "/api/login" }
}
```

`user` is `null` when nobody is signed in. A backend may add its own
fields beside these; Elysium adds `must_change_password`.

### `GET {base}/modules`

The modules this person is offered, and what each contributes. Needs a
session. **Filtered by the backend**: a module the person may not use
is absent, never sent and hidden.

```json
{
  "contract": 1,
  "home": "/query",
  "modules": [
    {
      "id": "query",
      "name": "Query",
      "version": "1.0.0",
      "entry": null,
      "contributes": {
        "pages": [{ "id": "query", "path": "/query" }],
        "nav": [{ "title": "Query", "path": "/query", "subject": "Objects" }],
        "redirects": [{ "from": "/ask", "to": "/query" }]
      }
    }
  ]
}
```

- `contract` -- a shell refuses a feed in another version by name
  rather than half-reading it.
- `home` -- where an address nothing claims is sent. If no page this
  person is offered is at `home`, such an address says nothing opens
  it rather than redirecting in a loop. Elysium refuses at load a
  `home` that no loaded module's page is at.
- `entry` -- the address of the module's code bundle, or `null` when
  the page already has the code built in.
- `styles` -- optional: stylesheets the bundle needs, added when it
  loads and removed when it unloads.
- `pinned` -- optional: a SYSTEM SUB-APP, decided by the backend (a
  module cannot pin itself). The shell loads it in safe mode, and
  nothing in the interface turns it off, so a broken module cannot take
  away the tool that fixes it. Elysium pins its own system sub-apps and
  always loads them, last.
- `activationEvents` -- optional: when the module's code runs besides
  one of its pages opening, VS Code's activation events. `onPalette`:
  when the command palette first opens, so the commands its code
  supplies are listed before any of its pages has been visited.
  `onStartup`: as soon as the frame is drawn, for a badge on its rail
  entry. A
  shell ignores an event it does not know (a newer backend's), and the
  module still loads with its pages; Elysium refuses an unknown one in a
  `module.json` at load, since there it is a typo.
- `contributes` -- **static**: read without running any of the
  module's code, so the rail and routes exist before anything loads
  (VS Code's `contributes`, Backstage's extension data).
  - `pages` -- each mounted at its `path`. A path belongs to the first
    module claiming it; a later claim is not mounted, and is listed in
    the registry's `problems` (Elysium logs them to the console until the
    module manager can show them).
  - `nav` -- rail entries; each must lead to one of the module's own
    pages. `subject` groups them: a subject's entries are drawn
    together, subjects in the order they first appear.
  - `redirects` -- old addresses kept, unless a page holds the path.

### `GET` and `PUT {base}/modules/arrangement`

For the module manager (step 1.4c), and only for someone the backend
lets change the deployment's modules. Every module the deployment knows
-- on and off, in rail order, pinned ones last -- with the pages each
holds and a `digest` of the arrangement as read:

```json
{ "home": "/query",
  "modules": [{ "id": "schema", "name": "Schema", "version": "1",
                "enabled": false, "pinned": false, "pages": ["/schema"] }],
  "digest": "9f1c..." }
```

`PUT` takes `{ home, modules: [[id, enabled], ...], digest }` -- every
module that is not pinned, in the order wanted -- and answers with the
arrangement as saved. A `digest` the backend no longer has is refused
(409) rather than merged; an arrangement that would not load (home
opening nothing) is refused (400) with nothing changed. Pinned modules
are never arranged. The feed changes for everyone; Elysium's pages
notice on their next request, which carries the new configuration
generation, and fetch the feed again.

### What the host supplies

The shell decides **where** a page is mounted; the host decides **what**
it is. `moduleRoutes(registry, resolve, home)` asks
`resolve(moduleId, pageId)` for a component; `null` mounts "nothing
loaded opens this page" rather than failing.

## The shell's system sub-app

`<ModulesPage feed={feed} loader={loader} />` lists every module the
feed offers, in rail order: its version, whether its code is its own
bundle or built into the page, and how it stands in this browser -- not
loaded yet (and on what it will load), loading, loaded, or failed and
why -- following the loader live (`loader.status(module)`,
`loader.subscribe`). A host mounts it as the page of a module its
backend marks `pinned`; Elysium's is `ui/src/system`, offered with
`manage:deployment`.

Given a `manager` (`read`, `save`, `refresh`, made from the host's own
client), it also offers the ARRANGEMENT FOR EVERYONE
(`ModuleArrangementEditor`): each module switched on or off and moved
up or down, where people land after signing in, saved as one with
Discard beside it, and "Refresh modules" to fetch the feed again -- a
bundle rebuilt since the page loaded then loads from its new address.

## Safe mode

`@shell/core/safeMode`: the page loaded with only the PINNED modules,
for when a module breaks it. Firefox's Troubleshoot Mode is the model --
temporary, entered from a menu or at start.

- THIS TAB, TEMPORARY: the switch is in the tab's session storage, so it
  holds across the page's own navigation and reloads, ends when the tab
  closes, and changes nothing on the server or in other tabs.
- ENTERING AND LEAVING RELOAD THE PAGE (`enterSafeMode`,
  `leaveSafeMode`): a module's imported code stays until a reload.
- `/?safe` opens it when no menu can be reached; `safeModeAtLoad()`
  reads it once, at load, and takes the marker out of the address.
- `safeFeed(feed)` is the feed it loads: pinned modules only, home moved
  to one of their pages if it was elsewhere.
- The frame says so above every page (`<Frame safeMode={{ onLeave }}>`);
  a module that fails to load offers a link to it, and never switches it
  on by itself; the Modules page (`safeMode`) says which modules it left
  out.

## A module's bundle

An ES module exporting:

```ts
export function activate(context: ModuleContext): ModuleActivation  // { pages: { [pageId]: Component } }
export function deactivate(): void                                    // optional
```

`activate` returns the pages its manifest declares, by id. The loader
(`@shell/core/moduleLoader`) fetches the bundle when one of its pages is
first opened, adds its `styles`, and hands the routes one component per
page, the same object every time. A bundle that cannot be fetched, has no
`activate`, or lacks the page asked for renders a sentence naming the
module and the reason; the shell carries on. Unloading removes the
stylesheets and calls `deactivate`; the browser keeps the code until the
page reloads.

A module builds its bundle with `moduleConfig` from
`@shell/build/moduleBuild` in its own `vite.config.ts`: one `index.js`
and one `index.css`, the page's shared libraries left as bare imports,
everything else bundled in. A deep import into a shared library
(`@blueprintjs/core/lib/...`) stops the build, since it would bundle a
private copy of part of something the page owns. A host adds
`builtModules({ configs })` so that its own build builds the modules and
its dev server rebuilds them on save.

## A module's tests

`@shell/build/testPreset` is the Vitest configuration a module's own
`vitest.config.ts` spreads into its `test` options, and the host's too,
so a fix reaches every module and the page at once:

```ts
test: { name: 'my-module', ...moduleTestConfig({ setupFiles: ['<the provider's setup>'] }) }
```

jsdom, a time zone that is not UTC (so date bugs show), threads, and
timeouts sized for a slow machine, each with its measurement in the
file. The host runs each module as a Vitest project of its own run.
What a module is tested FOR -- the test host and the conformance suite
-- is the provider's to ship, since it knows its own frame and API;
Elysium's is `ui/packages/testing` (`@elysium/testing`).

## Shared libraries

A module is built apart from the page, with the libraries the page
shares left as bare imports (`import { useState } from 'react'`). The
host's Vite config names them:

```ts
sharedLibraries({ libraries: ['react', 'react-dom/client', ...], packages: ['@shell/core', ...] })
```

and the plugin does three things:

1. **The registry.** `virtual:shared-registry`, which the page imports
   first, puts a loader for each shared library on
   `globalThis.__shellShared`. The loaders are the page's own imports, so
   a module gets the page's instance: one React, one router, one copy of
   any module-level state.
2. **The shims.** `/shared/<name>.js` per library, listing its export
   names and awaiting the page's copy. Libraries load lazily: a part the
   page does not use itself is fetched only when a module imports it.
3. **The import map**, first in `<head>`, sending each bare specifier to
   its shim. A specifier not in it cannot resolve, so a module must
   bundle anything the page does not promise.

Names are read exactly: npm packages by importing them in Node, the
host's own TypeScript packages by parsing them (an `export *` is
refused, since a parse cannot see through it). A host should test that
the names match the libraries; Elysium's `ui/src/sharedLibraries.test.ts`
does.

A shared library is available whole, because a module may use any part
of it; see Elysium's `ui/packages/shell-api/src/sharedLibraries.ts` for
what that cost and what it shares.

A host with a Content-Security-Policy must allow the import map: it is
an inline script. Elysium allows it by its hash (`'sha256-...'`), never
by `'unsafe-inline'` (api/app.py).

## Precedents

Piral's feed (name, version, link), VS Code's static `contributes` with
lazy activation, Backstage's extension ids and route references,
single-spa's lifecycle and import maps, and JupyterLab's prebuilt
extensions sharing singleton packages; for shared libraries, Native
Federation, which builds an import map from each remote's metadata. The
research is summarised in BLOCKING.md item 3.
