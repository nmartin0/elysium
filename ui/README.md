# Elysium web UI

A real client for the `api/` layer — login; ask a question (Query);
search and browse objects, with a real per-object detail page and
direct action invocation (Browse); approve or reject a proposed write;
see notifications and watches; read the ontology; and (for admins)
manage users, roles, silos, the mirror and deployment config. React +
TypeScript + Vite, no state management library, built on **Blueprint**
(`@blueprintjs/core`) — see the main project README's "Two ways to run
this" section for what `api/` actually exposes.

This paragraph once denied having a design system at all, which was
true of a phase-one API client and false from the Blueprint migration
onward. It mattered because this is the first thing a new contributor
reads, and it told them to hand-roll what the library already ships.
The standing rule is the opposite: **Blueprint always wins** — if a
new colour or component would mean overriding it, do not
(the interface design, consumed, and `index.css`'s own note on why
an element selector must never describe a widget the library owns).

An npm workspace, one package per real screen or shared concern, not
one monolithic app. **Each entry says what the package is FOR, not
what files it currently holds** — the previous version of this list
enumerated modules, and by the time anyone read it the enumeration was
a snapshot of an older codebase: four of shell-api's twenty-three
modules, two of app-browse's fourteen components, and three packages
missing altogether. A directory listing is always right; a copy of one
is right for a week. `ui/src/readme.test.ts` now fails if a package is
added and not named here.

```
MODULE_API.md              THE MODULE API'S GUIDE, for someone writing
                           a module: the manifest, activate(), host
                           values, styles, building and testing, the
                           add-on server, and the version rules.
module-api.report.md       THE PUBLIC MODULE API (BLOCKING.md item 3,
                           step 4): every name a module may rely on,
                           generated -- `python -m scripts.module_api_report`
                           -- and held current by a test. Not edited by
                           hand.
ui/src/                    App.tsx (auth state, routing, what is
                            fetched once and passed down), Shell.tsx
                            (what Elysium hands the shell's frame --
                            @shell/core/Frame), main.tsx, and system/:
                            the System sub-app, pinned, for
                            manage:deployment -- Modules, Add-on
                            servers, and Server (configuration, silos,
                            metrics, the mirror, cleaning).
ui/packages/shell-api/     Everything shared across screens: api.ts
                            (the one place that knows about fetch,
                            session and CSRF), formatting, the design
                            tokens and stylesheet, the shared hooks,
                            and the common components -- LoginForm,
                            PendingWriteCard, Workspace, AsyncPanel,
                            Chart and the rest.
ui/packages/app-query/     Query -- the agent question/answer screen,
                            with the step trace. ITS OWN BUNDLE (step
                            3): loaded when /query is first opened --
                            on most deployments, straight after login.
ui/packages/app-browse/    Browse -- search, per-object detail, direct
                            action invocation, charts, notes, history,
                            saved views, bulk actions, explore-related.
                            ITS OWN BUNDLE (step 3): a small entry with
                            its palette commands, asked for when the
                            palette first opens, and each page a chunk
                            of its own, fetched when first opened.
ui/packages/app-schema/    The ontology as a reference: object types,
                            link types, action types, and the schema
                            graph. ITS OWN BUNDLE: loaded when /schema
                            is first opened; the page never imports it.
ui/packages/app-approvals/ The write inbox -- review and decide a
                            proposed write -- and the enrichment,
                            prediction and unusual-value reviews. ITS
                            OWN BUNDLE (step 3): the Inbox's first four
                            tabs, loaded when the Inbox is first opened.
ui/packages/app-inbox/     The Inbox: one page whose tabs the queue
                           modules below fill, and the count of what is
                           waiting on its rail entry. ITS OWN BUNDLE
                           (step 3), loaded as the frame is drawn, since
                           the count is on every screen. Was ui/src/inbox;
                           a modules.yaml naming that is read as this.
ui/packages/app-identity/  Proposed merges -- decide whether two
                           records are the same thing, on the agreement
                           pattern rather than on values the reviewer
                           may not be cleared to read. ITS OWN BUNDLE
                           (step 3): the Inbox's Identity tab, loaded
                           when the tab is first opened.
ui/packages/app-notifications/
                           Notifications and the watch list. ITS OWN
                           BUNDLE (step 3): the Inbox's Notifications
                           tab, loaded when the tab is first opened.
ui/packages/app-admin/     Users and roles. ITS OWN BUNDLE (step 3),
                            loaded when /admin is first opened. The
                            server's own views --
                            deployment configuration, silos, metrics,
                            the mirror, cleaning -- moved to the System
                            sub-app's Server page (ui/src/system, step 3).
ui/packages/testing/       The test kit every sub-app's tests use: the
                            setup file, the test host (a page rendered
                            in the shell's frame against a stubbed
                            server), and the conformance suite.
```

## Development

```bash
npm install
npm run dev
```

