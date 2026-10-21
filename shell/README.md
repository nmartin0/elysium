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
```

Its own npm project, with its own tests:

```
cd shell && npm install && npx vitest run && npx tsc --noEmit
```

A host depends on it by path (`"@shell/core": "file:../shell/core"`) and
must give the bundle one React: Elysium's `ui/vite.config.ts` dedupes
`react`, `react-dom` and `react-router-dom`, because a second copy would
give the shell's routes a router context the page does not have.

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

### What the host supplies

The shell decides **where** a page is mounted; the host decides **what**
it is. `moduleRoutes(registry, resolve, home)` asks
`resolve(moduleId, pageId)` for a component; `null` mounts "nothing
loaded opens this page" rather than failing.

## Precedents

Piral's feed (name, version, link), VS Code's static `contributes` with
lazy activation, Backstage's extension ids and route references,
single-spa's lifecycle and import maps, and JupyterLab's prebuilt
extensions sharing singleton packages. The research is summarised in
BLOCKING.md item 3.