Every real backend path lives under `/api` — Vite's own dev-server
proxy forwards `/api/*` to a backend running on
`http://localhost:8000` by default; start that separately (e.g.
`uvicorn api.app:app` from the project root). Override the target with
`VITE_API_PROXY_TARGET` if your backend runs elsewhere:

```bash
VITE_API_PROXY_TARGET=http://localhost:9000 npm run dev
```

## Testing, linting, and type checking

```bash
npm test              # vitest -- the full suite, once
npm run lint          # THE GATE: oxlint, the add-ons' lint, tsc --noEmit, oxfmt, knip
npm run typecheck     # tsc --noEmit alone
npm run format:check  # oxfmt -- verify formatting without changing anything
npm run format        # oxfmt -- fix formatting in place
npm run knip          # unused files, exports, and dependencies
npm run lint:addons   # oxlint and oxfmt over add-on pages kept outside ui/
```

FIVE checks make up the gate, and the behavioural suite sits beside
them: style and correctness (`oxlint`), the same two rules -- `oxlint`
and `oxfmt` -- over add-on pages whose source lives outside this folder
(`lint:addons`: the simulator's panel, ../sim/panel/web, which neither
tool will reach by a path leaving the folder), do the types agree
(`tsc --noEmit`), formatting (`oxfmt`), and does anything still use
this file, export or dependency at all (`knip`) — on top of `vitest`,
which exercises real user flows through React Testing Library rather
than shallow rendering. `tsconfig.json`'s own comments explain the
compiler options chosen and why.

It said "five separate checks" and then listed four, in a paragraph
whose next line said "all four run". The number was never load-bearing
and the disagreement is what made it worth fixing: a count that
contradicts its own list two lines later is the reader's first
evidence that a document has stopped being maintained.

**`npm run lint` runs all five**, in that order, and stops at the
first failure. It used to run only the first two, which is how 14
unused imports, an undeclared runtime dependency and 57 unformatted
files accumulated with the command reporting success the whole time.
The individual scripts above stay, for running one in isolation.

Note the `--deny-warnings` on oxlint inside that script: **a bare
`npx oxlint` exits 0 on warnings** and reports them anyway, so its
exit code alone is not a signal. Read the count, or go through
`npm run lint`.

### What every module is held to by default

A sub-app built as a MODULE (one with a `vitest.config.ts` of its own,
today the Schema graph) runs as its own Vitest project, inheriting the
same preset as the page (`@shell/build/testPreset`), and calls one
line in its own tests:

```ts
describeModule({ folder: <its folder>, activate })   // @elysium/testing/conformance
```

That runs the conformance checks on every page its `module.json`
declares: the manifest is valid and `activate` offers every page; the
page renders; it says it is loading (`role="status"`); it announces a
failure (`role="alert"`); an expired session hands over to sign-in; it
leaves no interval or listener running once unmounted; its stylesheets
keep every rule inside a layer.

Exceptions live in `module.conformance.json` beside `module.json`, by
check or `check@page`, the narrowest winning, and every one needs a
reason: `todo` runs the check and reports a failure without failing
(and FAILS once the check passes, so the list only shrinks), `off` does
not run it, `replaced` names the module's own stronger test as
`<file>::<test name>`. `python -m scripts.conformance_report` (from the repository root) lists every
module's exceptions.

The checks are tested themselves, against pages built to fail each one
(`packages/testing/src/samples.tsx`).

### Why `package.json` overrides `vitest`

`"overrides": { "vitest": "^4.1.12" }` keeps every package on the
project's own Vitest. Vite 8.2.4 and later name `@vitejs/devtools` as an
optional peer, and its `@vitejs/devtools-vitest` accepts ANY Vitest, so
npm resolved that peer to Vitest 5 -- a different major -- and npm 10's
own peer resolution then crashed ("Cannot read properties of null
(reading 'edgesOut')") on every install that touched Vite or Vitest.
Found 22 October, upgrading Vite 8.2.2 -> 8.3.5 and Vitest 4.1.11 ->
4.1.12 for the advisories `npm audit` reported. Raise the override with
Vitest itself.

## Production

```bash
npm run build
```

Produces `dist/` — `api/app.py` serves this automatically, from the
same process as the API itself, if it exists (see that file's own
docstring). `install/install.sh` runs this build step automatically
during a fresh install, if `npm` is available; it's skipped gracefully
otherwise, and the backend still runs correctly as an API-only
deployment either way.

## Why plain fetch(), no API client library

`packages/shell-api/src/api.ts` is the one place that knows about
headers, the session/CSRF cookies, and error shapes -- query/write
endpoints for every logged-in user, plus browse/search, per-object
detail, direct action invocation, and the admin account-management
endpoints (list/create/disable/enable/delete users, force-logout, the
visible-schema debug view), all gated server-side by whichever
grant actually applies -- this module never decides who's allowed to
call what. Relative paths throughout (`/login`, not a full URL) work
correctly in both dev (proxied) and production (same-origin, since the
backend serves this UI itself) without any environment-specific
configuration to keep in sync.
